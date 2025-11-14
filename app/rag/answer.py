"""LLM-based question answering with RAG."""

from typing import Any

from openai import OpenAI

from app.rag.search import search
from app.settings import settings


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
        self, question: str, context_docs: list[dict[str, Any]]
    ) -> str:
        """
        Generate an answer based on question and context documents.

        Args:
            question: User question
            context_docs: List of context documents from vector search

        Returns:
            Generated answer with sources
        """
        # Build context from documents
        context_parts = []
        sources = set()

        for i, doc in enumerate(context_docs, 1):
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})
            permalink = metadata.get("permalink", "")

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


def ask(question: str, top_k: int = 5) -> str:
    """
    Ask a question using RAG.

    Args:
        question: User question
        top_k: Number of context documents to retrieve

    Returns:
        Generated answer with sources
    """
    # Search for relevant documents
    results = search(question, top_k=top_k)

    if not results:
        return "I couldn't find any relevant information in the channel history."

    # Generate answer
    generator = AnswerGenerator()
    answer = generator.generate_answer(question, results)

    return answer
