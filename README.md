# Slack RAG Bot (Serverless)

A serverless Slack RAG (Retrieval-Augmented Generation) bot that acts as an intelligent knowledge base for your workspace. Ask questions via DM or @mention, and get answers based on your Slack message history.

**Supports both English and Japanese messages.**

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                 SLACK                                        │
│                                                                              │
│   @mention / DM (questions)              Messages (indexed hourly)          │
│         │                                        │                           │
└─────────┼────────────────────────────────────────┼───────────────────────────┘
          │                                        │
          ▼                                        │ (Slack API fetch)
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                       │
│                                                                              │
│  ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐  │
│  │  API Gateway    │──────▶ │  Lambda         │──────▶ │  SQS Queue      │  │
│  │  /slack/events  │        │  (Receiver)     │        │  (QA Queue)     │  │
│  └─────────────────┘        └─────────────────┘        └────────┬────────┘  │
│                                                                  │           │
│  ┌─────────────────┐                                            ▼           │
│  │  EventBridge    │        ┌─────────────────┐        ┌─────────────────┐  │
│  │  (hourly)       │──────▶ │  Lambda         │        │  Lambda         │  │
│  └─────────────────┘        │  (Batch Indexer)│        │  (QA Processor) │  │
│                             └────────┬────────┘        └────────┬────────┘  │
│                                      │                          │           │
│                                      ▼                          ▼           │
│                     ┌───────────────────────────────────────────────────┐   │
│                     │          Aurora PostgreSQL Serverless v2          │   │
│                     │              (pgvector + Data API)                │   │
│                     └───────────────────────────────────────────────────┘   │
│                                      │                          │           │
│                                      ▼                          ▼           │
│                     ┌───────────────────────────────────────────────────┐   │
│                     │                Amazon Bedrock                      │   │
│                     │   (Titan Embeddings + Claude 3.5 Sonnet)          │   │
│                     └───────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Key Features

- **Serverless**: Pay only for what you use, auto-scaling, no idle costs
- **All AWS**: Single vendor for billing, support, and compliance
- **Hourly Batch Indexing**: Messages indexed every hour via EventBridge
- **RAG-based Answers**: Semantic search + LLM generation for accurate responses
- **Bilingual**: Handles English and Japanese with smart text chunking

## What It Does

| Trigger | Action |
|---------|--------|
| DM to bot | Search ALL indexed channels → return answer with sources |
| @mention in channel | Search all indexed messages → reply in thread |
| EventBridge (hourly) | Fetch new messages → chunk → embed → store in Aurora |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- AWS CLI v2 configured
- AWS CDK (`npm install -g aws-cdk`)
- Docker Desktop (for local development)

### Local Development

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Start PostgreSQL with pgvector
docker compose up -d postgres

# 3. Configure environment
cp .env.example .env
# Edit .env with your Slack tokens

# 4. Initialize database
psql -h localhost -U postgres -d slack_rag -f scripts/init_database.sql

# 5. Run tests
python -m pytest tests/ -v
```

## Usage

Once deployed, interact with the bot in two ways:

**DM the bot directly:**
```
You: 先月のプロジェクト進捗について教えて
Bot: #general チャンネルでの投稿によると、先月のプロジェクト進捗は...
     [Source: #general, 2026-02-15]
```

**@mention in a channel:**
```
You: @SlackRAGBot What was decided about the API redesign?
Bot: Based on discussions in #engineering, the team decided to...
     [Source: #engineering, 2026-02-10]
```

**Greetings and small talk** are handled naturally without searching the database:
```
You: こんにちは
Bot: こんにちは！何かお手伝いできることはありますか？
```

### AWS Deployment

```bash
# 1. Store Slack secrets in SSM
aws ssm put-parameter \
  --name "/slack-rag/slack-bot-token" \
  --value "xoxb-your-bot-token" \
  --type SecureString

aws ssm put-parameter \
  --name "/slack-rag/slack-signing-secret" \
  --value "your-signing-secret" \
  --type SecureString

# 2. Request Bedrock model access (AWS Console)
# - amazon.titan-embed-text-v1
# - anthropic.claude-3-5-sonnet-20240620-v1:0

# 3. Deploy
./scripts/deploy.sh deploy

# 4. Configure Slack app with the WebhookUrl from output
```

#### Deploy Script Commands

| Command | Description |
|---------|-------------|
| `bootstrap` | Bootstrap CDK (one-time per account/region) |
| `setup` | Setup CDK environment and install dependencies |
| `synth` | Synthesize CloudFormation templates |
| `diff` | Show diff between current and deployed stacks |
| `deploy` | Deploy all stacks (default) |
| `destroy` | Destroy all stacks |
| `init-db` | Initialize database schema via Data API |
| `secrets` | Check Slack secrets in SSM |

## Project Structure

```
slack-dic/
├── app/
│   ├── core/                      # Shared business logic
│   │   ├── bedrock/
│   │   │   ├── embeddings.py      # Titan Embeddings client
│   │   │   └── llm.py             # Claude 3.5 Sonnet client
│   │   ├── database/
│   │   │   ├── connection.py      # Dual-mode DB connection (Data API / psycopg2)
│   │   │   ├── repository.py      # CRUD + vector search
│   │   │   └── models.py          # Pydantic models
│   │   ├── rag/
│   │   │   ├── search.py          # Vector similarity search
│   │   │   └── answer.py          # RAG answer generation
│   │   └── slack/
│   │       ├── auth.py            # Signature verification
│   │       └── client.py          # Slack WebClient wrapper
│   │
│   ├── handlers/                  # Lambda entry points
│   │   ├── receiver.py            # Lambda 1: Webhook handler
│   │   ├── qa_processor.py        # Lambda 2: Question answering
│   │   └── batch_indexer.py       # Lambda 3: Hourly indexing
│   │
│   └── ingestion/
│       └── chunk.py               # Smart text chunking (EN + JP)
│
├── infra/                         # AWS CDK Infrastructure
│   ├── app.py                     # CDK entry point
│   └── stacks/
│       ├── database_stack.py      # Aurora Serverless v2 + VPC
│       └── application_stack.py   # Lambda + API GW + SQS + EventBridge
│
├── scripts/
│   ├── deploy.sh                  # Deployment helper
│   └── init_database.sql          # PostgreSQL schema with pgvector
│
├── tests/
│   ├── conftest.py                # Shared fixtures
│   └── unit/
│       ├── test_chunking.py       # Text chunking tests
│       ├── test_handlers.py       # Handler logic tests
│       ├── test_repository.py     # Database tests
│       └── test_slack_auth.py     # Authentication tests
│
├── docker-compose.yml             # PostgreSQL with pgvector (local dev)
├── pyproject.toml                 # Dependencies
└── .env.example                   # Environment template
```

## Setup

### 1. Create Slack App

Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**

#### OAuth Scopes (Bot Token Scopes)

| Scope | Purpose |
|-------|---------|
| `channels:history` | Read messages in public channels |
| `channels:read` | List public channels |
| `channels:join` | Join public channels |
| `groups:history` | Read messages in private channels |
| `groups:read` | List private channels |
| `chat:write` | Send messages |
| `im:history` | Read DM messages |
| `im:read` | Access DM info |
| `im:write` | Send DM replies |
| `app_mentions:read` | Respond to @mentions |
| `users:read` | Get user info |

#### Event Subscriptions

**Important**: Use HTTP mode (not Socket Mode)

1. Enable Event Subscriptions
2. Set Request URL to: `https://<api-gateway-id>.execute-api.<region>.amazonaws.com/slack/events`
3. Subscribe to bot events:
   - `app_mention` - Respond to @mentions
   - `message.im` - Receive DM questions

### 2. Configure Environment

Copy `.env.example` to `.env` and configure:

```env
# Slack Configuration (Required)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# Database Configuration
USE_DATA_API=false          # false for local, true for AWS Lambda

# Local PostgreSQL (when USE_DATA_API=false)
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DATABASE_NAME=slack_rag

# AWS Configuration
AWS_REGION=us-east-1

# Logging
LOG_LEVEL=INFO
```

### 3. Deploy to AWS

See the [AWS Deployment Guide](docs/implementation_summary.md#aws-deployment-guide) for detailed instructions.

## How It Works

### Data Flow 1: Question Answering

```
User @mentions bot or sends DM
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. Slack sends webhook to API Gateway                          │
│ 2. Receiver Lambda verifies signature, sends to SQS            │
│ 3. QA Processor Lambda picks up message                        │
│ 4. Embed question using Bedrock Titan (1536 dims)              │
│ 5. Query Aurora: SELECT by cosine similarity (top 5 chunks)    │
│ 6. Build prompt with retrieved context                         │
│ 7. Call Bedrock Claude to generate answer                      │
│ 8. Post reply to Slack thread                                  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
User receives answer (typically 3-8 seconds)
```

### Data Flow 2: Message Indexing (Hourly)

```
EventBridge triggers every hour
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. Batch Indexer Lambda starts                                 │
│ 2. Call Slack API: fetch messages from last hour              │
│ 3. Filter: skip bot messages, short messages                  │
│ 4. Chunk messages (respects URLs, code blocks, JP punctuation)│
│ 5. Batch embed chunks using Bedrock Titan                      │
│ 6. Bulk INSERT into Aurora (ON CONFLICT DO NOTHING)            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
Messages searchable within the hour
```

### Vector Search Query

```sql
SELECT text, channel_name, 1 - (embedding <=> query_vector) AS similarity
FROM slack_messages
WHERE 1 - (embedding <=> query_vector) > 0.25
ORDER BY embedding <=> query_vector
LIMIT 5;
```

## Technology Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Runtime | AWS Lambda (Python 3.12) | Serverless, pay-per-use |
| Database | Aurora PostgreSQL Serverless v2 | pgvector for vector search |
| DB Access | Data API | HTTP-based, no VPC needed for Lambda |
| Embeddings | Amazon Bedrock Titan | 1536 dimensions, multilingual |
| LLM | Amazon Bedrock Claude 3.5 Sonnet | High-quality generation |
| API | API Gateway HTTP API | Low latency, cost-effective |
| Queue | SQS with DLQ | Async processing, error handling |
| Scheduler | EventBridge | Hourly batch indexing |
| Secrets | SSM Parameter Store | Slack tokens |
| IaC | AWS CDK (Python) | Infrastructure as code |

## Configuration

### Environment Variables

#### Local Development

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_DATA_API` | `false` | Use psycopg2 for local PostgreSQL |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | `postgres` | PostgreSQL password |
| `DATABASE_NAME` | `slack_rag` | Database name |
| `SLACK_BOT_TOKEN` | required | Bot token (xoxb-...) |
| `SLACK_SIGNING_SECRET` | required | Webhook signature secret |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOOKBACK_HOURS` | `1` | Hours to look back for batch indexing |
| `FULL_BACKFILL` | `false` | Index full channel history when `true` |

#### AWS Lambda (set by CDK)

| Variable | Source | Description |
|----------|--------|-------------|
| `USE_DATA_API` | CDK | Always `true` in Lambda |
| `CLUSTER_ARN` | CDK output | Aurora cluster ARN |
| `SECRET_ARN` | CDK output | Secrets Manager ARN |
| `DATABASE_NAME` | CDK | `slack_rag` |
| `QA_QUEUE_URL` | CDK output | SQS queue URL |
| `SLACK_BOT_TOKEN_PARAM` | CDK | SSM parameter name |
| `SLACK_SIGNING_SECRET_PARAM` | CDK | SSM parameter name |
| `ALLOWED_CHANNELS` | CDK (optional) | Channel filter (comma-separated) |

## Testing

```bash
# Run all tests (requires PostgreSQL)
python -m pytest tests/ -v

# Run only unit tests (no PostgreSQL needed)
python -m pytest tests/unit/test_slack_auth.py tests/unit/test_chunking.py tests/unit/test_handlers.py -v

# Check database connection
USE_DATA_API=false python -c "
from app.core.database import MessageRepository
r = MessageRepository()
r.init_schema()
print(f'Database ready! Count: {r.count()}')
"
```

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_repository.py` | Database CRUD, vector search, similarity thresholds |
| `test_slack_auth.py` | Signature verification, replay attack prevention |
| `test_chunking.py` | Text splitting, Japanese support, URL preservation |
| `test_handlers.py` | Message parsing, bot filtering, event structure |

## Cost Estimate

### Monthly (~$45)

| Service | Usage | Cost |
|---------|-------|------|
| Aurora Serverless v2 | 0.5 ACU min | ~$40 |
| Lambda | ~1000 invocations | ~$0.50 |
| API Gateway | ~500 requests | ~$0.50 |
| SQS | ~1000 messages | ~$0.01 |
| Bedrock Titan | ~300K tokens | ~$0.03 |
| Bedrock Claude | ~150K tokens | ~$0.20 |
| CloudWatch | Logs | ~$3 |
| **Total** | | **~$45/month** |

### Cost Savings (Data API Architecture)

| What We Avoided | Saved |
|-----------------|-------|
| NAT Gateway | ~$30/month |
| VPC Endpoints | ~$15/month |
| RDS Proxy | ~$15/month |
| **Total Savings** | **~$60/month** |

## Troubleshooting

### Check CloudWatch Logs

```bash
# Receiver Lambda
aws logs tail /aws/lambda/slack-rag-receiver --follow

# QA Processor Lambda
aws logs tail /aws/lambda/slack-rag-qa-processor --follow

# Batch Indexer Lambda
aws logs tail /aws/lambda/slack-rag-batch-indexer --follow
```

### Check Dead Letter Queue

```bash
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name slack-rag-dlq --query 'QueueUrl' --output text)" \
  --attribute-names ApproximateNumberOfMessages
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Slack webhook not responding | Check Receiver Lambda logs, verify signing secret |
| Bot doesn't respond | Check QA Processor logs, verify bot token |
| No search results | Run batch indexer manually, check indexed message count |
| Low quality answers | Increase `top_k`, lower `min_similarity` threshold |

### Check Indexed Document Count

```bash
# Local
python -c "from app.core.database import MessageRepository; print(MessageRepository().count())"

# AWS (via Lambda)
aws lambda invoke \
  --function-name slack-rag-batch-indexer \
  --payload '{}' \
  response.json
```

## Japanese Language Support

The bot automatically handles Japanese text:

- **Sentence breaks**: `。` `！` `？` (full-width punctuation)
- **Clause breaks**: `、` (Japanese comma)
- **List markers**: `・` `①②③` `１.２.３.`
- **Smart tokenization**: Adjusts for Japanese token density

Works seamlessly with mixed English/Japanese content.

## Development

### Adding New Features

1. Create feature in `app/core/` for business logic
2. Update handlers in `app/handlers/` if Lambda interface changes
3. Update CDK stacks in `infra/stacks/` for infrastructure changes
4. Add tests in `tests/unit/`

### Code Style

```bash
# Format code
ruff format .

# Lint
ruff check .
```

## Documentation

- [Implementation Summary](docs/implementation_summary.md) - Technical details and deployment guide
- [Migration Plan](docs/serverless_migration_plan.md) - Architecture decisions and migration strategy

## License

MIT