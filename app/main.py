"""Main entry point for the Slack RAG bot."""

from app.rag.answer import ask
from app.settings import settings


def main():
    """
    Main entry point.

    If SLACK_APP_TOKEN or SOCKET_MODE_TOKEN is configured, starts Socket Mode listener.
    Otherwise, runs a simple CLI test prompt.
    """
    if settings.get_socket_mode_token():
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
