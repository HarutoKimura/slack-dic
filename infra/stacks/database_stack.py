"""
Database Stack for Slack RAG Bot.

Creates Aurora Serverless v2 PostgreSQL with pgvector extension.
Uses Data API for Lambda access without VPC connectivity.
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_rds as rds,
    aws_ec2 as ec2,
)
from constructs import Construct


class DatabaseStack(Stack):
    """Aurora Serverless v2 with Data API enabled."""

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # =======================================================
        # VPC for Aurora (required by RDS, but Lambda stays outside)
        # =======================================================
        self.vpc = ec2.Vpc(
            self,
            "AuroraVpc",
            max_azs=2,
            nat_gateways=0,  # No NAT needed - Lambda uses Data API (HTTP)
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                )
            ],
        )

        # Security group for Aurora (only internal access)
        aurora_security_group = ec2.SecurityGroup(
            self,
            "AuroraSecurityGroup",
            vpc=self.vpc,
            description="Security group for Aurora Serverless v2",
            allow_all_outbound=False,
        )
        # Allow inbound from within VPC (for Data API internal routing)
        aurora_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL from VPC",
        )

        # =======================================================
        # Aurora Serverless v2 with Data API
        # =======================================================
        self.cluster = rds.DatabaseCluster(
            self,
            "SlackRagCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_4,
            ),
            serverless_v2_min_capacity=0.5,  # Minimum ACU (~$0.06/hr when active)
            serverless_v2_max_capacity=2,  # Maximum ACU for scaling
            writer=rds.ClusterInstance.serverless_v2("writer"),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[aurora_security_group],
            default_database_name="slack_rag",
            enable_data_api=True,  # Enable Data API (HTTP-based access)
            removal_policy=RemovalPolicy.SNAPSHOT,  # Keep snapshot on delete
            backup=rds.BackupProps(retention=Duration.days(7)),
            storage_encrypted=True,
        )

        # Store reference to the secret (auto-generated credentials)
        self.secret = self.cluster.secret

        # =======================================================
        # Outputs (used by ApplicationStack and for reference)
        # =======================================================
        CfnOutput(
            self,
            "ClusterArn",
            value=self.cluster.cluster_arn,
            description="Aurora cluster ARN for Data API",
            export_name="SlackRagClusterArn",
        )

        CfnOutput(
            self,
            "ClusterEndpoint",
            value=self.cluster.cluster_endpoint.hostname,
            description="Aurora cluster endpoint",
            export_name="SlackRagClusterEndpoint",
        )

        CfnOutput(
            self,
            "SecretArn",
            value=self.secret.secret_arn,
            description="Secrets Manager ARN for database credentials",
            export_name="SlackRagSecretArn",
        )

        CfnOutput(
            self,
            "DatabaseName",
            value="slack_rag",
            description="Database name",
            export_name="SlackRagDatabaseName",
        )

        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            description="VPC ID (for reference only, Lambda runs outside)",
            export_name="SlackRagVpcId",
        )
