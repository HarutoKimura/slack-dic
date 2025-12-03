"""Startup indexing - catch up on messages missed while bot was offline."""

import logging
from datetime import datetime, timedelta

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.ingestion.slack_fetch import get_channel_name
from app.ingestion.realtime import index_documents
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)


def get_joined_channels(client: WebClient) -> list[dict]:
    """Get all channels the bot is a member of."""
    channels = []
    cursor = None

    try:
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )

            for channel in response["channels"]:
                if channel.get("is_member", False):
                    channels.append({
                        "id": channel["id"],
                        "name": channel["name"],
                    })

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except SlackApiError as e:
        logger.error(f"Error fetching channels: {e}")

    return channels


def fetch_recent_messages(
    client: WebClient,
    channel_id: str,
    channel_name: str,
    hours: int = 24,
    limit: int = 500,
) -> list[dict]:
    """
    Fetch messages from the last N hours.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        channel_name: Channel name (for metadata)
        hours: How many hours back to fetch
        limit: Max messages to fetch

    Returns:
        List of normalized message documents
    """
    messages = []
    oldest = (datetime.now() - timedelta(hours=hours)).timestamp()

    try:
        response = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest),
            limit=limit,
        )

        for msg in response.get("messages", []):
            # Skip bot messages
            if msg.get("bot_id") or msg.get("subtype") == "bot_message":
                continue

            # Skip messages without text
            text = msg.get("text", "").strip()
            if not text:
                continue

            ts = msg.get("ts", "")
            user = msg.get("user", "unknown")

            doc = {
                "id": f"{channel_id}-{ts}",
                "channel": channel_id,
                "channel_name": channel_name,
                "text": text,
                "user": user,
                "ts": ts,
                "permalink": "",  # Skip permalink to speed up startup
            }
            messages.append(doc)

    except SlackApiError as e:
        logger.error(f"Error fetching messages from {channel_name}: {e}")

    return messages


def startup_index(
    client: WebClient,
    hours: int = 24,
    limit_per_channel: int = 500,
) -> int:
    """
    Index recent messages from all joined channels.
    Call this when the bot starts to catch up on missed messages.

    Args:
        client: Slack WebClient
        hours: How many hours back to index (default: 24)
        limit_per_channel: Max messages per channel (default: 500)

    Returns:
        Total number of chunks indexed
    """
    logger.info(f"Starting catch-up indexing (last {hours} hours)...")
    print(f"📥 Catch-up indexing: fetching messages from last {hours} hours...")

    # Get joined channels
    channels = get_joined_channels(client)
    if not channels:
        logger.info("No channels to index")
        return 0

    print(f"   Found {len(channels)} channels to check")

    total_messages = 0
    total_chunks = 0
    all_docs = []

    # Collect messages from all channels
    for channel in channels:
        channel_id = channel["id"]
        channel_name = channel["name"]

        messages = fetch_recent_messages(
            client, channel_id, channel_name, hours, limit_per_channel
        )

        if messages:
            all_docs.extend(messages)
            total_messages += len(messages)
            logger.info(f"Found {len(messages)} recent messages in #{channel_name}")

    if not all_docs:
        print("   No new messages to index")
        return 0

    print(f"   Found {total_messages} messages across {len(channels)} channels")

    # Index all at once (deduplication handled by ChromaDB via document IDs)
    try:
        num_chunks = index_documents(all_docs)
        total_chunks = num_chunks
        print(f"   ✅ Indexed {num_chunks} chunks from {total_messages} messages")
    except Exception as e:
        logger.error(f"Error indexing documents: {e}")
        print(f"   ❌ Error indexing: {e}")

    # Show total store count
    store = VectorStore()
    print(f"   Total documents in store: {store.count()}")

    return total_chunks
