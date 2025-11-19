"""Bulk ingestion script for Slack messages."""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from slack_sdk import WebClient

from app.ingestion.realtime import index_documents
from app.ingestion.slack_fetch import fetch_channel_messages, get_channel_id
from app.settings import settings


def main():
    """Main ingestion script."""
    parser = argparse.ArgumentParser(description="Index Slack messages into vector store")
    parser.add_argument(
        "--channel",
        type=str,
        required=True,
        help="Channel name (e.g., '#all-slack-rag-test' or 'general')",
    )
    parser.add_argument(
        "--limit", type=int, default=2000, help="Maximum number of messages to fetch"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=600, help="Text chunk size (400-800 recommended)"
    )
    parser.add_argument(
        "--chunk-overlap", type=int, default=100, help="Chunk overlap (80-120 recommended)"
    )

    args = parser.parse_args()

    # Initialize Slack client
    print("Initializing Slack client...")
    client = WebClient(token=settings.slack_bot_token)

    # Get channel ID
    print(f"Looking up channel: {args.channel}")
    channel_id = get_channel_id(client, args.channel)

    if not channel_id:
        print(f"Error: Channel '{args.channel}' not found")
        return

    print(f"Found channel ID: {channel_id}")

    # Fetch messages
    print(f"Fetching up to {args.limit} messages...")
    messages = fetch_channel_messages(client, channel_id, limit=args.limit)

    if not messages:
        print("No messages fetched. Exiting.")
        return

    print(f"Fetched {len(messages)} messages")

    # Index documents (chunk, embed, store)
    print("Indexing documents (chunking, embedding, storing)...")
    num_chunks = index_documents(
        messages, chunk_size=args.chunk_size, overlap=args.chunk_overlap
    )

    if not num_chunks:
        print("No chunks created. Exiting.")
        return

    print(f"\n✅ Successfully indexed {num_chunks} chunks from {len(messages)} messages")

    # Show total count
    from app.rag.store import VectorStore
    store = VectorStore()
    print(f"Total documents in vector store: {store.count()}")


if __name__ == "__main__":
    main()
