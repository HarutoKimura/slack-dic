"""Slack Bot application using Bolt for Python."""

import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.rag.answer import ask
from app.settings import settings

# Initialize Slack app
app = App(token=settings.slack_bot_token)


@app.event("app_mention")
def handle_mention(event, say, logger):
    """Handle @mention of the bot."""
    try:
        # Extract question from message (remove bot mention)
        text = event["text"]
        # Remove <@BOT_ID> mention
        question = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

        if not question:
            say(
                text="Please ask me a question!",
                thread_ts=event.get("thread_ts") or event["ts"],
            )
            return

        logger.info(f"Question: {question}")

        # Generate answer
        answer = ask(question)

        # Reply in thread
        say(text=answer, thread_ts=event.get("thread_ts") or event["ts"])

    except Exception as e:
        logger.error(f"Error handling mention: {e}")
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


def start_socket_mode():
    """Start the Slack app in Socket Mode."""
    if not settings.slack_app_token:
        raise ValueError(
            "SLACK_APP_TOKEN is required for Socket Mode. "
            "Please set it in your .env file."
        )

    handler = SocketModeHandler(app, settings.slack_app_token)
    print("⚡️ Slack RAG bot is running in Socket Mode!")
    handler.start()
