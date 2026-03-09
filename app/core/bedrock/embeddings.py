"""
Amazon Bedrock Titan Embeddings client.

Uses amazon.titan-embed-text-v1 for generating 1536-dimensional embeddings.
Supports both single text and batch embedding with rate limiting.
"""

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockEmbeddings:
    """Client for Amazon Bedrock Titan Embeddings."""

    MODEL_ID = "amazon.titan-embed-text-v1"
    DIMENSION = 1536
    MAX_INPUT_TOKENS = 8192  # Titan limit

    def __init__(
        self,
        region_name: str = "us-east-1",
        client: Optional[boto3.client] = None,
    ):
        """
        Initialize Bedrock embeddings client.

        Args:
            region_name: AWS region for Bedrock
            client: Optional pre-configured boto3 client (for testing)
        """
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=region_name
        )
        self._region = region_name
        logger.info(f"Initialized Bedrock embeddings client in {region_name}")

    def embed(self, text: str) -> list[float]:
        """
        Embed a single text.

        Args:
            text: Text to embed (max 8192 tokens)

        Returns:
            1536-dimensional embedding vector
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Truncate if too long (rough estimate: 4 chars per token)
        max_chars = self.MAX_INPUT_TOKENS * 4
        if len(text) > max_chars:
            logger.warning(f"Text truncated from {len(text)} to {max_chars} chars")
            text = text[:max_chars]

        try:
            response = self._client.invoke_model(
                modelId=self.MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({"inputText": text}),
            )
            result = json.loads(response["body"].read())
            return result["embedding"]

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ThrottlingException":
                logger.warning("Bedrock rate limit hit, retrying after 1s...")
                time.sleep(1)
                return self.embed(text)
            raise

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 25,
        delay_between_batches: float = 0.1,
    ) -> list[list[float]]:
        """
        Embed multiple texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch
            delay_between_batches: Seconds to wait between batches

        Returns:
            List of embedding vectors (same order as input)
        """
        if not texts:
            return []

        embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_num = i // batch_size + 1

            logger.debug(f"Embedding batch {batch_num}/{total_batches}")

            for text in batch:
                if text and text.strip():
                    embeddings.append(self.embed(text))
                else:
                    # Return zero vector for empty text
                    embeddings.append([0.0] * self.DIMENSION)

            # Rate limiting between batches
            if i + batch_size < len(texts) and delay_between_batches > 0:
                time.sleep(delay_between_batches)

        return embeddings

    def embed_documents(
        self,
        documents: list[dict],
        text_key: str = "text",
        batch_size: int = 25,
    ) -> list[dict]:
        """
        Embed documents and add embedding to each document.

        Args:
            documents: List of document dicts
            text_key: Key containing text to embed
            batch_size: Number of documents per batch

        Returns:
            Documents with "embedding" key added
        """
        if not documents:
            return []

        texts = [doc.get(text_key, "") for doc in documents]
        embeddings = self.embed_batch(texts, batch_size=batch_size)

        for doc, embedding in zip(documents, embeddings):
            doc["embedding"] = embedding

        return documents
