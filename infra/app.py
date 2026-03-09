#!/usr/bin/env python3
"""
AWS CDK App for Slack RAG Bot.

Deploys:
- DatabaseStack: Aurora Serverless v2 with pgvector and Data API
- ApplicationStack: Lambda functions, API Gateway, SQS, EventBridge

Usage:
    cd infra
    uv sync
    cdk bootstrap  # One-time per account/region
    cdk deploy --all
"""

import aws_cdk as cdk

from stacks import DatabaseStack, ApplicationStack


app = cdk.App()

# Environment configuration
env = cdk.Environment(
    # Uncomment and set these for a specific account/region:
    # account="123456789012",
    # region="us-east-1",
    #
    # Or use environment variables:
    # account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    # region=os.environ.get("CDK_DEFAULT_REGION"),
)

# Stack names
stack_prefix = "SlackRag"

# =======================================================
# Database Stack (Aurora Serverless v2)
# =======================================================
database_stack = DatabaseStack(
    app,
    f"{stack_prefix}Database",
    description="Aurora Serverless v2 with pgvector for Slack RAG Bot",
    env=env,
)

# =======================================================
# Application Stack (Lambda, API Gateway, SQS)
# =======================================================
application_stack = ApplicationStack(
    app,
    f"{stack_prefix}Application",
    database_stack=database_stack,
    description="Lambda functions and API Gateway for Slack RAG Bot",
    env=env,
)

# Ensure database is created before application
application_stack.add_dependency(database_stack)

# Add tags to all resources
cdk.Tags.of(app).add("Project", "slack-rag")
cdk.Tags.of(app).add("Environment", "production")

app.synth()
