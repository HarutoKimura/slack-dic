# Slack RAG Bot

A minimal Slack RAG (Retrieval-Augmented Generation) bot built with Python 3.11+, using OpenAI embeddings and GPT-5-mini for intelligent question answering over Slack message history.

## Features

- **Real-time indexing**: Automatically indexes new messages as they arrive in channels where the bot is present
- **Batch indexing**: Fetches and indexes historical messages from Slack channels
- Chunks text into manageable pieces with overlap
- Generates embeddings using OpenAI's `text-embedding-3-small`
- Stores vectors in local Chroma database with idempotent upserts
- Answers questions using GPT-5-mini with context from relevant messages
- Provides source Slack permalinks with answers
- Supports both Socket Mode (live bot) and CLI interfaces

## Architecture

```
.
├── app/
│   ├── main.py              # Entry point: Socket Mode or CLI
│   ├── settings.py          # Pydantic settings loader
│   ├── slack_app.py         # Bolt for Python app definition
│   ├── ingestion/
│   │   ├── slack_fetch.py   # Fetch Slack messages (batch)
│   │   ├── chunk.py         # Text chunking
│   │   └── realtime.py      # Real-time message indexing
│   ├── rag/
│   │   ├── embed.py         # OpenAI embeddings
│   │   ├── store.py         # Chroma vector DB
│   │   ├── search.py        # Vector search
│   │   └── answer.py        # LLM summarization
│   └── utils/
│       └── slack_links.py   # Slack permalink helpers
├── scripts/
│   ├── ingest_slack.py      # Bulk indexing script
│   └── ask_cli.py           # CLI testing script
├── .env                     # Environment variables (not in git)
└── .env.example             # Example environment variables
```

## Quick Start

```bash
# 1. Install dependencies
uv sync
uv pip install -e .

# 2. Configure your .env file
cp .env.example .env
# Edit .env with your API keys

# 3. Start the bot
uv run slack-rag-bot
```

## Setup

### 1. Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- OpenAI API key
- Slack Bot Token (with appropriate scopes)
- Slack App Token (optional, for Socket Mode)

### 2. Install Dependencies

```bash
# Install dependencies
uv sync

# Install the package in editable mode (required for imports to work)
uv pip install -e .
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required
OPENAI_API_KEY=sk-...
SLACK_BOT_TOKEN=xoxb-...

# Required for Socket Mode (use either variable name)
SLACK_APP_TOKEN=xapp-...
# OR
SOCKET_MODE_TOKEN=xapp-...

# Optional - Real-time indexing
REALTIME_INDEX_ENABLED=true
REALTIME_INDEX_CHANNELS=

# Optional (with defaults)
CHROMA_PERSIST_DIRECTORY=.chroma
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-5-mini-2025-08-07
```

### 4. Slack App Configuration

Create a Slack app at https://api.slack.com/apps with the following:

**OAuth & Permissions - Bot Token Scopes:**
- `channels:history` - View messages in public channels
- `channels:read` - View basic channel info
- `groups:history` - View messages in private channels (required for private channels)
- `groups:read` - View basic info about private channels (required for private channels)
- `chat:write` - Send messages
- `app_mentions:read` - View messages that mention your bot
- `commands` - Add slash commands (optional)

**Event Subscriptions:**
- Enable Events
- Subscribe to `app_mention` event
- Subscribe to `message.channels` event (for real-time indexing in public channels)
- Subscribe to `message.groups` event (for real-time indexing in private channels, optional)

**Socket Mode (recommended):**
- Enable Socket Mode
- Generate an App-Level Token with `connections:write` scope

**Install App:**
- Install the app to your workspace
- Copy the Bot Token and App Token to `.env`

## Usage

### Index Slack Messages

#### Batch Indexing (Historical Messages)

Fetch and index historical messages from a channel:

```bash
uv run python scripts/ingest_slack.py --channel "#all-slack-rag-test" --limit 2000
```

Options:
- `--channel`: Channel name (with or without #)
- `--limit`: Max messages to fetch (default: 2000)
- `--chunk-size`: Chunk size in chars (default: 600)
- `--chunk-overlap`: Overlap between chunks (default: 100)

#### Real-time Indexing (New Messages)

When the Slack bot is running in Socket Mode, it automatically indexes new messages in channels where the bot is present. No additional configuration needed!

**Configuration (optional):**

Add these to your `.env` file to control real-time indexing:

```env
# Enable/disable real-time indexing (default: true)
REALTIME_INDEX_ENABLED=true

# Only index messages from specific channels (default: all channels)
# Comma-separated list of channel IDs (e.g., C01234567,C89012345)
REALTIME_INDEX_CHANNELS=
```

**How it works:**
1. Invite the bot to a channel: `/invite @your-bot`
2. Start the bot: `uv run python app/main.py`
3. New messages in that channel are automatically indexed
4. Ask questions immediately without re-running batch ingestion

**Important:** The bot only indexes messages in channels where it's a member. Make sure to invite the bot to channels you want to index.

### Ask Questions (CLI)

Test the RAG system from the command line:

```bash
uv run python scripts/ask_cli.py --q "What is RAG?"
```

Options:
- `--q`: Your question
- `--top-k`: Number of context documents (default: 5)

### Run the Slack Bot

#### Socket Mode (Recommended)

If you have `SLACK_APP_TOKEN` or `SOCKET_MODE_TOKEN` configured:

```bash
# Option 1: Using the installed CLI command (recommended)
uv run slack-rag-bot

# Option 2: Using Python module syntax
uv run python -m app.main

# Option 3: Direct file path
uv run python app/main.py
```

The bot will:
- **Automatically index new messages** in channels where it's a member
- Listen for `@mentions` in channels
- Respond to `/ask` slash commands
- Reply in threads with answers and sources

#### CLI Test Mode

If Socket Mode token is not set, the app runs in interactive CLI mode:

```bash
uv run slack-rag-bot
```

### Interact with the Bot

**Via @mention:**
```
@rag-bot What features were discussed in yesterday's standup?
```

**Via /ask command:**
```
/ask What is our deployment process?
```

The bot will respond with an answer and source links:

```
Based on the channel history, the deployment process involves...

Sources:
- https://workspace.slack.com/archives/C.../p...
- https://workspace.slack.com/archives/C.../p...
```

## Project Structure

### Core Modules

- **app/settings.py**: Environment configuration using Pydantic
- **app/ingestion/slack_fetch.py**: Slack API integration for batch message retrieval
- **app/ingestion/chunk.py**: Text chunking with overlap
- **app/ingestion/realtime.py**: Real-time message indexing API
- **app/rag/embed.py**: OpenAI embedding generation with retry logic
- **app/rag/store.py**: Chroma vector database interface with idempotent upserts
- **app/rag/search.py**: Vector similarity search
- **app/rag/answer.py**: LLM-based answer generation
- **app/slack_app.py**: Slack Bolt app with event handlers (mentions, commands, messages)
- **app/main.py**: Application entry point

### Scripts

- **scripts/ingest_slack.py**: Bulk message indexing pipeline
- **scripts/ask_cli.py**: Command-line question interface

## Technical Details

### Text Chunking

Messages are split into 400-800 character chunks with 80-120 character overlap to:
- Fit within embedding context windows
- Preserve semantic continuity
- Improve retrieval accuracy

### Embeddings

Uses OpenAI's `text-embedding-3-small` model:
- 1536 dimensions
- Cost-effective
- High quality semantic representations
- Automatic rate limit handling with exponential backoff

### Vector Store

Chroma DB with:
- Local persistence (`.chroma/` directory)
- Cosine similarity search
- Metadata storage for source attribution
- Easy migration path to pgvector

### Answer Generation

GPT-5-mini (gpt-5-mini-2025-08-07) with:
- Max completion tokens: 2000
- Strict context-only answering
- Source URL attribution

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `SLACK_BOT_TOKEN` | Yes | - | Slack bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | Socket Mode | - | Socket Mode token (xapp-...) |
| `SOCKET_MODE_TOKEN` | Socket Mode | - | Alternative name for SLACK_APP_TOKEN |
| `CHROMA_PERSIST_DIRECTORY` | No | `.chroma` | Vector DB storage path |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `LLM_MODEL` | No | `gpt-5-mini-2025-08-07` | OpenAI chat model |
| `REALTIME_INDEX_ENABLED` | No | `true` | Enable real-time message indexing |
| `REALTIME_INDEX_CHANNELS` | No | `""` (all) | Comma-separated channel IDs to index |

**Note:** Use either `SLACK_APP_TOKEN` or `SOCKET_MODE_TOKEN` for Socket Mode (both work, use whichever you prefer).

## Troubleshooting

### "ModuleNotFoundError: No module named 'app'"

If you get this error when running the bot:

```bash
# Solution: Install the package in editable mode
uv pip install -e .

# Then use one of these commands:
uv run slack-rag-bot          # Recommended
uv run python -m app.main     # Alternative
```

### "Channel not found"

Make sure:
1. The bot is invited to the channel (`/invite @your-bot`)
2. The bot has `channels:read` and `channels:history` scopes
3. Channel name is correct (check case sensitivity)

### "No results found"

- Verify the vector store has data: check `.chroma/` directory
- Re-run ingestion if empty
- Try broader search terms

### Rate limit errors

The system includes automatic retry with exponential backoff. For large ingestion jobs:
- Reduce batch size in `embed.py`
- Add delays between batches
- Use a higher rate limit tier

### Socket Mode connection issues

Check:
1. `SLACK_APP_TOKEN` is set correctly
2. Socket Mode is enabled in your Slack app settings
3. App has required event subscriptions

## Future Enhancements

- [x] Incremental message updates (real-time indexing) - **Implemented!**
- [ ] Multiple channel support (batch indexing)
- [ ] Enhanced thread awareness for retrieval
- [ ] User-based filtering
- [ ] PostgreSQL + pgvector for production
- [ ] Hybrid search (keyword + semantic)
- [ ] Message metadata filtering (date, author, etc.)
- [ ] Answer quality evaluation
- [ ] Background queue for real-time indexing (async processing)

## License

MIT

## Contributing

This is a minimal reference implementation. Feel free to fork and extend!
