"""
Lambda 3: Batch Indexer

Hourly batch indexing of Slack messages into Aurora PostgreSQL.
- Fetches messages from the last hour from all joined channels
- Chunks messages using existing chunk.py logic
- Generates embeddings using Bedrock Titan
- Bulk inserts into Aurora via Data API

Triggered by: EventBridge (hourly schedule)
"""

import logging
import os
from datetime import datetime, timedelta

from app.core.bedrock import BedrockEmbeddings
from app.core.database import MessageRepository, MessageChunk
from app.core.slack.client import get_slack_client, get_channel_name, get_user_name, get_permalink
from app.ingestion.chunk import chunk_text

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Configuration
LOOKBACK_HOURS = 1
LOOKBACK_BUFFER_MINUTES = 5  # Extra buffer to catch edge cases
MIN_MESSAGE_LENGTH = 10  # Skip very short messages
BATCH_SIZE = 25  # Embedding batch size

# Channels to index (comma-separated IDs, empty = all joined channels)
ALLOWED_CHANNELS = set(
    filter(None, os.environ.get("ALLOWED_CHANNELS", "").split(","))
)

# Reusable clients
_embeddings = None
_repository = None


def get_embeddings() -> BedrockEmbeddings:
    """Get or create embeddings client."""
    global _embeddings
    if _embeddings is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _embeddings = BedrockEmbeddings(region_name=region)
    return _embeddings


def get_repository() -> MessageRepository:
    """Get or create message repository."""
    global _repository
    if _repository is None:
        _repository = MessageRepository()
    return _repository


def handler(event: dict, context) -> dict:
    """
    Lambda handler for batch indexing.

    Args:
        event: EventBridge event (unused)
        context: Lambda context

    Returns:
        Status dict with indexing metrics
    """
    logger.info("Starting batch indexer")

    # Calculate time range
    now = datetime.utcnow()
    oldest = (now - timedelta(hours=LOOKBACK_HOURS, minutes=LOOKBACK_BUFFER_MINUTES)).timestamp()
    latest = now.timestamp()

    logger.info(f"Fetching messages from {oldest} to {latest}")

    # Get all channels the bot is in
    channels = get_joined_channels()
    logger.info(f"Found {len(channels)} joined channels")

    # Filter channels if configured
    if ALLOWED_CHANNELS:
        channels = [c for c in channels if c["id"] in ALLOWED_CHANNELS]
        logger.info(f"Filtered to {len(channels)} allowed channels")

    total_indexed = 0
    total_skipped = 0
    embeddings = get_embeddings()
    repository = get_repository()

    for channel in channels:
        channel_id = channel["id"]
        channel_name = channel["name"]

        try:
            indexed, skipped = index_channel(
                channel_id=channel_id,
                channel_name=channel_name,
                oldest=oldest,
                latest=latest,
                embeddings=embeddings,
                repository=repository,
            )
            total_indexed += indexed
            total_skipped += skipped

        except Exception as e:
            logger.error(f"Failed to index channel {channel_name}: {e}", exc_info=True)
            continue

    logger.info(f"Batch indexing complete: {total_indexed} indexed, {total_skipped} skipped")

    return {
        "statusCode": 200,
        "body": {
            "indexed": total_indexed,
            "skipped": total_skipped,
            "channels_processed": len(channels),
        },
    }


def get_joined_channels() -> list[dict]:
    """
    Get all channels the bot has joined.

    Returns:
        List of dicts with 'id' and 'name' keys
    """
    client = get_slack_client()
    channels = []
    cursor = None

    while True:
        response = client.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            cursor=cursor,
        )

        for channel in response.get("channels", []):
            if channel.get("is_member"):
                channels.append({
                    "id": channel["id"],
                    "name": channel["name"],
                })

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return channels


def fetch_channel_messages(
    channel_id: str,
    oldest: float,
    latest: float,
) -> list[dict]:
    """
    Fetch messages from a channel within a time range.

    Args:
        channel_id: Slack channel ID
        oldest: Oldest timestamp (Unix)
        latest: Latest timestamp (Unix)

    Returns:
        List of Slack message dicts
    """
    client = get_slack_client()
    messages = []
    cursor = None

    while True:
        response = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest),
            latest=str(latest),
            cursor=cursor,
            limit=200,
        )

        messages.extend(response.get("messages", []))

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return messages


def index_channel(
    channel_id: str,
    channel_name: str,
    oldest: float,
    latest: float,
    embeddings: BedrockEmbeddings,
    repository: MessageRepository,
) -> tuple[int, int]:
    """
    Index messages from a single channel.

    Args:
        channel_id: Slack channel ID
        channel_name: Channel name
        oldest: Oldest timestamp
        latest: Latest timestamp
        embeddings: Embeddings client
        repository: Message repository

    Returns:
        Tuple of (indexed_count, skipped_count)
    """
    # Fetch messages
    messages = fetch_channel_messages(channel_id, oldest, latest)
    logger.debug(f"Fetched {len(messages)} messages from #{channel_name}")

    if not messages:
        return (0, 0)

    # Prepare chunks for indexing
    chunks_to_index = []
    skipped = 0

    for msg in messages:
        # Skip bot messages
        if msg.get("bot_id") or msg.get("subtype"):
            skipped += 1
            continue

        text = msg.get("text", "")
        if not text or len(text) < MIN_MESSAGE_LENGTH:
            skipped += 1
            continue

        ts = msg.get("ts")
        user_id = msg.get("user")

        # Get user name (cached)
        user_name = get_user_name(user_id) if user_id else None

        # Get permalink
        permalink = get_permalink(channel_id, ts)

        # Chunk the message
        text_chunks = chunk_text(text, chunk_size=500)

        for idx, chunk_text_content in enumerate(text_chunks):
            chunk_id = f"{channel_id}_{ts}_{idx}"

            chunks_to_index.append({
                "id": chunk_id,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "message_ts": ts,
                "chunk_index": idx,
                "text": chunk_text_content,
                "user_id": user_id or "",
                "user_name": user_name or "",
                "permalink": permalink or "",
            })

    if not chunks_to_index:
        return (0, skipped)

    # Generate embeddings in batches
    logger.debug(f"Generating embeddings for {len(chunks_to_index)} chunks")
    texts = [c["text"] for c in chunks_to_index]
    chunk_embeddings = embeddings.embed_batch(texts, batch_size=BATCH_SIZE)

    # Convert to MessageChunk models
    message_chunks = []
    for chunk_data, embedding in zip(chunks_to_index, chunk_embeddings):
        message_chunks.append(
            MessageChunk(
                id=chunk_data["id"],
                channel_id=chunk_data["channel_id"],
                channel_name=chunk_data["channel_name"],
                message_ts=chunk_data["message_ts"],
                chunk_index=chunk_data["chunk_index"],
                text=chunk_data["text"],
                embedding=embedding,
                user_id=chunk_data["user_id"],
                user_name=chunk_data["user_name"],
                permalink=chunk_data["permalink"],
            )
        )

    # Bulk insert
    indexed = repository.upsert_chunks(message_chunks)
    logger.info(f"Indexed {indexed} chunks from #{channel_name}")

    return (indexed, skipped)
