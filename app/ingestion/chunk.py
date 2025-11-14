"""Text chunking utilities for splitting Slack messages."""

from typing import Any


def chunk_text(
    text: str, chunk_size: int = 600, overlap: int = 100
) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: Text to split
        chunk_size: Target chunk size (400-800 chars recommended)
        overlap: Overlap between chunks (80-120 chars recommended)

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # If this is not the last chunk, try to break at a sentence or word boundary
        if end < len(text):
            # Look for sentence boundaries
            for sep in [".", "!", "?", "\n"]:
                last_sep = text.rfind(sep, start, end)
                if last_sep != -1:
                    end = last_sep + 1
                    break
            else:
                # Fall back to word boundary
                last_space = text.rfind(" ", start, end)
                if last_space != -1:
                    end = last_space

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move start forward, accounting for overlap
        start = end - overlap if end < len(text) else end

    return chunks


def chunk_documents(
    docs: list[dict[str, Any]], chunk_size: int = 600, overlap: int = 100
) -> list[dict[str, Any]]:
    """
    Chunk a list of document dictionaries.

    Args:
        docs: List of documents with 'text' field
        chunk_size: Target chunk size (400-800 chars recommended)
        overlap: Overlap between chunks (80-120 chars recommended)

    Returns:
        List of chunked documents with structure:
        {
            "id": "original-id-chunk-0",
            "text": "chunk text",
            "metadata": {
                "channel": "...",
                "user": "...",
                "ts": "...",
                "permalink": "...",
                "chunk_index": 0
            }
        }
    """
    chunked_docs = []

    for doc in docs:
        text = doc.get("text", "")
        if not text:
            continue

        chunks = chunk_text(text, chunk_size, overlap)

        for i, chunk in enumerate(chunks):
            chunked_doc = {
                "id": f"{doc['id']}-chunk-{i}",
                "text": chunk,
                "metadata": {
                    "channel": doc.get("channel", ""),
                    "user": doc.get("user", ""),
                    "ts": doc.get("ts", ""),
                    "permalink": doc.get("permalink", ""),
                    "chunk_index": i,
                },
            }
            chunked_docs.append(chunked_doc)

    print(f"Chunked {len(docs)} documents into {len(chunked_docs)} chunks")
    return chunked_docs
