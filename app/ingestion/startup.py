"""Startup indexing - catch up on messages missed while bot was offline."""

import logging
from datetime import datetime, timedelta

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.ingestion.slack_fetch import get_channel_name, fetch_channel_messages
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


def get_indexed_channel_ids(store: VectorStore) -> set[str]:
    """
    Get the set of channel IDs that have at least one document in the vector store.
    """
    try:
        # Query all documents and extract unique channel IDs from metadata
        # ChromaDB doesn't have a direct "distinct" query, so we fetch a sample
        result = store.collection.get(
            limit=10000,  # Get up to 10k docs to check channels
            include=["metadatas"]
        )

        channel_ids = set()
        if result and result.get("metadatas"):
            for metadata in result["metadatas"]:
                if metadata and metadata.get("channel"):
                    channel_ids.add(metadata["channel"])

        return channel_ids
    except Exception as e:
        logger.error(f"Error getting indexed channels: {e}")
        return set()


def check_and_index_new_channels(
    client: WebClient,
    limit_per_channel: int = 1000,
) -> int:
    """
    Check for channels the bot has joined but haven't been indexed yet.
    This handles the case where bot was invited while offline.

    Args:
        client: Slack WebClient
        limit_per_channel: Max messages to index per new channel

    Returns:
        Number of new channels indexed
    """
    logger.info("Checking for unindexed channels...")
    print("🔍 Checking for new channels that need indexing...")

    # Get all channels bot is member of
    joined_channels = get_joined_channels(client)
    if not joined_channels:
        print("   No channels found")
        return 0

    joined_channel_ids = {ch["id"] for ch in joined_channels}

    # Get channels already in vector store
    store = VectorStore()
    indexed_channel_ids = get_indexed_channel_ids(store)

    # Find channels that are joined but not indexed
    new_channel_ids = joined_channel_ids - indexed_channel_ids

    if not new_channel_ids:
        print(f"   All {len(joined_channels)} channels are already indexed")
        return 0

    # Get channel info for new channels
    new_channels = [ch for ch in joined_channels if ch["id"] in new_channel_ids]

    print(f"   Found {len(new_channels)} new channel(s) to index:")
    for ch in new_channels:
        print(f"      - #{ch['name']}")

    # Index each new channel
    total_indexed = 0
    for channel in new_channels:
        channel_id = channel["id"]
        channel_name = channel["name"]

        print(f"   📥 Indexing #{channel_name}...")

        try:
            messages = fetch_channel_messages(client, channel_id, limit=limit_per_channel)

            if messages:
                num_chunks = index_documents(messages)
                print(f"      ✅ Indexed {num_chunks} chunks from {len(messages)} messages")
                total_indexed += 1
            else:
                print(f"      No messages found in #{channel_name}")

        except Exception as e:
            logger.error(f"Error indexing channel {channel_name}: {e}")
            print(f"      ❌ Error: {e}")

    print(f"   Total documents in store: {store.count()}")
    return total_indexed
