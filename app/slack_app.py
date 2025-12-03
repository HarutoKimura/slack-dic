"""Slack Bot application using Bolt for Python."""

import logging
import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.ingestion.realtime import index_slack_message
from app.rag.answer import ask
from app.settings import settings

logger = logging.getLogger(__name__)

# Initialize Slack app
app = App(token=settings.slack_bot_token)


def is_dm_channel(channel_id: str) -> bool:
    """Check if a channel ID is a DM (direct message) channel."""
    # DM channels start with 'D', group DMs start with 'G' (for MPDMs)
    return channel_id.startswith("D")


@app.event("app_mention")
def handle_mention(event, say, logger):
    """Handle @mention of the bot."""
    logger.info(f"Received app_mention event: {event}")
    try:
        # Extract question from message (remove bot mention)
        text = event["text"]
        logger.info(f"Full message text: {text}")

        # Remove <@BOT_ID> mention
        question = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
        logger.info(f"Question after removing mention: {question}")

        if not question:
            logger.info("No question found, asking user to provide one")
            say(
                text="Please ask me a question!",
                thread_ts=event.get("thread_ts") or event["ts"],
            )
            return

        logger.info(f"Processing question: {question}")

        # Generate answer
        logger.info("Calling ask() to generate answer...")
        answer = ask(question)
        logger.info(f"Generated answer (length: {len(answer)}): {answer[:100]}...")

        # Reply in thread
        logger.info(f"Sending response to Slack...")
        say(text=answer, thread_ts=event.get("thread_ts") or event["ts"])
        logger.info("Response sent successfully!")

    except Exception as e:
        logger.error(f"Error handling mention: {e}", exc_info=True)
        say(
            text=f"Sorry, I encountered an error: {e}",
            thread_ts=event.get("thread_ts") or event["ts"],
        )


@app.command("/ask")
def handle_ask_command(ack, command, say, logger):
    """Handle /ask slash command."""
    try:
        # Acknowledge command immediately
        ack()

        question = command["text"].strip()

        if not question:
            say("Please provide a question. Usage: `/ask What is RAG?`")
            return

        logger.info(f"Question: {question}")

        # Generate answer
        answer = ask(question)

        # Reply
        say(answer)

    except Exception as e:
        logger.error(f"Error handling /ask command: {e}")
        say(f"Sorry, I encountered an error: {e}")


@app.event("message")
def handle_message(event, client, say):
    """Handle new messages - DMs for Q&A, channels for real-time indexing."""
    try:
        # Skip bot messages
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        # Skip messages without text
        text = event.get("text", "").strip()
        if not text:
            return

        channel_id = event.get("channel", "")

        # Handle DM messages - treat as questions
        if is_dm_channel(channel_id):
            logger.info(f"Received DM from user {event.get('user')}: {text[:50]}...")
            print(f"[DM DEBUG] Question received: {text}")

            # Generate answer from indexed messages across all channels
            answer = ask(text, debug=True)
            print(f"[DM DEBUG] Answer generated: {answer[:100]}...")

            # Reply in DM
            say(text=answer)
            logger.info("Sent DM response successfully")
            return

        # For non-DM messages: real-time indexing
        if not settings.realtime_index_enabled:
            return

        # Channel filtering (if configured)
        if settings.realtime_index_channels:
            allowed_channels = [
                ch.strip() for ch in settings.realtime_index_channels.split(",")
            ]

            # Check if channel ID or name is in allowed list
            # Note: For channel names, we'd need to resolve them, but for simplicity
            # we'll just check channel IDs for now
            if channel_id not in allowed_channels:
                logger.debug(
                    "Skipping message from channel %s (not in allowed list)", channel_id
                )
                return

        # Index the message
        logger.info(
            "Indexing new message: channel=%s ts=%s user=%s",
            channel_id,
            event.get("ts"),
            event.get("user", "unknown"),
        )

        num_chunks = index_slack_message(client, event)

        logger.info(
            "Indexed message ts=%s channel=%s into %d chunks",
            event.get("ts"),
            channel_id,
            num_chunks,
        )

    except Exception as e:
        # Log error but don't crash the app
        logger.error("Error handling message: %s", e, exc_info=True)
        # For DMs, try to send error message back to user
        if is_dm_channel(event.get("channel", "")):
            try:
                say(text=f"Sorry, I encountered an error: {e}")
            except Exception:
                pass


def start_socket_mode():
    """Start the Slack app in Socket Mode."""
    socket_token = settings.get_socket_mode_token()
    if not socket_token:
        raise ValueError(
            "Socket Mode token is required. "
            "Please set SLACK_APP_TOKEN or SOCKET_MODE_TOKEN in your .env file."
        )

    handler = SocketModeHandler(app, socket_token)
    print("⚡️ Slack RAG bot is running in Socket Mode!")
    handler.start()
