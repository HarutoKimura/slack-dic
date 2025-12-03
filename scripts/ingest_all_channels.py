"""Bulk ingestion script for ALL public Slack channels."""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.ingestion.realtime import index_documents
from app.ingestion.slack_fetch import fetch_channel_messages
from app.settings import settings


def get_all_public_channels(client: WebClient) -> list[dict]:
    """
    Fetch all public channels the bot has access to.

    Returns:
        List of channel dicts with 'id' and 'name' keys
    """
    channels = []
    cursor = None

    try:
        while True:
            response = client.conversations_list(
                types="public_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )

            for channel in response["channels"]:
                # Only include channels where bot is a member
                if channel.get("is_member", False):
                    channels.append({
                        "id": channel["id"],
                        "name": channel["name"],
                        "num_members": channel.get("num_members", 0),
                    })

            # Check for more pages
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except SlackApiError as e:
        print(f"Error fetching channels: {e}")

    return channels


def main():
    """Main ingestion script for all channels."""
    parser = argparse.ArgumentParser(
        description="Index ALL public Slack channels into vector store"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum messages per channel (default: 1000)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=600,
        help="Text chunk size (default: 600)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=100,
        help="Chunk overlap (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List channels without indexing",
    )

    args = parser.parse_args()

    # Initialize Slack client
    print("Initializing Slack client...")
    client = WebClient(token=settings.slack_bot_token)

    # Get all public channels
    print("Fetching all public channels...")
    channels = get_all_public_channels(client)

    if not channels:
        print("No channels found. Make sure the bot is added to at least one channel.")
        return

    print(f"\nFound {len(channels)} channels the bot is a member of:")
    for ch in channels:
        print(f"  - #{ch['name']} ({ch['id']}) - {ch['num_members']} members")

    if args.dry_run:
        print("\n[Dry run] No indexing performed.")
        return

    print(f"\n{'='*60}")
    print(f"Starting indexing (max {args.limit} messages per channel)...")
    print(f"{'='*60}\n")

    total_messages = 0
    total_chunks = 0
    failed_channels = []

    for i, channel in enumerate(channels, 1):
        channel_name = channel["name"]
        channel_id = channel["id"]

        print(f"[{i}/{len(channels)}] Indexing #{channel_name}...")

        try:
            # Fetch messages
            messages = fetch_channel_messages(client, channel_id, limit=args.limit)

            if not messages:
                print(f"  No messages found in #{channel_name}, skipping.")
                continue

            # Index documents
            num_chunks = index_documents(
                messages,
                chunk_size=args.chunk_size,
                overlap=args.chunk_overlap,
            )

            total_messages += len(messages)
            total_chunks += num_chunks
            print(f"  ✅ Indexed {num_chunks} chunks from {len(messages)} messages\n")

        except Exception as e:
            print(f"  ❌ Failed to index #{channel_name}: {e}\n")
            failed_channels.append(channel_name)

    # Summary
    print(f"\n{'='*60}")
    print("INDEXING COMPLETE")
    print(f"{'='*60}")
    print(f"Channels processed: {len(channels)}")
    print(f"Total messages indexed: {total_messages}")
    print(f"Total chunks created: {total_chunks}")

    if failed_channels:
        print(f"Failed channels: {', '.join(failed_channels)}")

    # Show total count in vector store
    from app.rag.store import VectorStore
    store = VectorStore()
    print(f"\nTotal documents in vector store: {store.count()}")


if __name__ == "__main__":
    main()
