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
import time
from datetime import datetime

from app.core.bedrock import BedrockEmbeddings
from app.core.database import MessageRepository, MessageChunk
from app.core.slack.client import get_slack_client, get_channel_name, get_user_name, get_permalink
from app.ingestion.chunk import chunk_text

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Configuration
DEFAULT_LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "1"))
LOOKBACK_BUFFER_MINUTES = int(os.environ.get("LOOKBACK_BUFFER_MINUTES", "5"))
FULL_BACKFILL = os.environ.get("FULL_BACKFILL", "false").lower() == "true"
MIN_MESSAGE_LENGTH = 10  # Skip very short messages
BATCH_SIZE = 25  # Embedding batch size
NOISE_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "channel_archive",
    "channel_unarchive",
    "group_join",
    "group_leave",
    "group_topic",
    "group_purpose",
    "group_name",
    "group_archive",
    "group_unarchive",
}

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
        event: EventBridge event (supports optional "days" override)
        context: Lambda context

    Returns:
        Status dict with indexing metrics
    """
    logger.info("Starting batch indexer")
    if FULL_BACKFILL:
        logger.warning("FULL_BACKFILL enabled: indexing full channel history")

    # Calculate time range
    now = datetime.utcnow()
    latest = now.timestamp()
    days = event.get("days") if isinstance(event, dict) else None
    manual_backfill = days is not None
    oldest_override = None

    if days is not None:
        try:
            days_value = float(days)
            if days_value < 0:
                raise ValueError("days must be non-negative")
            oldest_override = max(latest - (days_value * 24 * 3600), 0.0)
            logger.info(
                f"Using event days override: days={days_value}, oldest={oldest_override}"
            )
        except (TypeError, ValueError):
            logger.warning(
                f"Invalid 'days' value in event: {days!r}. "
                "Falling back to default lookback logic."
            )

    logger.info(f"Fetching messages up to {latest}")

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
        if oldest_override is not None:
            oldest = oldest_override
        else:
            oldest = calculate_oldest_timestamp(
                channel_id=channel_id,
                repository=repository,
                latest=latest,
            )
        logger.info(
            f"Indexing #{channel_name} from {oldest} to {latest}"
        )

        try:
            indexed, skipped = index_channel(
                channel_id=channel_id,
                channel_name=channel_name,
                oldest=oldest,
                latest=latest,
                embeddings=embeddings,
                repository=repository,
                stop_on_existing=not manual_backfill,
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


def calculate_oldest_timestamp(
    channel_id: str,
    repository: MessageRepository,
    latest: float,
) -> float:
    """
    Calculate the oldest timestamp to fetch for a channel.

    If the channel has indexed data, continue from the latest timestamp.
    Otherwise, backfill using the configured lookback window or full history.
    """
    if FULL_BACKFILL:
        return 0.0

    last_ts = repository.get_latest_timestamp(channel_id)
    if last_ts:
        try:
            return max(float(last_ts) - LOOKBACK_BUFFER_MINUTES * 60, 0.0)
        except ValueError:
            logger.warning(f"Invalid last_ts for channel {channel_id}: {last_ts}")

    return max(
        latest - (DEFAULT_LOOKBACK_HOURS * 3600) - (LOOKBACK_BUFFER_MINUTES * 60),
        0.0,
    )


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
        params = {
            "channel": channel_id,
            "latest": f"{latest:.6f}",
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        if oldest > 0:
            params["oldest"] = f"{oldest:.6f}"

        response = client.conversations_history(**params)

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
    stop_on_existing: bool = True,
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
        stop_on_existing: Stop scanning after first existing message (incremental mode)

    Returns:
        Tuple of (indexed_count, skipped_count)
    """
    client = get_slack_client()
    cursor = None
    total_indexed = 0
    total_skipped = 0

    while True:
        params = {
            "channel": channel_id,
            "latest": f"{latest:.6f}",
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        if oldest > 0:
            params["oldest"] = f"{oldest:.6f}"

        response = client.conversations_history(**params)
        messages = response.get("messages", [])
        logger.debug(
            "Fetched %s messages from #%s (cursor=%s)",
            len(messages),
            channel_name,
            "set" if cursor else "none",
        )

        if not messages:
            break

        chunks_to_index = []
        reached_oldest = False
        stop_scan = False

        for msg in messages:
            ts = msg.get("ts")
            if oldest > 0 and ts:
                try:
                    if float(ts) <= oldest:
                        reached_oldest = True
                except ValueError:
                    logger.debug(
                        "Skipping oldest boundary check for invalid ts=%s in #%s",
                        ts,
                        channel_name,
                    )

            # Skip bot messages
            if msg.get("bot_id"):
                total_skipped += 1
                continue

            subtype = msg.get("subtype")
            if subtype in NOISE_SUBTYPES:
                total_skipped += 1
                continue

            text = msg.get("text", "")
            if not text or len(text) < MIN_MESSAGE_LENGTH:
                total_skipped += 1
                continue

            user_id = msg.get("user")
            if not ts:
                total_skipped += 1
                continue

            if repository.message_exists(channel_id=channel_id, message_ts=ts):
                total_skipped += 1
                if stop_on_existing:
                    logger.info(
                        "Found already indexed message in #%s (ts=%s), stopping incremental scan",
                        channel_name,
                        ts,
                    )
                    stop_scan = True
                    break
                continue

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

        if chunks_to_index:
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

            # Bulk insert per page
            indexed = repository.upsert_chunks(message_chunks)
            total_indexed += indexed
            logger.info(f"Indexed {indexed} chunks from #{channel_name}")

        if stop_scan:
            break

        if reached_oldest:
            logger.info(
                "Reached oldest boundary in #%s (oldest=%s), stopping pagination",
                channel_name,
                oldest,
            )
            break

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

        time.sleep(1)

    return (total_indexed, total_skipped)
