"""Fetch messages from Slack channels."""

from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.utils.slack_links import get_permalink


def get_channel_id(client: WebClient, channel_name: str) -> str | None:
    """
    Get channel ID from channel name.

    Args:
        client: Slack WebClient instance
        channel_name: Channel name (with or without #)

    Returns:
        Channel ID or None if not found
    """
    # Strip # if present
    channel_name = channel_name.lstrip("#")

    try:
        response = client.conversations_list(types="public_channel,private_channel")
        for channel in response["channels"]:
            if channel["name"] == channel_name:
                return channel["id"]
    except SlackApiError as e:
        print(f"Error fetching channel list: {e}")

    return None


def fetch_channel_messages(
    client: WebClient, channel_id: str, limit: int = 1000
) -> list[dict[str, Any]]:
    """
    Fetch messages from a Slack channel.

    Args:
        client: Slack WebClient instance
        channel_id: Channel ID
        limit: Maximum number of messages to fetch

    Returns:
        List of message documents with structure:
        {
            "id": "ts-based-id",
            "channel": "Cxxxx",
            "text": "...",
            "user": "Uxxxx",
            "ts": "1712345678.9012",
            "permalink": "https://..."
        }
    """
    messages = []
    cursor = None
    fetched = 0

    try:
        while fetched < limit:
            response = client.conversations_history(
                channel=channel_id, limit=min(200, limit - fetched), cursor=cursor
            )

            for msg in response["messages"]:
                # Skip messages without text (e.g., file uploads without text)
                if "text" not in msg or not msg["text"].strip():
                    continue

                # Skip bot messages if desired (optional)
                # if msg.get("bot_id"):
                #     continue

                permalink = get_permalink(client, channel_id, msg["ts"])

                doc = {
                    "id": f"{channel_id}-{msg['ts']}",
                    "channel": channel_id,
                    "text": msg["text"],
                    "user": msg.get("user", "unknown"),
                    "ts": msg["ts"],
                    "permalink": permalink or "",
                }
                messages.append(doc)
                fetched += 1

                if fetched >= limit:
                    break

            # Check for more messages
            if not response.get("has_more"):
                break

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except SlackApiError as e:
        print(f"Error fetching messages: {e}")

    print(f"Fetched {len(messages)} messages from channel {channel_id}")
    return messages
