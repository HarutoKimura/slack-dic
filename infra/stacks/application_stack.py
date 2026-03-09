"""
Application Stack for Slack RAG Bot.

Creates Lambda functions, API Gateway, SQS queues, and EventBridge rules.
Lambda functions run OUTSIDE VPC and access Aurora via Data API.
"""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    BundlingOptions,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_logs as logs,
)
from constructs import Construct

from .database_stack import DatabaseStack


class ApplicationStack(Stack):
    """Lambda functions, API Gateway, SQS, and EventBridge."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        database_stack: DatabaseStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        asset_excludes = [
            ".venv",
            "__pycache__",
            "*.pyc",
            ".git",
            ".chroma",
            "infra",
            "tests",
            "docs",
            "scripts",
            "*.md",
            ".env",
            ".env.*",
            "docker-compose.yml",
        ]

        # =======================================================
        # SSM Parameters for Slack secrets
        # (User must create these manually before deployment)
        # =======================================================
        slack_bot_token_param = ssm.StringParameter.from_secure_string_parameter_attributes(
            self,
            "SlackBotTokenParam",
            parameter_name="/slack-rag/slack-bot-token",
        )

        slack_signing_secret_param = ssm.StringParameter.from_secure_string_parameter_attributes(
            self,
            "SlackSigningSecretParam",
            parameter_name="/slack-rag/slack-signing-secret",
        )

        # =======================================================
        # Dead Letter Queue (for failed messages)
        # =======================================================
        dlq = sqs.Queue(
            self,
            "DeadLetterQueue",
            queue_name="slack-rag-dlq",
            retention_period=Duration.days(14),
        )

        # =======================================================
        # QA Queue (questions to process)
        # =======================================================
        qa_queue = sqs.Queue(
            self,
            "QAQueue",
            queue_name="slack-rag-qa-queue",
            visibility_timeout=Duration.seconds(120),  # Must be >= Lambda timeout
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            ),
        )

        # =======================================================
        # Common Lambda environment variables
        # =======================================================
        common_env = {
            "CLUSTER_ARN": database_stack.cluster.cluster_arn,
            "SECRET_ARN": database_stack.secret.secret_arn,
            "DATABASE_NAME": "slack_rag",
            "USE_DATA_API": "true",  # Use Data API in production
            "LOG_LEVEL": "INFO",
        }

        # =======================================================
        # IAM Policies for Lambda
        # =======================================================
        # Data API access policy
        data_api_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "rds-data:ExecuteStatement",
                "rds-data:BatchExecuteStatement",
                "rds-data:BeginTransaction",
                "rds-data:CommitTransaction",
                "rds-data:RollbackTransaction",
            ],
            resources=[database_stack.cluster.cluster_arn],
        )

        # Secrets Manager access policy
        secrets_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["secretsmanager:GetSecretValue"],
            resources=[database_stack.secret.secret_arn],
        )

        # Bedrock access policy
        bedrock_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v1",
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-5-sonnet-20240620-v1:0",
            ],
        )

        # =======================================================
        # Lambda Layer for shared dependencies
        # =======================================================
        # Bundle dependencies into the Lambda asset (no separate layer).
        bundling = BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            command=[
                "bash",
                "-c",
                "pip install -r requirements.lambda.txt -t /asset-output "
                "&& cp -au app /asset-output/app",
            ],
            platform="linux/arm64",
        )
        lambda_code = lambda_.Code.from_asset(
            "../",
            bundling=bundling,
            exclude=asset_excludes,
        )

        # =======================================================
        # Lambda 1: Receiver (Webhook handler)
        # =======================================================
        receiver_lambda = lambda_.Function(
            self,
            "ReceiverLambda",
            function_name="slack-rag-receiver",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="app.handlers.receiver.handler",
            code=lambda_code,
            timeout=Duration.seconds(10),  # Slack requires response within 3s, but we use async
            memory_size=256,
            environment={
                **common_env,
                "QA_QUEUE_URL": qa_queue.queue_url,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant permissions
        slack_signing_secret_param.grant_read(receiver_lambda)
        qa_queue.grant_send_messages(receiver_lambda)

        # Add SSM parameter to environment (resolved at runtime)
        receiver_lambda.add_environment(
            "SLACK_SIGNING_SECRET_PARAM", "/slack-rag/slack-signing-secret"
        )

        # =======================================================
        # Lambda 2: QA Processor (Question answering)
        # =======================================================
        qa_processor_lambda = lambda_.Function(
            self,
            "QAProcessorLambda",
            function_name="slack-rag-qa-processor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="app.handlers.qa_processor.handler",
            code=lambda_code,
            timeout=Duration.seconds(90),  # RAG can take time
            memory_size=512,
            environment=common_env,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant permissions
        qa_processor_lambda.add_to_role_policy(data_api_policy)
        qa_processor_lambda.add_to_role_policy(secrets_policy)
        qa_processor_lambda.add_to_role_policy(bedrock_policy)
        slack_bot_token_param.grant_read(qa_processor_lambda)
        qa_queue.grant_consume_messages(qa_processor_lambda)

        qa_processor_lambda.add_environment(
            "SLACK_BOT_TOKEN_PARAM", "/slack-rag/slack-bot-token"
        )

        # SQS trigger
        qa_processor_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                qa_queue,
                batch_size=1,  # Process one question at a time
            )
        )

        # =======================================================
        # Lambda 3: Batch Indexer (Hourly indexing)
        # =======================================================
        batch_indexer_lambda = lambda_.Function(
            self,
            "BatchIndexerLambda",
            function_name="slack-rag-batch-indexer",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="app.handlers.batch_indexer.handler",
            code=lambda_code,
            timeout=Duration.seconds(300),  # 5 minutes for batch processing
            memory_size=1024,
            environment={
                **common_env,
                "ALLOWED_CHANNELS": "",  # Empty = all channels
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Grant permissions
        batch_indexer_lambda.add_to_role_policy(data_api_policy)
        batch_indexer_lambda.add_to_role_policy(secrets_policy)
        batch_indexer_lambda.add_to_role_policy(bedrock_policy)
        slack_bot_token_param.grant_read(batch_indexer_lambda)

        batch_indexer_lambda.add_environment(
            "SLACK_BOT_TOKEN_PARAM", "/slack-rag/slack-bot-token"
        )

        # =======================================================
        # EventBridge Rule (Hourly trigger for batch indexer)
        # =======================================================
        hourly_rule = events.Rule(
            self,
            "HourlyIndexerRule",
            rule_name="slack-rag-hourly-indexer",
            schedule=events.Schedule.rate(Duration.hours(1)),
            description="Trigger batch indexer every hour",
        )

        hourly_rule.add_target(targets.LambdaFunction(batch_indexer_lambda))

        # =======================================================
        # API Gateway (HTTP API for Slack webhooks)
        # =======================================================
        http_api = apigwv2.HttpApi(
            self,
            "SlackWebhookApi",
            api_name="slack-rag-webhook",
            description="HTTP API for Slack event webhooks",
        )

        # Add route for Slack events
        http_api.add_routes(
            path="/slack/events",
            methods=[apigwv2.HttpMethod.POST],
            integration=apigwv2_integrations.HttpLambdaIntegration(
                "ReceiverIntegration",
                receiver_lambda,
            ),
        )

        # =======================================================
        # Outputs
        # =======================================================
        CfnOutput(
            self,
            "WebhookUrl",
            value=f"{http_api.url}slack/events",
            description="Slack webhook URL (configure in Slack app settings)",
            export_name="SlackRagWebhookUrl",
        )

        CfnOutput(
            self,
            "QAQueueUrl",
            value=qa_queue.queue_url,
            description="SQS queue URL for QA processing",
            export_name="SlackRagQAQueueUrl",
        )

        CfnOutput(
            self,
            "DLQUrl",
            value=dlq.queue_url,
            description="Dead letter queue URL",
            export_name="SlackRagDLQUrl",
        )

        CfnOutput(
            self,
            "ReceiverLambdaArn",
            value=receiver_lambda.function_arn,
            description="Receiver Lambda ARN",
        )

        CfnOutput(
            self,
            "QAProcessorLambdaArn",
            value=qa_processor_lambda.function_arn,
            description="QA Processor Lambda ARN",
        )

        CfnOutput(
            self,
            "BatchIndexerLambdaArn",
            value=batch_indexer_lambda.function_arn,
            description="Batch Indexer Lambda ARN",
        )
