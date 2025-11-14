"""OpenAI embeddings with rate limit handling."""

import time
from typing import Any

from openai import OpenAI, RateLimitError

from app.settings import settings


class EmbeddingClient:
    """Client for generating embeddings with OpenAI."""

    def __init__(self, model: str | None = None):
        """
        Initialize the embedding client.

        Args:
            model: OpenAI embedding model to use
        """
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.embedding_model

    def embed_texts(
        self, texts: list[str], max_retries: int = 3, retry_delay: int = 2
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of texts with rate limit retry.

        Args:
            texts: List of texts to embed
            max_retries: Maximum number of retries on rate limit
            retry_delay: Delay between retries in seconds

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(input=texts, model=self.model)
                embeddings = [item.embedding for item in response.data]
                return embeddings

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2**attempt)  # Exponential backoff
                    print(f"Rate limit hit. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    raise e

            except Exception as e:
                print(f"Error generating embeddings: {e}")
                raise e

        return []

    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = self.embed_texts([text])
        return embeddings[0] if embeddings else []


def embed_documents(
    docs: list[dict[str, Any]], batch_size: int = 100
) -> list[dict[str, Any]]:
    """
    Add embeddings to a list of documents.

    Args:
        docs: List of documents with 'text' field
        batch_size: Number of documents to embed in each batch

    Returns:
        List of documents with 'embedding' field added
    """
    client = EmbeddingClient()
    embedded_docs = []

    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        texts = [doc["text"] for doc in batch]

        print(f"Embedding batch {i // batch_size + 1}/{(len(docs) - 1) // batch_size + 1}...")
        embeddings = client.embed_texts(texts)

        for doc, embedding in zip(batch, embeddings):
            doc["embedding"] = embedding
            embedded_docs.append(doc)

    print(f"Embedded {len(embedded_docs)} documents")
    return embedded_docs
