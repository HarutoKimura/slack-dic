"""
Slack WebClient wrapper with SSM Parameter Store integration.

Retrieves bot token from SSM in production, environment variable in development.
"""

import logging
import os
from functools import lru_cache
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

# Cached client instance
_client: Optional[WebClient] = None


def get_slack_token() -> str:
    """
    Get Slack bot token from SSM Parameter Store or environment variable.

    In production (Lambda), reads from SSM using the parameter name in
    SLACK_BOT_TOKEN_PARAM environment variable.

    In development, uses SLACK_BOT_TOKEN environment variable directly.

    Returns:
        Slack bot token (xoxb-...)
    """
    # Check for direct token first (development)
    token = os.environ.get("SLACK_BOT_TOKEN")
    if token:
        return token

    # Check for SSM parameter path (production)
    param_name = os.environ.get("SLACK_BOT_TOKEN_PARAM")
    if param_name:
        import boto3

        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return response["Parameter"]["Value"]

    raise ValueError(
        "No Slack bot token configured. "
        "Set SLACK_BOT_TOKEN or SLACK_BOT_TOKEN_PARAM environment variable."
    )


def get_signing_secret() -> str:
    """
    Get Slack signing secret from SSM Parameter Store or environment variable.

    Returns:
        Slack signing secret
    """
    # Check for direct secret first (development)
    secret = os.environ.get("SLACK_SIGNING_SECRET")
    if secret:
        return secret

    # Check for SSM parameter path (production)
    param_name = os.environ.get("SLACK_SIGNING_SECRET_PARAM")
    if param_name:
        import boto3

        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return response["Parameter"]["Value"]

    raise ValueError(
        "No Slack signing secret configured. "
        "Set SLACK_SIGNING_SECRET or SLACK_SIGNING_SECRET_PARAM environment variable."
    )


def get_slack_client() -> WebClient:
    """
    Get or create Slack WebClient instance.

    Returns a cached client for reuse across Lambda invocations.

    Returns:
        Configured Slack WebClient
    """
    global _client

    if _client is None:
        token = get_slack_token()
        _client = WebClient(token=token)
        logger.info("Initialized Slack WebClient")

    return _client


@lru_cache(maxsize=100)
def get_channel_name(channel_id: str) -> Optional[str]:
    """
    Get channel name from channel ID.

    Results are cached for performance.

    Args:
        channel_id: Slack channel ID (e.g., C1234567890)

    Returns:
        Channel name or None if not found
    """
    try:
        client = get_slack_client()
        response = client.conversations_info(channel=channel_id)
        return response["channel"]["name"]
    except SlackApiError as e:
        logger.warning(f"Failed to get channel name for {channel_id}: {e}")
        return None


@lru_cache(maxsize=100)
def get_user_name(user_id: str) -> Optional[str]:
    """
    Get user display name from user ID.

    Results are cached for performance.

    Args:
        user_id: Slack user ID (e.g., U1234567890)

    Returns:
        User display name or None if not found
    """
    try:
        client = get_slack_client()
        response = client.users_info(user=user_id)
        user = response["user"]
        # Prefer display_name, fall back to real_name
        return (
            user.get("profile", {}).get("display_name")
            or user.get("real_name")
            or user.get("name")
        )
    except SlackApiError as e:
        logger.warning(f"Failed to get user name for {user_id}: {e}")
        return None


def get_permalink(channel_id: str, message_ts: str) -> Optional[str]:
    """
    Get permalink for a Slack message.

    Args:
        channel_id: Slack channel ID
        message_ts: Message timestamp

    Returns:
        Permalink URL or None if failed
    """
    try:
        client = get_slack_client()
        response = client.chat_getPermalink(channel=channel_id, message_ts=message_ts)
        return response.get("permalink")
    except SlackApiError as e:
        logger.warning(f"Failed to get permalink for {channel_id}/{message_ts}: {e}")
        return None


def post_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
) -> bool:
    """
    Post a message to Slack.

    Args:
        channel: Channel ID to post to
        text: Message text
        thread_ts: Optional thread timestamp for replies

    Returns:
        True if successful, False otherwise
    """
    try:
        client = get_slack_client()
        kwargs = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        client.chat_postMessage(**kwargs)
        return True
    except SlackApiError as e:
        logger.error(f"Failed to post message to {channel}: {e}")
        return False
