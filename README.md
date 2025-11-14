# Slack RAG Bot

A minimal Slack RAG (Retrieval-Augmented Generation) bot built with Python 3.11+, using OpenAI embeddings and GPT-5-mini for intelligent question answering over Slack message history.

## Features

- Fetches messages from Slack channels
- Chunks text into manageable pieces with overlap
- Generates embeddings using OpenAI's `text-embedding-3-small`
- Stores vectors in local Chroma database
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
│   │   ├── slack_fetch.py   # Fetch Slack messages
│   │   └── chunk.py         # Text chunking
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

## Setup

### 1. Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- OpenAI API key
- Slack Bot Token (with appropriate scopes)
- Slack App Token (optional, for Socket Mode)

### 2. Install Dependencies

```bash
uv sync
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

# Optional (for Socket Mode)
SLACK_APP_TOKEN=xapp-...

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
- `chat:write` - Send messages
- `app_mentions:read` - View messages that mention your bot
- `commands` - Add slash commands

**Event Subscriptions:**
- Enable Events
- Subscribe to `app_mention` event

**Socket Mode (recommended):**
- Enable Socket Mode
- Generate an App-Level Token with `connections:write` scope

**Install App:**
- Install the app to your workspace
- Copy the Bot Token and App Token to `.env`

## Usage

### Index Slack Messages

Fetch and index messages from a channel:

```bash
uv run python scripts/ingest_slack.py --channel "#all-slack-rag-test" --limit 2000
```

Options:
- `--channel`: Channel name (with or without #)
- `--limit`: Max messages to fetch (default: 2000)
- `--chunk-size`: Chunk size in chars (default: 600)
- `--chunk-overlap`: Overlap between chunks (default: 100)

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

If you have `SLACK_APP_TOKEN` configured:

```bash
uv run python app/main.py
```

The bot will:
- Listen for `@mentions` in channels
- Respond to `/ask` slash commands
- Reply in threads with answers and sources

#### CLI Test Mode

If `SLACK_APP_TOKEN` is not set, the app runs in interactive CLI mode:

```bash
uv run python app/main.py
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
- **app/ingestion/slack_fetch.py**: Slack API integration for message retrieval
- **app/ingestion/chunk.py**: Text chunking with overlap
- **app/rag/embed.py**: OpenAI embedding generation with retry logic
- **app/rag/store.py**: Chroma vector database interface
- **app/rag/search.py**: Vector similarity search
- **app/rag/answer.py**: LLM-based answer generation
- **app/slack_app.py**: Slack Bolt app with event handlers
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
| `SLACK_APP_TOKEN` | No | - | Slack app token for Socket Mode (xapp-...) |
| `CHROMA_PERSIST_DIRECTORY` | No | `.chroma` | Vector DB storage path |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `LLM_MODEL` | No | `gpt-5-mini-2025-08-07` | OpenAI chat model |

## Troubleshooting

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

- [ ] Incremental message updates (real-time indexing)
- [ ] Multiple channel support
- [ ] Conversation thread awareness
- [ ] User-based filtering
- [ ] PostgreSQL + pgvector for production
- [ ] Hybrid search (keyword + semantic)
- [ ] Message metadata filtering (date, author, etc.)
- [ ] Answer quality evaluation

## License

MIT

## Contributing

This is a minimal reference implementation. Feel free to fork and extend!
