"""
Vector similarity search for RAG.

Searches Aurora PostgreSQL with pgvector for similar message chunks.
"""

import logging
import os
from typing import Optional

from ..bedrock import BedrockEmbeddings
from ..database import MessageRepository, SearchResult

logger = logging.getLogger(__name__)


def search(
    query: str,
    repository: Optional[MessageRepository] = None,
    embeddings: Optional[BedrockEmbeddings] = None,
    top_k: int = 5,
    min_similarity: float = 0.25,
    channel_filter: Optional[str] = None,
) -> list[SearchResult]:
    """
    Search for similar message chunks.

    Args:
        query: Search query text
        repository: Message repository (created if not provided)
        embeddings: Embeddings client (created if not provided)
        top_k: Maximum number of results
        min_similarity: Minimum similarity threshold (0-1)
        channel_filter: Optional channel ID to filter results

    Returns:
        List of SearchResult sorted by similarity (descending)
    """
    if not query or not query.strip():
        logger.warning("Empty search query")
        return []

    # Initialize clients if not provided
    if embeddings is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        embeddings = BedrockEmbeddings(region_name=region)

    if repository is None:
        repository = MessageRepository()

    # Embed the query
    logger.debug(f"Embedding query: {query[:50]}...")
    query_embedding = embeddings.embed(query)

    # Search for similar chunks
    results = repository.search_similar(
        embedding=query_embedding,
        top_k=top_k,
        min_similarity=min_similarity,
        channel_filter=channel_filter,
    )

    logger.info(f"Found {len(results)} results for query: {query[:50]}...")
    return results


def format_search_results(results: list[SearchResult]) -> str:
    """
    Format search results for display.

    Args:
        results: List of SearchResult

    Returns:
        Formatted string with results
    """
    if not results:
        return "検索結果が見つかりませんでした。"

    lines = []
    for i, result in enumerate(results, 1):
        similarity_pct = result.similarity * 100
        source = result.source_info

        lines.append(f"**[{i}]** (類似度: {similarity_pct:.1f}%)")
        lines.append(f"ソース: {source}")
        lines.append(f"```\n{result.text[:300]}{'...' if len(result.text) > 300 else ''}\n```")
        if result.permalink:
            lines.append(f"リンク: {result.permalink}")
        lines.append("")

    return "\n".join(lines)
