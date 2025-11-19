"""LLM-based question answering with RAG."""

import logging

from openai import OpenAI

from app.rag.search import RetrievedChunk, search
from app.settings import settings

logger = logging.getLogger(__name__)


class AnswerGenerator:
    """Generate answers using RAG with OpenAI."""

    def __init__(self, model: str | None = None):
        """
        Initialize the answer generator.

        Args:
            model: OpenAI model to use for generation
        """
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.llm_model

    def generate_answer(
        self, question: str, context_chunks: list[RetrievedChunk]
    ) -> str:
        """
        Generate an answer based on question and context documents.

        Args:
            question: User question
            context_chunks: List of context chunks from vector search

        Returns:
            Generated answer with sources
        """
        # Build context from documents
        context_parts = []
        sources = set()

        for i, chunk in enumerate(context_chunks, 1):
            text = chunk.text
            permalink = chunk.metadata.get("permalink", "")

            context_parts.append(f"[{i}] {text}")
            if permalink:
                sources.add(permalink)

        context_text = "\n\n".join(context_parts)

        # Build prompt
        prompt = f"""You are a helpful assistant answering questions using only the provided context from Slack messages.

Rules:
- Answer based ONLY on the context below
- If the answer isn't in the context, say "I couldn't find that information in the channel history."
- Be concise and direct
- DO NOT fabricate or make assumptions beyond the provided context

Question:
{question}

Context:
{context_text}"""

        # Generate answer
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=2000,
            )

            answer = response.choices[0].message.content or "No answer generated."

            # Add sources
            if sources:
                sources_text = "\n\nSources:\n" + "\n".join(f"- {url}" for url in sorted(sources))
                answer += sources_text

            return answer

        except Exception as e:
            return f"Error generating answer: {e}"


def ask(question: str, top_k: int = 5, debug: bool = False) -> str:
    """
    Ask a question using RAG.

    Args:
        question: User question
        top_k: Number of context documents to retrieve
        debug: If True, include debug information in output

    Returns:
        Generated answer with sources (or fallback message)
    """
    # Search for relevant documents
    chunks = search(question, top_k=top_k)

    # Case 1: No chunks retrieved at all
    if not chunks:
        message = "I couldn't find any relevant information in the indexed messages for this channel."
        if debug:
            print(f"[DEBUG] No chunks retrieved")
        return message

    # Get top similarity score
    top_score = max(chunk.score for chunk in chunks)

    # Debug output
    if debug:
        print(f"[DEBUG] top similarity: {top_score:.4f} (threshold: {settings.min_similarity})")
        print(f"[DEBUG] All chunk scores:")
        for i, chunk in enumerate(chunks, 1):
            permalink = chunk.metadata.get("permalink", "N/A")
            print(f"  [{i}] score={chunk.score:.4f} - {permalink}")

    # Case 2: Top score is below threshold - return low confidence fallback
    if top_score < settings.min_similarity:
        if debug:
            print(f"[DEBUG] Below threshold ({top_score:.4f} < {settings.min_similarity}) -> using fallback")

        # Build low confidence response with top 3 sources
        low_confidence_chunks = chunks[:3]
        sources = []
        for chunk in low_confidence_chunks:
            permalink = chunk.metadata.get("permalink", "")
            if permalink:
                sources.append(permalink)

        message = "I couldn't find enough relevant information in this channel's indexed messages to answer that confidently."

        if sources:
            message += "\n\nSources (possibly related but low confidence):\n"
            message += "\n".join(f"- {url}" for url in sources)

        return message

    # Case 3: Normal flow - generate answer with LLM
    if debug:
        print(f"[DEBUG] Above threshold ({top_score:.4f} >= {settings.min_similarity}) -> generating answer")

    generator = AnswerGenerator()
    answer = generator.generate_answer(question, chunks)

    return answer
