"""
Lambda 1: Receiver

Handles incoming Slack webhook events from API Gateway.
- Verifies Slack signature
- Routes questions to SQS for async processing
- Returns 200 within Slack's 3-second timeout

Triggered by: API Gateway HTTP POST /slack/events
"""

import json
import logging
import os

import boto3

from app.core.slack.auth import (
    verify_slack_signature,
    extract_slack_headers,
    is_slack_retry,
)
from app.core.slack.client import get_signing_secret

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize SQS client (reused across invocations)
sqs = boto3.client("sqs")


def handler(event: dict, context) -> dict:
    """
    Lambda handler for Slack webhook events.

    Args:
        event: API Gateway HTTP API event
        context: Lambda context

    Returns:
        API Gateway response dict
    """
    logger.info(f"Received event: {json.dumps(event)[:500]}...")

    # Parse API Gateway event
    headers = event.get("headers", {})
    body = event.get("body", "")

    # Handle base64 encoding if present
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    # Skip Slack retries (we process async via SQS)
    if is_slack_retry(headers):
        logger.info("Skipping Slack retry request")
        return {"statusCode": 200, "body": "Retry skipped"}

    # Verify Slack signature
    timestamp, signature = extract_slack_headers(headers)
    signing_secret = get_signing_secret()

    if not verify_slack_signature(
        body=body,
        timestamp=timestamp,
        signature=signature,
        signing_secret=signing_secret,
    ):
        logger.error("Invalid Slack signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON body: {body[:100]}")
        return {"statusCode": 400, "body": "Invalid JSON"}

    # Handle URL verification challenge (Slack app setup)
    if payload.get("type") == "url_verification":
        logger.info("Handling URL verification challenge")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": payload["challenge"],
        }

    # Process event callbacks
    if payload.get("type") == "event_callback":
        return process_event_callback(payload)

    logger.info(f"Ignoring event type: {payload.get('type')}")
    return {"statusCode": 200, "body": "OK"}


def process_event_callback(payload: dict) -> dict:
    """
    Process Slack event callback.

    Args:
        payload: Slack event payload

    Returns:
        API Gateway response
    """
    slack_event = payload.get("event", {})
    event_type = slack_event.get("type")
    channel = slack_event.get("channel", "")

    logger.info(f"Processing event: {event_type} in channel {channel}")

    # Skip bot messages to prevent loops
    if slack_event.get("bot_id") or slack_event.get("subtype") == "bot_message":
        logger.info("Skipping bot message")
        return {"statusCode": 200, "body": "Bot message ignored"}

    # Route questions to QA queue
    # - app_mention: @bot questions
    # - message in DM channel (starts with D): Direct messages
    if event_type == "app_mention" or channel.startswith("D"):
        return route_to_qa_queue(slack_event)

    logger.info(f"Ignoring event type: {event_type}")
    return {"statusCode": 200, "body": "OK"}


def route_to_qa_queue(slack_event: dict) -> dict:
    """
    Send question to SQS for async processing.

    Args:
        slack_event: Slack event data

    Returns:
        API Gateway response
    """
    queue_url = os.environ.get("QA_QUEUE_URL")
    if not queue_url:
        logger.error("QA_QUEUE_URL not configured")
        return {"statusCode": 500, "body": "Queue not configured"}

    try:
        message_body = json.dumps(slack_event)
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body,
        )
        logger.info(f"Sent to SQS: {response['MessageId']}")
        return {"statusCode": 200, "body": "Queued"}

    except Exception as e:
        logger.error(f"Failed to send to SQS: {e}")
        return {"statusCode": 500, "body": "Queue error"}
