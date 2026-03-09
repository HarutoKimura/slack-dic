"""
Database connection manager with support for both:
- Local development: PostgreSQL via psycopg2
- Production (AWS): Aurora via Data API (boto3)

Switch between modes using the USE_DATA_API environment variable.
"""

import json
import os
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DatabaseConnection(ABC):
    """Abstract base class for database connections."""

    @abstractmethod
    def execute(
        self, sql: str, parameters: Optional[dict[str, Any]] = None
    ) -> list[dict]:
        """Execute SQL and return results as list of dicts."""
        pass

    @abstractmethod
    def execute_many(
        self, sql: str, parameter_sets: list[dict[str, Any]]
    ) -> int:
        """Execute SQL with multiple parameter sets. Returns affected rows."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""
        pass


class DataAPIConnection(DatabaseConnection):
    """
    Aurora Data API connection using boto3.

    Used in production Lambda environment.
    No VPC required - communicates via HTTP.
    """

    def __init__(
        self,
        cluster_arn: str,
        secret_arn: str,
        database: str = "slack_rag",
        region_name: str = "us-east-1",
    ):
        import boto3

        self._cluster_arn = cluster_arn
        self._secret_arn = secret_arn
        self._database = database
        self._client = boto3.client("rds-data", region_name=region_name)
        logger.info(f"Initialized Data API connection to {database}")

    def _convert_parameters(
        self, parameters: Optional[dict[str, Any]]
    ) -> list[dict]:
        """Convert Python dict parameters to Data API format."""
        if not parameters:
            return []

        result = []
        for name, value in parameters.items():
            param = {"name": name}
            if value is None:
                param["value"] = {"isNull": True}
            elif isinstance(value, bool):
                param["value"] = {"booleanValue": value}
            elif isinstance(value, int):
                param["value"] = {"longValue": value}
            elif isinstance(value, float):
                param["value"] = {"doubleValue": value}
            elif isinstance(value, str):
                param["value"] = {"stringValue": value}
            elif isinstance(value, bytes):
                param["value"] = {"blobValue": value}
            elif isinstance(value, list):
                # For vector embeddings, convert to string format
                param["value"] = {"stringValue": json.dumps(value)}
            elif isinstance(value, dict):
                param["value"] = {"stringValue": json.dumps(value)}
            else:
                param["value"] = {"stringValue": str(value)}
            result.append(param)
        return result

    def _parse_records(self, response: dict) -> list[dict]:
        """Parse Data API response records to list of dicts."""
        records = response.get("records", [])
        columns = [
            col.get("name", f"col_{i}")
            for i, col in enumerate(response.get("columnMetadata", []))
        ]

        result = []
        for record in records:
            row = {}
            for i, field in enumerate(record):
                col_name = columns[i] if i < len(columns) else f"col_{i}"
                # Extract value from Data API format
                if "isNull" in field and field["isNull"]:
                    row[col_name] = None
                elif "stringValue" in field:
                    row[col_name] = field["stringValue"]
                elif "longValue" in field:
                    row[col_name] = field["longValue"]
                elif "doubleValue" in field:
                    row[col_name] = field["doubleValue"]
                elif "booleanValue" in field:
                    row[col_name] = field["booleanValue"]
                elif "blobValue" in field:
                    row[col_name] = field["blobValue"]
                elif "arrayValue" in field:
                    row[col_name] = field["arrayValue"]
                else:
                    row[col_name] = None
            result.append(row)
        return result

    def execute(
        self, sql: str, parameters: Optional[dict[str, Any]] = None
    ) -> list[dict]:
        """Execute SQL using Data API."""
        kwargs = {
            "resourceArn": self._cluster_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "includeResultMetadata": True,
        }

        params = self._convert_parameters(parameters)
        if params:
            kwargs["parameters"] = params

        response = self._client.execute_statement(**kwargs)
        return self._parse_records(response)

    def execute_many(
        self, sql: str, parameter_sets: list[dict[str, Any]]
    ) -> int:
        """Execute batch SQL using Data API."""
        if not parameter_sets:
            return 0

        converted_sets = [
            self._convert_parameters(params) for params in parameter_sets
        ]

        # Data API supports up to 1000 parameter sets per batch
        total_affected = 0
        batch_size = 1000

        for i in range(0, len(converted_sets), batch_size):
            batch = converted_sets[i : i + batch_size]
            response = self._client.batch_execute_statement(
                resourceArn=self._cluster_arn,
                secretArn=self._secret_arn,
                database=self._database,
                sql=sql,
                parameterSets=batch,
            )
            total_affected += len(response.get("updateResults", []))

        return total_affected

    def close(self) -> None:
        """No-op for Data API (stateless)."""
        pass


class PsycopgConnection(DatabaseConnection):
    """
    Direct PostgreSQL connection using psycopg2.

    Used for local development with Docker PostgreSQL.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "slack_rag",
        user: str = "postgres",
        password: str = "postgres",
    ):
        import psycopg2
        from psycopg2.extras import RealDictCursor

        self._conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )
        self._conn.autocommit = True
        self._cursor_factory = RealDictCursor
        logger.info(f"Initialized psycopg2 connection to {database}@{host}:{port}")

    def execute(
        self, sql: str, parameters: Optional[dict[str, Any]] = None
    ) -> list[dict]:
        """Execute SQL using psycopg2."""
        # Convert named parameters from :name to %(name)s format
        if parameters:
            converted_sql = sql
            for name in parameters.keys():
                converted_sql = converted_sql.replace(f":{name}", f"%({name})s")
            sql = converted_sql

            # Handle vector embeddings - convert list to PostgreSQL array format
            converted_params = {}
            for name, value in parameters.items():
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], float):
                    # Vector embedding - format as PostgreSQL vector
                    converted_params[name] = "[" + ",".join(map(str, value)) + "]"
                elif isinstance(value, dict):
                    converted_params[name] = json.dumps(value)
                else:
                    converted_params[name] = value
            parameters = converted_params

        with self._conn.cursor(cursor_factory=self._cursor_factory) as cursor:
            cursor.execute(sql, parameters)
            if cursor.description:
                return [dict(row) for row in cursor.fetchall()]
            return []

    def execute_many(
        self, sql: str, parameter_sets: list[dict[str, Any]]
    ) -> int:
        """Execute batch SQL using psycopg2."""
        if not parameter_sets:
            return 0

        # Convert named parameters
        converted_sql = sql
        if parameter_sets:
            for name in parameter_sets[0].keys():
                converted_sql = converted_sql.replace(f":{name}", f"%({name})s")

        count = 0
        with self._conn.cursor() as cursor:
            for params in parameter_sets:
                # Handle vector embeddings
                converted_params = {}
                for name, value in params.items():
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], float):
                        converted_params[name] = "[" + ",".join(map(str, value)) + "]"
                    elif isinstance(value, dict):
                        converted_params[name] = json.dumps(value)
                    else:
                        converted_params[name] = value

                cursor.execute(converted_sql, converted_params)
                count += cursor.rowcount if cursor.rowcount > 0 else 1

        return count

    def close(self) -> None:
        """Close the psycopg2 connection."""
        if self._conn:
            self._conn.close()
            logger.info("Closed psycopg2 connection")


def get_connection() -> DatabaseConnection:
    """
    Factory function to get the appropriate database connection.

    Uses USE_DATA_API environment variable to switch between modes:
    - USE_DATA_API=true: Aurora Data API (production)
    - USE_DATA_API=false: psycopg2 (local development)

    Environment variables:
    - USE_DATA_API: "true" or "false"
    - CLUSTER_ARN: Aurora cluster ARN (Data API mode)
    - SECRET_ARN: Secrets Manager ARN (Data API mode)
    - DATABASE_NAME: Database name
    - AWS_REGION: AWS region (Data API mode)
    - DB_HOST: PostgreSQL host (local mode)
    - DB_PORT: PostgreSQL port (local mode)
    - DB_USER: PostgreSQL user (local mode)
    - DB_PASSWORD: PostgreSQL password (local mode)
    """
    use_data_api = os.environ.get("USE_DATA_API", "false").lower() == "true"

    if use_data_api:
        return DataAPIConnection(
            cluster_arn=os.environ["CLUSTER_ARN"],
            secret_arn=os.environ["SECRET_ARN"],
            database=os.environ.get("DATABASE_NAME", "slack_rag"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    else:
        return PsycopgConnection(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            database=os.environ.get("DATABASE_NAME", "slack_rag"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
        )
