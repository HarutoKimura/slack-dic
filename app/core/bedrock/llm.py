"""
Amazon Bedrock Claude LLM client.

Uses Claude 3 Haiku for fast, cost-effective answer generation.
"""

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockLLM:
    """Client for Amazon Bedrock Claude."""

    MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
    MAX_TOKENS_DEFAULT = 1024

    def __init__(
        self,
        region_name: str = "us-east-1",
        client: Optional[boto3.client] = None,
    ):
        """
        Initialize Bedrock LLM client.

        Args:
            region_name: AWS region for Bedrock
            client: Optional pre-configured boto3 client (for testing)
        """
        self._client = client or boto3.client(
            "bedrock-runtime", region_name=region_name
        )
        self._region = region_name
        logger.info(f"Initialized Bedrock LLM client in {region_name}")

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = MAX_TOKENS_DEFAULT,
        temperature: float = 0.7,
    ) -> str:
        """
        Generate a response from Claude.

        Args:
            prompt: User prompt
            system: Optional system prompt
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0-1)

        Returns:
            Generated text response
        """
        messages = [{"role": "user", "content": prompt}]

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system:
            body["system"] = system

        try:
            response = self._client.invoke_model(
                modelId=self.MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )

            result = json.loads(response["body"].read())
            return result["content"][0]["text"]

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ThrottlingException":
                logger.warning("Bedrock rate limit hit, retrying after 1s...")
                time.sleep(1)
                return self.generate(prompt, system, max_tokens, temperature)
            raise

    def generate_answer(
        self,
        question: str,
        context_chunks: list[dict],
        language: str = "Japanese",
        max_tokens: int = MAX_TOKENS_DEFAULT,
    ) -> str:
        """
        Generate a RAG answer with context.

        Args:
            question: User's question
            context_chunks: List of dicts with 'text', 'channel_name', 'permalink'
            language: Response language
            max_tokens: Maximum tokens in response

        Returns:
            Generated answer text
        """
        # Build context string
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            source_info = []
            if chunk.get("channel_name"):
                source_info.append(f"#{chunk['channel_name']}")
            if chunk.get("user_name"):
                source_info.append(f"by {chunk['user_name']}")
            source = " ".join(source_info) if source_info else "Unknown"

            context_parts.append(
                f"[Source {i}: {source}]\n{chunk.get('text', '')}"
            )

        context = "\n\n".join(context_parts)

        system = f"""You are a helpful assistant that answers questions based on Slack message history.
Answer in {language}.
Only use information from the provided context.
If the information is not in the context, say "その情報は見つかりませんでした" (I couldn't find that information).
Be concise and direct.
Do not make up information.
If quoting from sources, refer to them by number (e.g., "Source 1によると...")."""

        prompt = f"""Context from Slack messages:
{context}

Question: {question}

Answer based only on the context above:"""

        return self.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=0.3,  # Lower temperature for factual answers
        )

    def generate_summary(
        self,
        texts: list[str],
        max_tokens: int = 512,
        language: str = "Japanese",
    ) -> str:
        """
        Generate a summary of multiple texts.

        Args:
            texts: List of texts to summarize
            max_tokens: Maximum tokens in response
            language: Response language

        Returns:
            Summary text
        """
        combined = "\n\n---\n\n".join(texts)

        system = f"""You are a helpful assistant that summarizes information.
Answer in {language}.
Be concise and capture the key points."""

        prompt = f"""Please summarize the following information:

{combined}

Summary:"""

        return self.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=0.5,
        )
