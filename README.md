# Slack RAG Bot

A Slack RAG (Retrieval-Augmented Generation) bot that acts as an intelligent knowledge base for your workspace. Ask questions via DM or @mention, and get answers based on your Slack message history.

**Supports both English and Japanese messages.**

## What It Does

- **Ask via DM**: Send a direct message to the bot → it searches ALL indexed channels → returns an answer with sources
- **Ask via @mention**: Mention the bot in any channel → get answers from all indexed messages
- **Auto-indexing**: New messages are automatically indexed in real-time
- **Startup catch-up**: Missed messages while offline are indexed when the bot starts
- **Bilingual**: Handles English and Japanese text with smart chunking for both languages

## Quick Start

```bash
# 1. Install dependencies
uv sync
uv pip install -e .

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Join all public channels & index messages
python scripts/join_all_channels.py
python scripts/ingest_all_channels.py

# 4. Start the bot
python -m app.main
```

## Architecture

```
.
├── app/
│   ├── main.py              # Entry point with startup indexing
│   ├── settings.py          # Configuration (Pydantic)
│   ├── slack_app.py         # Slack event handlers (DM, mention, real-time)
│   ├── ingestion/
│   │   ├── slack_fetch.py   # Fetch Slack messages
│   │   ├── chunk.py         # Smart text chunking
│   │   ├── realtime.py      # Real-time message indexing
│   │   └── startup.py       # Startup catch-up indexing
│   ├── rag/
│   │   ├── embed.py         # OpenAI embeddings
│   │   ├── store.py         # ChromaDB vector store
│   │   ├── search.py        # Vector similarity search
│   │   └── answer.py        # LLM answer generation
│   └── utils/
│       └── slack_links.py   # Slack permalink helpers
├── scripts/
│   ├── ingest_all_channels.py  # Index all public channels
│   ├── ingest_slack.py         # Index single channel
│   ├── join_all_channels.py    # Bot joins all public channels
│   └── ask_cli.py              # CLI testing
├── .chroma/                 # Vector database (local storage)
└── .env                     # Environment variables
```

## Setup

### 1. Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- OpenAI API key
- Slack workspace with admin access

### 2. Create Slack App

Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**

#### OAuth Scopes (Bot Token Scopes)

| Scope | Purpose |
|-------|---------|
| `channels:history` | Read messages in public channels |
| `channels:read` | List public channels |
| `channels:join` | Join public channels automatically |
| `groups:history` | Read messages in private channels |
| `groups:read` | List private channels |
| `chat:write` | Send messages |
| `im:history` | Read DM messages |
| `im:read` | Access DM info |
| `im:write` | Send DM replies |
| `app_mentions:read` | Respond to @mentions |
| `users:read` | Get user info |
| `users:read.email` | Get user emails |

#### Event Subscriptions

Subscribe to these bot events:
- `app_mention` - Respond to @mentions
- `message.channels` - Index public channel messages
- `message.groups` - Index private channel messages
- `message.im` - Receive DM questions
- `member_joined_channel` - Auto-index when bot is invited to a channel

#### App Home

- Enable **Messages Tab**
- Check **"Allow users to send messages"**

#### Socket Mode

- Enable Socket Mode
- Generate App-Level Token with `connections:write` scope

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
OPENAI_API_KEY=sk-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Optional - Indexing
REALTIME_INDEX_ENABLED=true
STARTUP_INDEX_ENABLED=true
STARTUP_INDEX_HOURS=24

# Optional - RAG
MIN_SIMILARITY=0.25
CHROMA_PERSIST_DIRECTORY=.chroma
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-5-mini-2025-08-07
```

### 4. Install & Run

```bash
# Install dependencies
uv sync
uv pip install -e .

# Join all public channels (one-time)
python scripts/join_all_channels.py

# Index historical messages (one-time)
python scripts/ingest_all_channels.py --limit 5000

# Start the bot
python -m app.main
```

## Usage

### Ask Questions

**Via DM (recommended for searching all channels):**
```
You: What is our deployment process?
Bot: Based on messages from #engineering and #devops...
     Sources: [links]
```

**Via @mention (in any channel):**
```
@rag-bot What was discussed about the new feature?
```

**Via /ask command:**
```
/ask Who is responsible for the billing system?
```

### Scripts

```bash
# Index all public channels
python scripts/ingest_all_channels.py --limit 5000

# Index single channel
python scripts/ingest_slack.py --channel "general" --limit 2000

# Join all public channels (bot must be member to index)
python scripts/join_all_channels.py

# Dry run (see what will be indexed/joined)
python scripts/ingest_all_channels.py --dry-run
python scripts/join_all_channels.py --dry-run

# Check vector store status
python -c "from app.rag.store import VectorStore; print(f'Docs: {VectorStore().count()}')"
```

## How It Works

### Indexing Flow

```
Slack Message → Chunking → Embedding → ChromaDB
                  ↓           ↓
            600 chars    OpenAI API
            smart split  text-embedding-3-small
```

1. **Fetch**: Messages retrieved from Slack API
2. **Chunk**: Split into ~600 char pieces at sentence boundaries
3. **Embed**: Convert to 1536-dim vectors via OpenAI
4. **Store**: Save in ChromaDB with metadata (channel, user, timestamp, permalink)

### Search Flow

```
Question → Embedding → Vector Search → Top 5 chunks → LLM → Answer
                           ↓
                      ChromaDB
                      cosine similarity
```

1. **Embed question**: Same embedding model as indexing
2. **Search**: Find most similar chunks in vector DB
3. **Generate**: LLM creates answer using retrieved context
4. **Cite**: Include source permalinks

### Auto-Indexing

| Trigger | What happens |
|---------|--------------|
| Bot starts | Check for unindexed channels, then index last 24 hours |
| Bot invited to channel | Automatically index channel history in background |
| New message in channel | Index immediately (real-time) |
| DM received | Search all indexed channels, return answer |

**No manual indexing required!** Once the bot is set up, it automatically handles:
- Channels joined while offline (indexed on next startup)
- New channel invitations (indexed immediately in background)
- New messages (indexed in real-time)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | required | OpenAI API key |
| `SLACK_BOT_TOKEN` | required | Bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | required | App token for Socket Mode (xapp-...) |
| `CHROMA_PERSIST_DIRECTORY` | `.chroma` | Vector DB location |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `LLM_MODEL` | `gpt-5-mini-2025-08-07` | OpenAI chat model |
| `MIN_SIMILARITY` | `0.25` | Minimum similarity threshold |
| `REALTIME_INDEX_ENABLED` | `true` | Auto-index new messages |
| `REALTIME_INDEX_CHANNELS` | `""` (all) | Limit to specific channel IDs |
| `STARTUP_INDEX_ENABLED` | `true` | Catch-up index on startup |
| `STARTUP_INDEX_HOURS` | `24` | Hours to look back on startup |

## Troubleshooting

### "Sending messages to this app has been turned off"

1. Go to Slack App settings → **App Home**
2. Enable **Messages Tab**
3. Check **"Allow users to send Slash commands and messages"**
4. Reinstall app to workspace

### "not_in_channel" error when indexing

The bot must be a member of channels to read messages:
```bash
python scripts/join_all_channels.py
```

### Bot doesn't respond to DMs

1. Check `im:history`, `im:read`, `im:write` scopes are added
2. Subscribe to `message.im` event
3. Reinstall app after scope changes

### Low quality answers / wrong sources

- Increase indexed messages: `--limit 10000`
- Check similarity threshold in `.env`: `MIN_SIMILARITY=0.2`
- Verify content is indexed: check `store.count()`

### Check indexed document count

```bash
python -c "from app.rag.store import VectorStore; print(VectorStore().count())"
```

### Clear and re-index

```bash
rm -rf .chroma/
python scripts/ingest_all_channels.py --limit 5000
```

## Docker Deployment

### Quick Start with Docker

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

Make sure your `.env` file contains:
```env
OPENAI_API_KEY=sk-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...   # or SOCKET_MODE_TOKEN
```

### Docker Commands

| Command | Description |
|---------|-------------|
| `docker compose up -d` | Start bot in background |
| `docker compose up -d --build` | Rebuild and start |
| `docker compose logs -f` | Watch logs in real-time |
| `docker compose ps` | Check container status |
| `docker compose restart` | Restart the bot |
| `docker compose down` | Stop the bot |
| `docker compose down -v` | Stop and delete vector DB data |

### Data Persistence

Vector database is stored in a Docker volume (`chroma-data`). Your indexed messages persist across container restarts.

```bash
# View volume
docker volume ls | grep chroma

# Backup volume (optional)
docker run --rm -v slack-dic_chroma-data:/data -v $(pwd):/backup alpine tar czf /backup/chroma-backup.tar.gz /data
```

## Production Deployment

### Phase 1: Local Testing
1. Run on your machine with `python -m app.main` or Docker
2. Vector DB stored in `.chroma/` folder (local) or Docker volume
3. Good for validating with real data

### Phase 2: Cloud Deployment (AWS EC2)

1. Launch EC2 instance (t3.medium recommended for 10-50 users)
2. Install Docker:
   ```bash
   sudo yum update -y
   sudo yum install -y docker
   sudo service docker start
   sudo usermod -a -G docker ec2-user
   ```
3. Copy project files and `.env` to EC2
4. Run with Docker:
   ```bash
   docker compose up -d
   ```

### Scaling Guide

| Users | EC2 Instance | Notes |
|-------|--------------|-------|
| <10 | t3.small | Testing/development |
| 10-50 | t3.medium | Small team |
| 50-100 | t3.large | Consider managed vector DB |
| 100+ | Multiple instances | Use Pinecone + HTTP mode |

### Alternative Deployment Options
- **Container**: AWS ECS, GCP Cloud Run, DigitalOcean App Platform
- **PaaS**: Railway, Render, Heroku

### Vector DB Options for Scale
- **Self-hosted ChromaDB**: Current setup, good for <100 users
- **Pinecone**: Managed vector DB (recommended for scale)
- **Weaviate Cloud**: Alternative managed option
- **PostgreSQL + pgvector**: If you need SQL

## Data Storage

| Data | Location | Persistence |
|------|----------|-------------|
| Vector embeddings | `.chroma/` | Local filesystem |
| Configuration | `.env` | Local file |
| Slack messages | Slack API | Fetched on-demand |

## Step-by-Step Setup Guide

### Complete Setup Flow

```
┌─────────────────────────────────────────────────────────────┐
│  1. CREATE SLACK APP                                        │
│     api.slack.com/apps → Create New App                     │
│     Add OAuth scopes, Event subscriptions, Enable Socket    │
│     Mode, Enable Messages Tab in App Home                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  2. INSTALL APP TO WORKSPACE                                │
│     Install App → Copy Bot Token & App Token to .env        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  3. JOIN CHANNELS                                           │
│     python scripts/join_all_channels.py                     │
│     (Bot must be member of channels to read messages)       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  4. INDEX MESSAGES                                          │
│     python scripts/ingest_all_channels.py                   │
│     (Stores messages in vector database)                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  5. START BOT                                               │
│     python -m app.main                                      │
│     (Now ready to answer questions!)                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  6. ASK QUESTIONS                                           │
│     • Send DM to bot → searches ALL indexed channels        │
│     • @mention in channel → answers from all channels       │
│     • New messages auto-indexed while bot is running        │
└─────────────────────────────────────────────────────────────┘
```

### Key Points

| Requirement | Why |
|-------------|-----|
| Bot must join channel | Slack API requires membership to read messages |
| Must run indexing script | Messages need to be stored in vector DB before searching |
| No need to @mention before DM | DM works as soon as messages are indexed |

### Adding a New Channel Later

Simply invite the bot to the channel - it will automatically index the channel history:

```
/invite @your-bot-name
```

The bot will:
1. Send a message: "Thanks for inviting me! I'm now indexing..."
2. Index all messages in the background
3. Notify when complete: "Indexing complete! I've indexed X messages"

**No manual scripts needed!** The bot handles everything automatically.

For bulk operations (e.g., joining all public channels at once):
```bash
python scripts/join_all_channels.py
```

## Japanese Language Support

The bot automatically handles Japanese text:

- **Sentence breaks**: `。` `！` `？` (full-width punctuation)
- **Clause breaks**: `、` (Japanese comma)
- **List markers**: `・` `①②③` `１.２.３.`
- **Smart tokenization**: Adjusts for Japanese token density

Works seamlessly with mixed English/Japanese content in the same workspace.

## License

MIT
