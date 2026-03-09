"""
RAG answer generation.

Combines vector search with LLM generation to answer questions
based on indexed Slack message history.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from ..bedrock import BedrockEmbeddings, BedrockLLM
from ..database import MessageRepository, SearchResult
from .search import search

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_TOP_K = 25
DEFAULT_MIN_SIMILARITY = 0.25
MAX_DISPLAY_SOURCES = 5
NO_RESULTS_MESSAGE = "情報が見つかりません"
LOW_CONFIDENCE_MESSAGE = (
    "関連する情報が見つかりましたが、確信度が低いため回答できません。"
    "質問を具体的にしていただくか、別の表現でお試しください。"
)
QUERY_EXPANSION_KEYWORD_LIMIT = 8
MAX_EXPANDED_SEARCH_QUERIES = 4
SMALL_TALK_PATTERNS = [
    "こんにちは",
    "こんばんは",
    "おはよう",
    "ありがとう",
    "お疲れ",
    "元気",
    "よろしく",
    "ただいま",
    "おやすみ",
    "はじめまして",
]
CITED_SOURCE_PATTERN = re.compile(r"\[?\s*source\s*(\d+)\s*\]?", re.IGNORECASE)
BRACKET_ONLY_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def _format_post_date(message_ts: Optional[str]) -> str:
    """Convert Slack message_ts to a readable UTC datetime string."""
    if not message_ts:
        return "Unknown"

    timestamp_text = str(message_ts).strip()
    if not timestamp_text:
        return "Unknown"

    try:
        unix_ts = float(timestamp_text)
        # Handle millisecond timestamps defensively.
        if unix_ts > 10_000_000_000:
            unix_ts /= 1000
        if unix_ts < 0:
            return "Unknown"
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "Unknown"


def is_small_talk(question: str) -> bool:
    """Return True when question is likely greeting/chit-chat."""
    normalized_question = question.strip().lower()
    if not normalized_question or len(normalized_question) > 40:
        return False
    has_ja_pattern = any(pattern in normalized_question for pattern in SMALL_TALK_PATTERNS)
    has_en_pattern = bool(
        re.search(r"\b(?:hello|hi|hey|thanks|thank you)\b", normalized_question)
    )
    return has_ja_pattern or has_en_pattern


def _parse_expansion_keywords(raw_text: str) -> list[str]:
    """Parse a JSON array of keywords from LLM output."""
    payload = raw_text.strip()
    if not payload:
        return []

    if not payload.startswith("["):
        match = re.search(r"\[[\s\S]*\]", payload)
        if match:
            payload = match.group(0)

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Failed to parse query expansion output: %s", raw_text[:120])
        return []

    if not isinstance(parsed, list):
        return []

    keywords: list[str] = []
    seen_keywords: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        keyword = " ".join(item.split()).strip()
        if not keyword:
            continue
        keyword_key = keyword.lower()
        if keyword_key in seen_keywords:
            continue
        seen_keywords.add(keyword_key)
        keywords.append(keyword)
        if len(keywords) >= QUERY_EXPANSION_KEYWORD_LIMIT:
            break

    return keywords


def _expand_search_queries(question: str, llm: BedrockLLM) -> list[str]:
    """Generate expanded retrieval queries from the user question."""
    system = (
        "You create retrieval query expansion keywords for Slack semantic search. "
        "Return ONLY a JSON array of short related keywords or phrases. "
        "Do not include explanation or markdown."
    )
    prompt = f"""User question:
{question}

Generate 4 to 8 related search keywords/short phrases that improve retrieval recall.
Include paraphrases and synonyms likely used in Slack posts.
Return only JSON array text, for example:
["keyword1", "keyword2", "keyword3"]"""

    try:
        raw_keywords = llm.generate(
            prompt=prompt,
            system=system,
            max_tokens=200,
            temperature=0.1,
        )
    except Exception as exc:
        logger.warning("Query expansion failed. Fallback to original query only: %s", exc)
        return [question]

    keywords = _parse_expansion_keywords(raw_keywords)

    candidate_queries = [question]
    if keywords:
        candidate_queries.append(f"{question} {' '.join(keywords)}")
        question_lower = question.lower()
        for keyword in keywords:
            if keyword.lower() in question_lower:
                continue
            candidate_queries.append(keyword)
            if len(candidate_queries) >= MAX_EXPANDED_SEARCH_QUERIES:
                break
        logger.info("Generated query expansion keywords: %s", ", ".join(keywords))
    else:
        logger.info("No query expansion keywords generated")

    queries: list[str] = []
    seen_queries: set[str] = set()
    for query in candidate_queries:
        normalized_query = " ".join(query.split()).strip()
        if not normalized_query:
            continue
        query_key = normalized_query.lower()
        if query_key in seen_queries:
            continue
        seen_queries.add(query_key)
        queries.append(normalized_query)
        if len(queries) >= MAX_EXPANDED_SEARCH_QUERIES:
            break

    return queries or [question]


def _dedup_key(result: SearchResult) -> str:
    """Build a stable key for merging search results across multiple queries."""
    if result.id:
        return f"id:{result.id}"
    if result.permalink:
        return f"permalink:{result.permalink}"
    return f"ts:{result.message_ts or ''}|text:{result.text}"


def _merge_search_results(
    result_sets: list[list[SearchResult]],
    top_k: int,
) -> list[SearchResult]:
    """Merge and deduplicate search results, keeping highest similarity first."""
    best_by_key: dict[str, SearchResult] = {}

    for result_set in result_sets:
        for result in result_set:
            key = _dedup_key(result)
            existing = best_by_key.get(key)
            if existing is None or result.similarity > existing.similarity:
                best_by_key[key] = result

    merged = sorted(
        best_by_key.values(),
        key=lambda item: item.similarity,
        reverse=True,
    )
    return merged[:top_k]


def _map_citation_to_result_index(
    citation_number: int, total_results: int
) -> Optional[int]:
    """
    Map a citation number in the answer to a context_results index.

    We prefer 1-based mapping because prompts enumerate context as [Source 1], [Source 2], ...
    If a 0-based number is emitted (e.g., [0]), we still support it.
    """
    if total_results <= 0:
        return None

    if 1 <= citation_number <= total_results:
        return citation_number - 1

    if 0 <= citation_number < total_results:
        return citation_number

    return None


def _extract_cited_result_indices(answer: str, total_results: int) -> list[int]:
    """Extract cited result indices from answer text, preserving mention order."""
    cited_indices: list[int] = []
    seen_indices: set[int] = set()

    def add_citation(citation_number: int) -> None:
        mapped_index = _map_citation_to_result_index(
            citation_number=citation_number,
            total_results=total_results,
        )
        if mapped_index is None or mapped_index in seen_indices:
            return
        seen_indices.add(mapped_index)
        cited_indices.append(mapped_index)

    for match in CITED_SOURCE_PATTERN.finditer(answer):
        add_citation(int(match.group(1)))

    for match in BRACKET_ONLY_CITATION_PATTERN.finditer(answer):
        add_citation(int(match.group(1)))

    return cited_indices


def _build_source_links(answer: str, context_results: list[SearchResult]) -> list[str]:
    """
    Build source links with cited documents first, then top-ranked remaining docs.
    """
    source_links: list[str] = []
    seen_links: set[str] = set()

    for result_index in _extract_cited_result_indices(
        answer=answer, total_results=len(context_results)
    ):
        permalink = context_results[result_index].permalink
        if not permalink or permalink in seen_links:
            continue
        seen_links.add(permalink)
        source_links.append(permalink)
        if len(source_links) >= MAX_DISPLAY_SOURCES:
            return source_links

    for result in context_results:
        permalink = result.permalink
        if not permalink or permalink in seen_links:
            continue
        seen_links.add(permalink)
        source_links.append(permalink)
        if len(source_links) >= MAX_DISPLAY_SOURCES:
            break

    return source_links


def generate_answer(
    question: str,
    context_results: list[SearchResult],
    llm: Optional[BedrockLLM] = None,
    include_sources: bool = True,
    current_time: str = "2026-02-12",
) -> str:
    """
    Generate an answer from search results using LLM.

    Args:
        question: User's question
        context_results: Search results to use as context
        llm: LLM client (created if not provided)
        include_sources: Whether to append source links
        current_time: Current date/time reference included in system prompt

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
            "message_ts": result.message_ts,
            "post_date": _format_post_date(result.message_ts),
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
        current_time=current_time,
    )

    # Append sources if requested
    if include_sources:
        sources = _build_source_links(answer=answer, context_results=context_results)

        if sources:
            answer += "\n\n📚 ソース:\n" + "\n".join(f"• {s}" for s in sources)

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
    current_time: str = "2026-02-12",
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
        current_time: Current date/time reference included in system prompt

    Returns:
        Tuple of (answer_text, search_results)
    """
    if not question or not question.strip():
        return ("質問を入力してください。", [])

    logger.info(f"Processing question: {question[:100]}...")

    # Skip retrieval for greetings/chit-chat and let the LLM answer naturally.
    if is_small_talk(question):
        logger.info("Detected greeting/small talk, skipping vector search")
        if llm is None:
            region = os.environ.get("AWS_REGION", "us-east-1")
            llm = BedrockLLM(region_name=region)
        return (
            llm.generate_answer(
                question=question,
                context_chunks=[],
                language="Japanese",
            ),
            [],
        )

    if llm is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        llm = BedrockLLM(region_name=region)

    if embeddings is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        embeddings = BedrockEmbeddings(region_name=region)

    if repository is None:
        repository = MessageRepository()

    # Dynamically expand the user question to reduce retrieval misses.
    search_queries = _expand_search_queries(question=question, llm=llm)
    result_sets: list[list[SearchResult]] = []

    for search_query in search_queries:
        query_results = search(
            query=search_query,
            repository=repository,
            embeddings=embeddings,
            top_k=top_k,
            min_similarity=min_similarity,
            channel_filter=channel_filter,
        )
        if query_results:
            result_sets.append(query_results)

    results = _merge_search_results(result_sets=result_sets, top_k=top_k)
    logger.info(
        "Retrieved %d unique chunks from %d queries",
        len(results),
        len(search_queries),
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
        current_time=current_time,
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
