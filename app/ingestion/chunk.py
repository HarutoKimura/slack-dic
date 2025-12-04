"""Text chunking utilities for splitting Slack messages."""

import re
from typing import Any

import tiktoken


# Compile regex patterns for protected content
URL_PATTERN = re.compile(
    r'https?://[^\s<>\[\]()]+|'  # Standard URLs
    r'<https?://[^>|]+(?:\|[^>]+)?>'  # Slack-formatted URLs like <url|text>
)
CODE_BLOCK_PATTERN = re.compile(r'```[\s\S]*?```')  # Fenced code blocks
INLINE_CODE_PATTERN = re.compile(r'`[^`\n]+`')  # Inline code
LIST_ITEM_PATTERN = re.compile(r'^[\s]*[-*•]\s+.+$', re.MULTILINE)  # List items


def _get_tokenizer():
    """Get tiktoken tokenizer for consistent token counting."""
    try:
        return tiktoken.encoding_for_model("gpt-4")
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str, tokenizer=None) -> int:
    """Count tokens in text using tiktoken."""
    if tokenizer is None:
        tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text))


def _find_protected_ranges(text: str) -> list[tuple[int, int]]:
    """
    Find character ranges that should not be split (URLs, code blocks, list items).

    Returns:
        List of (start, end) tuples representing protected ranges
    """
    protected = []

    # Find code blocks first (highest priority - they may contain URLs)
    for match in CODE_BLOCK_PATTERN.finditer(text):
        protected.append((match.start(), match.end()))

    # Find inline code
    for match in INLINE_CODE_PATTERN.finditer(text):
        protected.append((match.start(), match.end()))

    # Find URLs
    for match in URL_PATTERN.finditer(text):
        protected.append((match.start(), match.end()))

    # Find list items
    for match in LIST_ITEM_PATTERN.finditer(text):
        protected.append((match.start(), match.end()))

    # Merge overlapping ranges
    if not protected:
        return []

    protected.sort(key=lambda x: x[0])
    merged = [protected[0]]

    for start, end in protected[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            # Overlapping, merge
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def _get_protected_range_at(position: int, protected_ranges: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Get the protected range that contains the given position, if any."""
    for start, end in protected_ranges:
        if start <= position < end:
            return (start, end)
        if start > position:
            break
    return None


def _find_break_point(
    text: str,
    start: int,
    max_end: int,
    protected_ranges: list[tuple[int, int]]
) -> int:
    """
    Find the best break point for a chunk, never breaking inside protected content.

    Args:
        text: The full text
        start: Start of current chunk
        max_end: Maximum end position (chunk_size from start)
        protected_ranges: List of protected (start, end) ranges

    Returns:
        Best end position for the chunk
    """
    if max_end >= len(text):
        return len(text)

    # Check if max_end is inside a protected range
    protected = _get_protected_range_at(max_end, protected_ranges)
    if protected:
        # We're inside protected content - we must break before it starts
        # Find a break point before the protected range
        max_end = protected[0]
        if max_end <= start:
            # Protected content starts at or before our chunk start
            # We must include the entire protected content
            return protected[1]

    # Search backward from max_end to find a good break point
    # Search in the last 50% of the chunk for flexibility
    search_start = start + int((max_end - start) * 0.5)

    best_break = None
    best_priority = 100  # Lower is better

    for i in range(max_end, search_start, -1):
        # Skip if inside protected range
        if _get_protected_range_at(i, protected_ranges):
            continue

        # Check for different break types
        priority = None
        break_pos = None

        # Priority 1: Paragraph boundary
        if i < len(text) - 1 and text[i:i+2] == '\n\n':
            priority = 1
            break_pos = i + 2
        # Priority 2: Sentence end followed by space or newline
        elif i > 0 and text[i-1] in '.!?' and text[i] in ' \n':
            priority = 2
            break_pos = i + 1
        # Priority 3: Newline
        elif text[i] == '\n':
            priority = 3
            break_pos = i + 1
        # Priority 4: Space (word boundary)
        elif text[i] == ' ':
            priority = 4
            break_pos = i + 1

        if priority is not None and break_pos is not None:
            # Make sure break_pos is not inside protected content
            if not _get_protected_range_at(break_pos - 1, protected_ranges):
                if priority < best_priority:
                    best_priority = priority
                    best_break = break_pos
                    # If we found paragraph or sentence break, use it
                    if priority <= 2:
                        break

    if best_break is not None:
        return best_break

    # Fallback: find any space before max_end
    for i in range(max_end, start, -1):
        if text[i] == ' ' and not _get_protected_range_at(i, protected_ranges):
            return i + 1

    # Last resort: if we still can't find a break, use max_end
    # but make sure we're not in protected content
    if _get_protected_range_at(max_end - 1, protected_ranges):
        # Find the end of this protected range
        for range_start, range_end in protected_ranges:
            if range_start <= max_end - 1 < range_end:
                return range_end

    return max_end


def _merge_small_chunks(chunks: list[str], min_chunk_size: int, max_chunk_size: int) -> list[str]:
    """
    Merge chunks that are smaller than min_chunk_size with adjacent chunks.

    Args:
        chunks: List of text chunks
        min_chunk_size: Minimum acceptable chunk size
        max_chunk_size: Maximum chunk size after merging (can exceed by 50% for small chunks)

    Returns:
        List of merged chunks
    """
    if not chunks or len(chunks) <= 1:
        return chunks

    # Allow exceeding max_chunk_size by 50% when merging small chunks
    merge_limit = int(max_chunk_size * 1.5)

    merged = []
    current = chunks[0]

    for i in range(1, len(chunks)):
        next_chunk = chunks[i]

        # If current chunk is small, try to merge
        if len(current) < min_chunk_size:
            if len(current) + len(next_chunk) + 1 <= merge_limit:
                current = current + " " + next_chunk
            else:
                merged.append(current)
                current = next_chunk
        # If next chunk is small, try to merge
        elif len(next_chunk) < min_chunk_size:
            if len(current) + len(next_chunk) + 1 <= merge_limit:
                current = current + " " + next_chunk
            else:
                merged.append(current)
                current = next_chunk
        else:
            merged.append(current)
            current = next_chunk

    # Don't forget the last chunk
    if current:
        merged.append(current)

    # Second pass: try to merge any remaining small chunks at the end
    if len(merged) > 1 and len(merged[-1]) < min_chunk_size:
        if len(merged[-2]) + len(merged[-1]) + 1 <= merge_limit:
            merged[-2] = merged[-2] + " " + merged[-1]
            merged.pop()

    # Third pass: merge small chunks at the beginning
    if len(merged) > 1 and len(merged[0]) < min_chunk_size:
        if len(merged[0]) + len(merged[1]) + 1 <= merge_limit:
            merged[1] = merged[0] + " " + merged[1]
            merged.pop(0)

    return merged


def chunk_text(
    text: str,
    chunk_size: int = 600,
    overlap: int = 0,
    use_tokens: bool = True,
    min_chunk_size: int = 50
) -> list[str]:
    """
    Split text into chunks with smart boundary detection.

    This improved chunking:
    - Never breaks inside URLs, code blocks, or list items
    - Uses tiktoken for consistent token-based sizing (optional)
    - Respects sentence and paragraph boundaries
    - Never breaks mid-word
    - Merges small chunks with adjacent ones

    Args:
        text: Text to split
        chunk_size: Target chunk size in characters (450-750 recommended)
        overlap: Overlap between chunks in characters (0 = no overlap, default)
        use_tokens: If True, also validates chunk sizes using token count
        min_chunk_size: Minimum chunk size; smaller chunks are merged (default 50)

    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # For short texts, return as-is
    if len(text) <= chunk_size:
        return [text]

    # Find protected ranges
    protected_ranges = _find_protected_ranges(text)

    # Get tokenizer if using token-based validation
    tokenizer = _get_tokenizer() if use_tokens else None

    chunks = []
    start = 0

    while start < len(text):
        # Calculate max end for this chunk
        max_end = min(start + chunk_size, len(text))

        if max_end >= len(text):
            # Last chunk - take everything remaining
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Find break point
        end = _find_break_point(text, start, max_end, protected_ranges)

        # Safety check: ensure we make progress
        if end <= start:
            end = max_end

        chunk = text[start:end].strip()

        if chunk:
            # Token-based validation
            if use_tokens and tokenizer:
                token_count = _count_tokens(chunk, tokenizer)
                max_tokens = int(chunk_size * 0.35)
                if token_count > max_tokens and end - start > 200:
                    reduced_end = _find_break_point(
                        text, start, start + int(chunk_size * 0.7), protected_ranges
                    )
                    if reduced_end > start + 100:
                        reduced_chunk = text[start:reduced_end].strip()
                        if reduced_chunk:
                            chunk = reduced_chunk
                            end = reduced_end

            chunks.append(chunk)

        # Calculate next start position
        if overlap > 0 and end < len(text):
            # Find overlap start point at a word boundary
            overlap_start = end - overlap
            if overlap_start <= start:
                next_start = end
            else:
                # Search forward to find a word boundary for overlap
                next_start = None
                for i in range(overlap_start, end):
                    if text[i] == ' ':
                        next_start = i + 1
                        break
                if next_start is None:
                    next_start = end
        else:
            next_start = end

        # Prevent infinite loop
        if next_start <= start:
            next_start = end
        if next_start <= start:
            break

        start = next_start

    # Merge small chunks with adjacent ones
    if min_chunk_size > 0 and len(chunks) > 1:
        chunks = _merge_small_chunks(chunks, min_chunk_size, chunk_size)

    return chunks


def chunk_documents(
    docs: list[dict[str, Any]],
    chunk_size: int = 600,
    overlap: int = 0,
    use_tokens: bool = True
) -> list[dict[str, Any]]:
    """
    Chunk a list of document dictionaries.

    Args:
        docs: List of documents with 'text' field
        chunk_size: Target chunk size in characters (450-750 recommended)
        overlap: Overlap between chunks in characters (0 = no overlap, default)
        use_tokens: If True, also validates chunk sizes using token count

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

        chunks = chunk_text(text, chunk_size, overlap, use_tokens)

        for i, chunk in enumerate(chunks):
            chunked_doc = {
                "id": f"{doc['id']}-chunk-{i}",
                "text": chunk,
                "metadata": {
                    "channel": doc.get("channel", ""),
                    "channel_name": doc.get("channel_name", ""),
                    "user": doc.get("user", ""),
                    "ts": doc.get("ts", ""),
                    "permalink": doc.get("permalink", ""),
                    "chunk_index": i,
                },
            }
            chunked_docs.append(chunked_doc)

    print(f"Chunked {len(docs)} documents into {len(chunked_docs)} chunks")
    return chunked_docs
