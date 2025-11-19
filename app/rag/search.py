"""Vector search functionality."""

import logging
from dataclasses import dataclass

from app.rag.store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A retrieved chunk with text, metadata, and similarity score."""

    text: str
    metadata: dict
    score: float  # Similarity score in [0, 1], higher = more similar


def search(query: str, top_k: int = 5) -> list[RetrievedChunk]:
    """
    Search for relevant documents in the vector store.

    Args:
        query: Search query
        top_k: Number of results to return

    Returns:
        List of RetrievedChunk objects with similarity scores
    """
    store = VectorStore()
    results = store.query(query, top_k=top_k)

    chunks = []
    for result in results:
        # Convert distance to similarity (for cosine distance: similarity = 1 - distance)
        distance = result.get("distance", 0.0)
        similarity = 1.0 - distance

        chunk = RetrievedChunk(
            text=result.get("text", ""),
            metadata=result.get("metadata", {}),
            score=similarity,
        )
        chunks.append(chunk)

        # Debug logging for scores
        permalink = chunk.metadata.get("permalink", "N/A")
        logger.debug(
            "Retrieved chunk: score=%.4f, permalink=%s",
            chunk.score,
            permalink
        )

    return chunks


def format_search_results(results: list[RetrievedChunk]) -> str:
    """
    Format search results for display.

    Args:
        results: List of RetrievedChunk objects

    Returns:
        Formatted string of results
    """
    if not results:
        return "No results found."

    output = []
    for i, chunk in enumerate(results, 1):
        permalink = chunk.metadata.get("permalink", "")
        text = chunk.text[:200] + "..."  # Truncate for display

        output.append(f"{i}. {text}")
        if permalink:
            output.append(f"   Source: {permalink}")
        output.append(f"   Similarity: {chunk.score:.4f}")
        output.append("")

    return "\n".join(output)
