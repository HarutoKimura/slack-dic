"""Vector search functionality."""

from typing import Any

from app.rag.store import VectorStore


def search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """
    Search for relevant documents in the vector store.

    Args:
        query: Search query
        top_k: Number of results to return

    Returns:
        List of search results with structure:
            {
                "id": "doc-id",
                "text": "document text",
                "metadata": {...},
                "distance": 0.123
            }
    """
    store = VectorStore()
    results = store.query(query, top_k=top_k)
    return results


def format_search_results(results: list[dict[str, Any]]) -> str:
    """
    Format search results for display.

    Args:
        results: List of search results

    Returns:
        Formatted string of results
    """
    if not results:
        return "No results found."

    output = []
    for i, result in enumerate(results, 1):
        metadata = result.get("metadata", {})
        permalink = metadata.get("permalink", "")
        text = result.get("text", "")[:200] + "..."  # Truncate for display

        output.append(f"{i}. {text}")
        if permalink:
            output.append(f"   Source: {permalink}")
        output.append(f"   Distance: {result.get('distance', 0.0):.4f}")
        output.append("")

    return "\n".join(output)
