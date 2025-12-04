"""Main entry point for the Slack RAG bot."""

from slack_sdk import WebClient

from app.rag.answer import ask
from app.settings import settings


def main():
    """
    Main entry point.

    If SLACK_APP_TOKEN or SOCKET_MODE_TOKEN is configured, starts Socket Mode listener.
    Otherwise, runs a simple CLI test prompt.
    """
    if settings.get_socket_mode_token():
        # Run startup catch-up indexing before starting the bot
        if settings.startup_index_enabled:
            from app.ingestion.startup import startup_index, check_and_index_new_channels

            client = WebClient(token=settings.slack_bot_token)

            # First, check for any channels that were joined while bot was offline
            # and haven't been indexed yet
            check_and_index_new_channels(client)

            # Then, catch up on recent messages from all channels
            startup_index(client, hours=settings.startup_index_hours)

        # Start Socket Mode
        from app.slack_app import start_socket_mode

        start_socket_mode()
    else:
        print("Socket Mode token not found. Running in CLI test mode.")
        print("Set SLACK_APP_TOKEN or SOCKET_MODE_TOKEN in .env to run Socket Mode.")
        print("\nAsk a question (or 'quit' to exit):")

        while True:
            try:
                question = input("\n> ").strip()

                if question.lower() in ["quit", "exit", "q"]:
                    print("Goodbye!")
                    break

                if not question:
                    continue

                answer = ask(question)
                print(f"\n{answer}")

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    main()
