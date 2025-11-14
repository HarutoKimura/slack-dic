"""Utilities for working with Slack permalinks."""

from slack_sdk import WebClient


def get_permalink(client: WebClient, channel: str, message_ts: str) -> str | None:
    """
    Get a permalink for a Slack message.

    Args:
        client: Slack WebClient instance
        channel: Channel ID
        message_ts: Message timestamp

    Returns:
        Permalink URL or None if request fails
    """
    try:
        response = client.chat_getPermalink(channel=channel, message_ts=message_ts)
        if response["ok"]:
            return response["permalink"]
    except Exception as e:
        print(f"Error getting permalink: {e}")
    return None
