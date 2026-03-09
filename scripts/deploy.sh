#!/bin/bash
# Deployment script for Slack RAG Bot serverless infrastructure
#
# Prerequisites:
#   - AWS CLI v2 configured with credentials
#   - AWS CDK installed (npm install -g aws-cdk)
#   - uv installed for Python dependency management
#   - Bedrock model access granted (Titan Embeddings + Claude 3.5 Sonnet)
#
# Usage:
#   ./scripts/deploy.sh [deploy|synth|diff|destroy]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INFRA_DIR="$PROJECT_ROOT/infra"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found. Install with: brew install awscli"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Run: aws configure"
        exit 1
    fi

    # Check CDK
    if ! command -v cdk &> /dev/null; then
        log_error "AWS CDK not found. Install with: npm install -g aws-cdk"
        exit 1
    fi

    # Check uv
    if ! command -v uv &> /dev/null; then
        log_error "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    log_info "All prerequisites met!"
}

# Setup CDK environment
setup_cdk() {
    log_info "Setting up CDK environment..."

    cd "$INFRA_DIR"

    # Create virtual environment and install dependencies
    if [ ! -d ".venv" ]; then
        log_info "Creating virtual environment..."
        uv venv
    fi

    log_info "Installing CDK dependencies..."
    uv sync

    cd "$PROJECT_ROOT"
}

# Bootstrap CDK (one-time per account/region)
bootstrap_cdk() {
    log_info "Bootstrapping CDK..."

    cd "$INFRA_DIR"
    source .venv/bin/activate

    cdk bootstrap

    deactivate
    cd "$PROJECT_ROOT"
}

# Synthesize CloudFormation templates
synth() {
    log_info "Synthesizing CloudFormation templates..."

    cd "$INFRA_DIR"
    source .venv/bin/activate

    cdk synth

    deactivate
    cd "$PROJECT_ROOT"
}

# Show diff between current and deployed stack
diff() {
    log_info "Showing stack diff..."

    cd "$INFRA_DIR"
    source .venv/bin/activate

    cdk diff --all

    deactivate
    cd "$PROJECT_ROOT"
}

# Deploy all stacks
deploy() {
    log_info "Deploying stacks..."

    # Check for Slack secrets in SSM
    check_slack_secrets

    cd "$INFRA_DIR"
    source .venv/bin/activate

    cdk deploy --all --require-approval never

    deactivate
    cd "$PROJECT_ROOT"

    log_info "Deployment complete!"
    log_info "Don't forget to:"
    echo "  1. Copy the WebhookUrl from the output"
    echo "  2. Configure it in your Slack app (Event Subscriptions)"
    echo "  3. Run the database initialization script"
}

# Destroy all stacks
destroy() {
    log_warn "This will destroy all resources!"
    read -p "Are you sure? (yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        log_info "Aborted."
        exit 0
    fi

    cd "$INFRA_DIR"
    source .venv/bin/activate

    cdk destroy --all

    deactivate
    cd "$PROJECT_ROOT"
}

# Check if Slack secrets exist in SSM
check_slack_secrets() {
    log_info "Checking Slack secrets in SSM..."

    if ! aws ssm get-parameter --name "/slack-rag/slack-bot-token" --with-decryption &> /dev/null; then
        log_warn "Slack bot token not found in SSM."
        log_info "Create it with:"
        echo "  aws ssm put-parameter \\"
        echo "    --name '/slack-rag/slack-bot-token' \\"
        echo "    --value 'xoxb-your-token' \\"
        echo "    --type SecureString"
        echo ""
    fi

    if ! aws ssm get-parameter --name "/slack-rag/slack-signing-secret" --with-decryption &> /dev/null; then
        log_warn "Slack signing secret not found in SSM."
        log_info "Create it with:"
        echo "  aws ssm put-parameter \\"
        echo "    --name '/slack-rag/slack-signing-secret' \\"
        echo "    --value 'your-signing-secret' \\"
        echo "    --type SecureString"
        echo ""
    fi
}

# Initialize database schema
init_database() {
    log_info "Initializing database schema..."

    # Get cluster and secret ARNs from CloudFormation outputs
    CLUSTER_ARN=$(aws cloudformation describe-stacks \
        --stack-name SlackRagDatabase \
        --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" \
        --output text)

    SECRET_ARN=$(aws cloudformation describe-stacks \
        --stack-name SlackRagDatabase \
        --query "Stacks[0].Outputs[?OutputKey=='SecretArn'].OutputValue" \
        --output text)

    if [ -z "$CLUSTER_ARN" ] || [ -z "$SECRET_ARN" ]; then
        log_error "Could not get cluster ARNs. Make sure the database stack is deployed."
        exit 1
    fi

    log_info "Cluster ARN: $CLUSTER_ARN"
    log_info "Secret ARN: $SECRET_ARN"

    # Read and execute SQL file
    # Note: Data API doesn't support multi-statement execution,
    # so we need to execute statements one by one
    log_info "This feature requires manual execution. Run:"
    echo ""
    echo "  # Enable pgvector"
    echo "  aws rds-data execute-statement \\"
    echo "    --resource-arn '$CLUSTER_ARN' \\"
    echo "    --secret-arn '$SECRET_ARN' \\"
    echo "    --database 'slack_rag' \\"
    echo "    --sql 'CREATE EXTENSION IF NOT EXISTS vector'"
    echo ""
    echo "  # Then use the Python repository to initialize schema:"
    echo "  python -c \"from app.core.database import MessageRepository; MessageRepository().init_schema()\""
}

# Main
main() {
    case "${1:-deploy}" in
        bootstrap)
            check_prerequisites
            setup_cdk
            bootstrap_cdk
            ;;
        setup)
            check_prerequisites
            setup_cdk
            ;;
        synth)
            check_prerequisites
            setup_cdk
            synth
            ;;
        diff)
            check_prerequisites
            setup_cdk
            diff
            ;;
        deploy)
            check_prerequisites
            setup_cdk
            deploy
            ;;
        destroy)
            check_prerequisites
            setup_cdk
            destroy
            ;;
        init-db)
            init_database
            ;;
        secrets)
            check_slack_secrets
            ;;
        *)
            echo "Usage: $0 [bootstrap|setup|synth|diff|deploy|destroy|init-db|secrets]"
            echo ""
            echo "Commands:"
            echo "  bootstrap  Bootstrap CDK (one-time per account/region)"
            echo "  setup      Setup CDK environment"
            echo "  synth      Synthesize CloudFormation templates"
            echo "  diff       Show diff between current and deployed"
            echo "  deploy     Deploy all stacks (default)"
            echo "  destroy    Destroy all stacks"
            echo "  init-db    Initialize database schema"
            echo "  secrets    Check Slack secrets in SSM"
            exit 1
            ;;
    esac
}

main "$@"
