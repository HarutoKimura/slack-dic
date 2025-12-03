"""Script to make the bot join all public channels."""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.settings import settings


def get_all_public_channels(client: WebClient) -> list[dict]:
    """Fetch all public channels."""
    channels = []
    cursor = None

    try:
        while True:
            response = client.conversations_list(
                types="public_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )

            for channel in response["channels"]:
                channels.append({
                    "id": channel["id"],
                    "name": channel["name"],
                    "is_member": channel.get("is_member", False),
                })

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except SlackApiError as e:
        print(f"Error fetching channels: {e}")

    return channels


def join_channel(client: WebClient, channel_id: str, channel_name: str) -> bool:
    """Join a channel. Returns True if successful."""
    try:
        client.conversations_join(channel=channel_id)
        return True
    except SlackApiError as e:
        print(f"  ❌ Failed to join #{channel_name}: {e.response['error']}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Make the bot join all public channels"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List channels without joining",
    )

    args = parser.parse_args()

    print("Initializing Slack client...")
    client = WebClient(token=settings.slack_bot_token)

    print("Fetching all public channels...")
    channels = get_all_public_channels(client)

    if not channels:
        print("No channels found.")
        return

    # Separate joined and not-joined
    joined = [ch for ch in channels if ch["is_member"]]
    not_joined = [ch for ch in channels if not ch["is_member"]]

    print(f"\nFound {len(channels)} public channels:")
    print(f"  - Already joined: {len(joined)}")
    print(f"  - Not joined: {len(not_joined)}")

    if not not_joined:
        print("\n✅ Bot is already a member of all public channels!")
        return

    print(f"\nChannels to join:")
    for ch in not_joined:
        print(f"  - #{ch['name']}")

    if args.dry_run:
        print("\n[Dry run] No channels joined.")
        return

    print(f"\nJoining {len(not_joined)} channels...")
    success_count = 0

    for ch in not_joined:
        print(f"  Joining #{ch['name']}...", end=" ")
        if join_channel(client, ch["id"], ch["name"]):
            print("✅")
            success_count += 1

    print(f"\n{'='*40}")
    print(f"Successfully joined {success_count}/{len(not_joined)} channels")


if __name__ == "__main__":
    main()
