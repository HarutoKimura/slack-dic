"""
Lambda 2: QA Processor

Processes questions from SQS and generates answers using RAG.
- Embeds the question using Bedrock Titan
- Searches Aurora for similar chunks
- Generates answer using Bedrock Claude
- Posts reply to Slack

Triggered by: SQS QA Queue
"""

import json
import logging
import os
import re

from app.core.bedrock import BedrockEmbeddings, BedrockLLM
from app.core.database import MessageRepository
from app.core.rag import ask
from app.core.slack.client import get_slack_client

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
CURRENT_TIME = "2026-02-12"

# Initialize clients (reused across invocations for warm starts)
_embeddings = None
_llm = None
_repository = None


def get_embeddings() -> BedrockEmbeddings:
    """Get or create embeddings client."""
    global _embeddings
    if _embeddings is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _embeddings = BedrockEmbeddings(region_name=region)
    return _embeddings


def get_llm() -> BedrockLLM:
    """Get or create LLM client."""
    global _llm
    if _llm is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _llm = BedrockLLM(region_name=region)
    return _llm


def get_repository() -> MessageRepository:
    """Get or create message repository."""
    global _repository
    if _repository is None:
        _repository = MessageRepository()
    return _repository


def handler(event: dict, context) -> dict:
    """
    Lambda handler for SQS messages.

    Args:
        event: SQS event with Records
        context: Lambda context

    Returns:
        Status dict
    """
    logger.info(f"Processing {len(event.get('Records', []))} messages")

    for record in event.get("Records", []):
        try:
            process_record(record)
        except Exception as e:
            logger.error(f"Failed to process record: {e}", exc_info=True)
            # Re-raise to trigger DLQ on failure
            raise

    return {"statusCode": 200}


def process_record(record: dict) -> None:
    """
    Process a single SQS record.

    Args:
        record: SQS record with Slack event in body
    """
    # Parse Slack event from SQS message body
    slack_event = json.loads(record["body"])

    channel = slack_event.get("channel")
    thread_ts = slack_event.get("thread_ts") or slack_event.get("ts")
    text = slack_event.get("text", "")
    user = slack_event.get("user")

    logger.info(f"Processing question from {user} in {channel}: {text[:50]}...")

    # Extract question (remove bot mention)
    question = extract_question(text)

    if not question:
        logger.warning("Empty question after extraction")
        return

    try:
        # Generate answer using RAG
        answer, results = ask(
            question=question,
            repository=get_repository(),
            embeddings=get_embeddings(),
            llm=get_llm(),
            top_k=25,
            min_similarity=0.25,
            include_sources=True,
            current_time=CURRENT_TIME,
        )

        logger.info(f"Generated answer ({len(answer)} chars) from {len(results)} sources")

    except Exception as e:
        logger.error(f"RAG error: {e}", exc_info=True)
        answer = "申し訳ありません。エラーが発生しました。しばらくしてからもう一度お試しください。"

    # Post reply to Slack
    try:
        client = get_slack_client()
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=answer,
        )
        logger.info(f"Posted reply to {channel}/{thread_ts}")

    except Exception as e:
        logger.error(f"Failed to post to Slack: {e}", exc_info=True)
        raise


def extract_question(text: str) -> str:
    """
    Extract the question from message text.

    Removes bot mentions and cleans up whitespace.

    Args:
        text: Raw message text

    Returns:
        Cleaned question text
    """
    # Remove bot mentions (<@U12345678>)
    question = re.sub(r"<@[A-Z0-9]+>", "", text)

    # Remove extra whitespace
    question = " ".join(question.split())

    return question.strip()
