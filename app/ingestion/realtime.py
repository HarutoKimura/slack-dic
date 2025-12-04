"""Real-time indexing for Slack messages."""

import logging
from typing import Any

from slack_sdk import WebClient

from app.ingestion.chunk import chunk_documents
from app.ingestion.slack_fetch import get_channel_name
from app.rag.store import VectorStore
from app.utils.slack_links import get_permalink

logger = logging.getLogger(__name__)


def normalize_slack_message(
    client: WebClient, message: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Normalize a raw Slack event message into a document format.

    Args:
        client: Slack WebClient instance
        message: Raw Slack message event dict

    Returns:
        Normalized document dict or None if message should be skipped
        Document structure:
        {
            "id": "channel-ts",
            "channel": "C123...",
            "text": "message text",
            "user": "U123...",
            "ts": "1234567890.123456",
            "thread_ts": "1234567890.123456" (optional),
            "permalink": "https://..."
        }
    """
    # Skip bot messages
    if message.get("bot_id") or message.get("subtype") == "bot_message":
        logger.debug("Skipping bot message")
        return None

    # Skip messages without text
    text = message.get("text", "").strip()
    if not text:
        logger.debug("Skipping message without text")
        return None

    # Extract required fields
    channel = message.get("channel")
    ts = message.get("ts")
    user = message.get("user", "unknown")

    if not channel or not ts:
        logger.warning("Message missing channel or ts: %s", message)
        return None

    # Get permalink and channel name
    permalink = get_permalink(client, channel, ts)
    channel_name = get_channel_name(client, channel)

    # Build document
    doc = {
        "id": f"{channel}-{ts}",
        "channel": channel,
        "channel_name": channel_name,
        "text": text,
        "user": user,
        "ts": ts,
        "permalink": permalink or "",
    }

    # Include thread_ts if present
    if "thread_ts" in message:
        doc["thread_ts"] = message["thread_ts"]

    return doc


def index_slack_messages(
    client: WebClient,
    messages: list[dict[str, Any]],
    chunk_size: int = 600,
    overlap: int = 100,
) -> int:
    """
    Index a list of raw Slack messages into the vector store.

    This function:
    1. Normalizes raw Slack event messages into document format
    2. Chunks the documents
    3. Embeds the chunks (handled by VectorStore)
    4. Upserts to Chroma (idempotent by document ID)

    Args:
        client: Slack WebClient instance
        messages: List of raw Slack message event dicts
        chunk_size: Target chunk size (400-800 chars recommended)
        overlap: Overlap between chunks (80-120 chars recommended)

    Returns:
        Number of chunks indexed
    """
    if not messages:
        return 0

    # Normalize messages
    docs = []
    for msg in messages:
        doc = normalize_slack_message(client, msg)
        if doc:
            docs.append(doc)

    if not docs:
        logger.info("No messages to index after normalization")
        return 0

    logger.info("Normalized %d messages for indexing", len(docs))

    # Chunk documents
    chunks = chunk_documents(docs, chunk_size=chunk_size, overlap=overlap)

    if not chunks:
        logger.warning("No chunks created from %d documents", len(docs))
        return 0

    logger.info("Created %d chunks from %d messages", len(chunks), len(docs))

    # Upsert to vector store (embeddings generated automatically if needed)
    store = VectorStore()
    store.upsert(chunks)

    logger.info("Successfully indexed %d chunks from %d messages", len(chunks), len(docs))
    return len(chunks)


def index_slack_message(
    client: WebClient,
    message: dict[str, Any],
    chunk_size: int = 600,
    overlap: int = 100,
) -> int:
    """
    Index a single raw Slack message into the vector store.

    This is a convenience wrapper around index_slack_messages().

    Args:
        client: Slack WebClient instance
        message: Raw Slack message event dict
        chunk_size: Target chunk size (400-800 chars recommended)
        overlap: Overlap between chunks (80-120 chars recommended)

    Returns:
        Number of chunks indexed
    """
    return index_slack_messages(client, [message], chunk_size, overlap)


def index_documents(
    docs: list[dict[str, Any]],
    chunk_size: int = 600,
    overlap: int = 100,
) -> int:
    """
    Index already-normalized document dicts into the vector store.

    This function can be used by batch ingestion scripts that already have
    normalized documents (e.g., from fetch_channel_messages).

    Args:
        docs: List of normalized document dicts with structure:
            {
                "id": "channel-ts",
                "channel": "C123...",
                "text": "message text",
                "user": "U123...",
                "ts": "1234567890.123456",
                "permalink": "https://..."
            }
        chunk_size: Target chunk size (400-800 chars recommended)
        overlap: Overlap between chunks (80-120 chars recommended)

    Returns:
        Number of chunks indexed
    """
    if not docs:
        return 0

    # Chunk documents
    chunks = chunk_documents(docs, chunk_size=chunk_size, overlap=overlap)

    if not chunks:
        logger.warning("No chunks created from %d documents", len(docs))
        return 0

    logger.info("Created %d chunks from %d documents", len(chunks), len(docs))

    # Upsert to vector store
    store = VectorStore()
    store.upsert(chunks)

    logger.info("Successfully indexed %d chunks from %d documents", len(chunks), len(docs))
    return len(chunks)
