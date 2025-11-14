"""CLI script for asking questions via RAG."""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag.answer import ask


def main():
    """Main CLI question script."""
    parser = argparse.ArgumentParser(description="Ask questions via RAG")
    parser.add_argument("--q", "--question", type=str, required=True, help="Question to ask")
    parser.add_argument("--top-k", type=int, default=5, help="Number of context documents to retrieve")

    args = parser.parse_args()

    # Ask question
    print(f"Question: {args.q}\n")
    answer = ask(args.q, top_k=args.top_k)
    print(answer)


if __name__ == "__main__":
    main()
