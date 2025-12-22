"""
RAG answer generation.

Combines vector search with LLM generation to answer questions
based on indexed Slack message history.
"""

import logging
import os
from typing import Optional

from ..bedrock import BedrockEmbeddings, BedrockLLM
from ..database import MessageRepository, SearchResult
from .search import search

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_TOP_K = 5
DEFAULT_MIN_SIMILARITY = 0.25
NO_RESULTS_MESSAGE = "関連する情報が見つかりませんでした。"
LOW_CONFIDENCE_MESSAGE = (
    "関連する情報が見つかりましたが、確信度が低いため回答できません。"
    "質問を具体的にしていただくか、別の表現でお試しください。"
)


def generate_answer(
    question: str,
    context_results: list[SearchResult],
    llm: Optional[BedrockLLM] = None,
    include_sources: bool = True,
) -> str:
    """
    Generate an answer from search results using LLM.

    Args:
        question: User's question
        context_results: Search results to use as context
        llm: LLM client (created if not provided)
        include_sources: Whether to append source links

    Returns:
        Generated answer text with optional source links
    """
    if not context_results:
        return NO_RESULTS_MESSAGE

    # Initialize LLM if not provided
    if llm is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        llm = BedrockLLM(region_name=region)

    # Convert SearchResult to context dict format
    context_chunks = [
        {
            "text": result.text,
            "channel_name": result.channel_name,
            "user_name": result.user_name,
            "permalink": result.permalink,
        }
        for result in context_results
    ]

    # Generate answer
    answer = llm.generate_answer(
        question=question,
        context_chunks=context_chunks,
        language="Japanese",
    )

    # Append sources if requested
    if include_sources:
        sources = set()
        for result in context_results:
            if result.permalink:
                sources.add(result.permalink)

        if sources:
            answer += "\n\n📚 ソース:\n" + "\n".join(f"• {s}" for s in sorted(sources))

    return answer


def ask(
    question: str,
    repository: Optional[MessageRepository] = None,
    embeddings: Optional[BedrockEmbeddings] = None,
    llm: Optional[BedrockLLM] = None,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    channel_filter: Optional[str] = None,
    include_sources: bool = True,
    low_confidence_threshold: float = 0.35,
) -> tuple[str, list[SearchResult]]:
    """
    Complete RAG pipeline: search and generate answer.

    Args:
        question: User's question
        repository: Message repository
        embeddings: Embeddings client
        llm: LLM client
        top_k: Maximum number of context chunks
        min_similarity: Minimum similarity for search
        channel_filter: Optional channel ID filter
        include_sources: Whether to include source links
        low_confidence_threshold: Min avg similarity for confident answer

    Returns:
        Tuple of (answer_text, search_results)
    """
    if not question or not question.strip():
        return ("質問を入力してください。", [])

    logger.info(f"Processing question: {question[:100]}...")

    # Search for relevant chunks
    results = search(
        query=question,
        repository=repository,
        embeddings=embeddings,
        top_k=top_k,
        min_similarity=min_similarity,
        channel_filter=channel_filter,
    )

    if not results:
        logger.info("No search results found")
        return (NO_RESULTS_MESSAGE, [])

    # Check confidence level
    avg_similarity = sum(r.similarity for r in results) / len(results)
    max_similarity = max(r.similarity for r in results)

    logger.info(
        f"Search results: {len(results)} chunks, "
        f"avg similarity: {avg_similarity:.3f}, "
        f"max similarity: {max_similarity:.3f}"
    )

    # If confidence is too low, warn the user
    if max_similarity < low_confidence_threshold and avg_similarity < min_similarity + 0.1:
        logger.warning("Low confidence results")
        return (LOW_CONFIDENCE_MESSAGE, results)

    # Generate answer
    answer = generate_answer(
        question=question,
        context_results=results,
        llm=llm,
        include_sources=include_sources,
    )

    return (answer, results)


def ask_simple(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> str:
    """
    Simple interface for asking questions.

    Creates all clients internally. Use this for Lambda handlers.

    Args:
        question: User's question
        top_k: Maximum number of context chunks
        min_similarity: Minimum similarity threshold

    Returns:
        Answer text
    """
    answer, _ = ask(
        question=question,
        top_k=top_k,
        min_similarity=min_similarity,
    )
    return answer
