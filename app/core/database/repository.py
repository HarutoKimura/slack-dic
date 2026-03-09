"""
Message repository for CRUD operations and vector search.

Supports both Aurora Data API (production) and psycopg2 (local development).
"""

import json
import logging
from typing import Optional

from .connection import DatabaseConnection, get_connection
from .models import MessageChunk, SearchResult

logger = logging.getLogger(__name__)


class MessageRepository:
    """Repository for Slack message chunks with vector search."""

    def __init__(self, connection: Optional[DatabaseConnection] = None):
        """
        Initialize repository.

        Args:
            connection: Database connection. If None, creates one automatically.
        """
        self._conn = connection or get_connection()
        self._initialized = False

    def init_schema(self) -> None:
        """Initialize database schema (run once)."""
        if self._initialized:
            return

        # Enable pgvector extension
        self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # Create table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS slack_messages (
                id              VARCHAR(255) PRIMARY KEY,
                channel_id      VARCHAR(50) NOT NULL,
                channel_name    VARCHAR(255),
                message_ts      VARCHAR(50) NOT NULL,
                chunk_index     INTEGER DEFAULT 0,
                text            TEXT NOT NULL,
                embedding       vector(1536) NOT NULL,
                user_id         VARCHAR(50),
                user_name       VARCHAR(255),
                permalink       TEXT,
                indexed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata        JSONB DEFAULT '{}'
            )
        """)

        # Create indexes
        # Note: IVFFlat index requires existing data, create HNSW instead for empty table
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_slack_messages_embedding
            ON slack_messages USING hnsw (embedding vector_cosine_ops)
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_messages_channel "
            "ON slack_messages (channel_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_messages_ts "
            "ON slack_messages (message_ts)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_messages_channel_ts "
            "ON slack_messages (channel_id, message_ts)"
        )

        self._initialized = True
        logger.info("Database schema initialized")

    def upsert_chunk(self, chunk: MessageChunk) -> bool:
        """
        Insert or update a single message chunk.

        Returns True if inserted, False if already existed.
        """
        data = chunk.to_db_dict()
        embedding_str = "[" + ",".join(map(str, data["embedding"])) + "]"

        result = self._conn.execute(
            """
            INSERT INTO slack_messages
                (id, channel_id, channel_name, message_ts, chunk_index,
                 text, embedding, user_id, user_name, permalink, metadata)
            VALUES
                (:id, :channel_id, :channel_name, :message_ts, :chunk_index,
                 :text, :embedding::vector, :user_id, :user_name, :permalink, :metadata::jsonb)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            {
                "id": data["id"],
                "channel_id": data["channel_id"],
                "channel_name": data["channel_name"],
                "message_ts": data["message_ts"],
                "chunk_index": data["chunk_index"],
                "text": data["text"],
                "embedding": embedding_str,
                "user_id": data["user_id"],
                "user_name": data["user_name"],
                "permalink": data["permalink"],
                "metadata": json.dumps(data["metadata"]),
            },
        )
        return len(result) > 0

    def upsert_chunks(self, chunks: list[MessageChunk]) -> int:
        """
        Bulk upsert message chunks.

        Returns number of chunks inserted (not updated).
        """
        if not chunks:
            return 0

        sql = """
            INSERT INTO slack_messages
                (id, channel_id, channel_name, message_ts, chunk_index,
                 text, embedding, user_id, user_name, permalink, metadata)
            VALUES
                (:id, :channel_id, :channel_name, :message_ts, :chunk_index,
                 :text, :embedding::vector, :user_id, :user_name, :permalink, :metadata::jsonb)
            ON CONFLICT (id) DO NOTHING
        """

        parameter_sets = []
        for chunk in chunks:
            data = chunk.to_db_dict()
            embedding_str = "[" + ",".join(map(str, data["embedding"])) + "]"
            parameter_sets.append({
                "id": data["id"],
                "channel_id": data["channel_id"],
                "channel_name": data["channel_name"],
                "message_ts": data["message_ts"],
                "chunk_index": data["chunk_index"],
                "text": data["text"],
                "embedding": embedding_str,
                "user_id": data["user_id"],
                "user_name": data["user_name"],
                "permalink": data["permalink"],
                "metadata": json.dumps(data["metadata"]),
            })

        return self._conn.execute_many(sql, parameter_sets)

    def search_similar(
        self,
        embedding: list[float],
        top_k: int = 20,
        min_similarity: float = 0.25,
        channel_filter: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        Search for similar chunks using cosine similarity.

        Args:
            embedding: Query embedding vector (1536 dims)
            top_k: Maximum number of results
            min_similarity: Minimum similarity threshold (0-1)
            channel_filter: Optional channel ID to filter results

        Returns:
            List of SearchResult sorted by similarity (descending)
        """
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        if channel_filter:
            sql = """
                SELECT
                    id,
                    channel_name,
                    text,
                    message_ts,
                    permalink,
                    user_name,
                    1 - (embedding <=> :embedding::vector) AS similarity
                FROM slack_messages
                WHERE 1 - (embedding <=> :embedding::vector) > :min_similarity
                  AND channel_id = :channel_filter
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """
            params = {
                "embedding": embedding_str,
                "min_similarity": min_similarity,
                "channel_filter": channel_filter,
                "top_k": top_k,
            }
        else:
            sql = """
                SELECT
                    id,
                    channel_name,
                    text,
                    message_ts,
                    permalink,
                    user_name,
                    1 - (embedding <=> :embedding::vector) AS similarity
                FROM slack_messages
                WHERE 1 - (embedding <=> :embedding::vector) > :min_similarity
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """
            params = {
                "embedding": embedding_str,
                "min_similarity": min_similarity,
                "top_k": top_k,
            }

        rows = self._conn.execute(sql, params)

        return [
            SearchResult(
                id=row["id"],
                channel_name=row.get("channel_name"),
                text=row["text"],
                message_ts=row.get("message_ts"),
                permalink=row.get("permalink"),
                user_name=row.get("user_name"),
                similarity=float(row["similarity"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        """Get total number of indexed chunks."""
        result = self._conn.execute("SELECT COUNT(*) as count FROM slack_messages")
        return result[0]["count"] if result else 0

    def count_by_channel(self, channel_id: str) -> int:
        """Get number of indexed chunks for a specific channel."""
        result = self._conn.execute(
            "SELECT COUNT(*) as count FROM slack_messages WHERE channel_id = :channel_id",
            {"channel_id": channel_id},
        )
        return result[0]["count"] if result else 0

    def message_exists(self, channel_id: str, message_ts: str) -> bool:
        """Check whether any chunk for a message already exists."""
        result = self._conn.execute(
            """
            SELECT 1
            FROM slack_messages
            WHERE channel_id = :channel_id
              AND message_ts = :message_ts
            LIMIT 1
            """,
            {"channel_id": channel_id, "message_ts": message_ts},
        )
        return len(result) > 0

    def get_latest_timestamp(self, channel_id: str) -> Optional[str]:
        """Get the latest indexed message timestamp for a channel."""
        result = self._conn.execute(
            "SELECT MAX(message_ts) as max_ts FROM slack_messages WHERE channel_id = :channel_id",
            {"channel_id": channel_id},
        )
        if result and result[0].get("max_ts"):
            return result[0]["max_ts"]
        return None

    def get_indexed_channel_ids(self) -> set[str]:
        """Get set of all channel IDs that have been indexed."""
        result = self._conn.execute(
            "SELECT DISTINCT channel_id FROM slack_messages"
        )
        return {row["channel_id"] for row in result}

    def delete_by_channel(self, channel_id: str) -> int:
        """Delete all chunks from a specific channel. Returns deleted count."""
        result = self._conn.execute(
            "DELETE FROM slack_messages WHERE channel_id = :channel_id RETURNING id",
            {"channel_id": channel_id},
        )
        return len(result)

    def delete_all(self) -> int:
        """Delete all chunks. Returns deleted count."""
        result = self._conn.execute("DELETE FROM slack_messages RETURNING id")
        return len(result)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
