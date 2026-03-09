"""
Amazon Bedrock Claude LLM client.

Uses Claude 3.5 Sonnet for high-quality answer generation.
"""

import json
import logging
import re
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockLLM:
    """Client for Amazon Bedrock Claude."""

    MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
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
        current_time: str = "2026-02-12",
    ) -> str:
        """
        Generate a RAG answer with context.

        Args:
            question: User's question
            context_chunks: List of dicts with 'text', 'channel_name', 'message_ts', 'permalink'
            language: Response language
            max_tokens: Maximum tokens in response
            current_time: Current date/time reference for temporal reasoning

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
            message_ts = chunk.get("message_ts") or "N/A"
            post_date = chunk.get("post_date") or "Unknown"

            context_parts.append(
                f"[Source {i}: {source}]\n[Post Date: {post_date}]\n"
                f"message_ts: {message_ts}\n{chunk.get('text', '')}"
            )

        context = "\n\n".join(context_parts)

        no_match_message = "情報が見つかりません"

        system = f"""You are a reliable AI assistant for Slack QA.
Answer in {language}.

Follow these rules strictly:
1. First classify the user's input as either greeting/small talk or a factual question.
2. If it is greeting/small talk (e.g., "こんにちは", "ありがとう"), respond naturally and politely without using or mentioning any provided context.
3. If it is a factual question, answer using ONLY the provided context.
4. For factual questions, strictly follow all user conditions (role, employment type, period, department, etc.).
5. Exclude any people or facts that do not fully match those conditions.
6. If no fully matching information exists in context, answer exactly: "{no_match_message}".
7. Do not guess, infer missing facts, or fabricate information.
8. Keep answers concise and factual.
9. Current Time: {current_time}.
10. For each source, [Post Date: YYYY-MM-DD HH:mm] is the readable posting time derived from `message_ts`.
11. Relative date expressions inside a message text (e.g., "今日", "昨日", "先週", "today", "yesterday", "last week") must be interpreted relative to that source's [Post Date], not Current Time.
12. For each source, `message_ts` is a Unix timestamp; a larger numeric value means a newer post.
13. Before generating an answer for factual questions, perform this chronological consistency check internally (do not expose this checklist in output):
   - When was each message posted based on [Post Date] and `message_ts`?
   - Is each date expression in the text consistent with the posting date?
   - Is the interpreted event date on or before Current Time?
14. Future date protection: Never claim that an event already happened on a date after Current Time.
15. Incomplete date interpretation rule: If a text says only a day number such as "19日から" without explicit month/year, interpret it as the same month as the source message's [Post Date], or an earlier month if explicitly indicated by context. Never assume the next month unless the text explicitly says so.
16. When text date expressions conflict with metadata timing, prioritize `message_ts` for chronological ordering.
17. Never invent year/month/day values that are not explicitly present in the text or metadata. Never misread Unix timestamps into fabricated years.
18. For comparative time questions (latest/recent/oldest), sort all retrieved sources (up to 30) by date information before answering."""

        # Detect if the input is a greeting or small talk
        greeting_patterns_ja = [
            "こんにちは", "こんばんは", "おはよう", "ありがとう", "お疲れ",
            "元気", "よろしく", "ただいま", "おやすみ", "はじめまして",
        ]
        normalized_question = question.strip().lower()
        has_ja_greeting = any(p in normalized_question for p in greeting_patterns_ja)
        has_en_greeting = bool(
            re.search(r"\b(?:hello|hi|hey|thanks|thank you)\b", normalized_question)
        )
        is_greeting = (
            bool(normalized_question)
            and len(normalized_question) <= 40
            and (has_ja_greeting or has_en_greeting)
        )

        if is_greeting:
            prompt = f"""User input: "{question}"

This is greeting or small talk.
Respond in Japanese with one short, natural, polite sentence.
Do not mention context, documents, or sources."""
        else:
            prompt = f"""Answer the user's question using ONLY the context below.

Requirements:
- Strictly apply user conditions (role, employment type, period, department, etc.).
- Exclude any person or information that does not fully match.
- If no fully matching information exists, answer exactly: "{no_match_message}".
- Do not include guesses or assumptions.

Context:
{context}

Question: {question}

Answer:"""

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
