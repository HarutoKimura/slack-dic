"""Test script for the improved chunking logic."""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.ingestion.chunk import chunk_text


def test_basic_chunking():
    """Test basic chunking with long text."""
    print("=" * 60)
    print("TEST 1: Basic chunking with long text (no overlap)")
    print("=" * 60)

    text = """Here is the first sentence with important context. Check out this link https://example.com/very/long/path/to/resource for more details. After the URL we have more content that keeps going. Then we have another paragraph with different information that should be in the next chunk. And even more text to make sure we get multiple chunks created."""

    chunks = chunk_text(text, chunk_size=150, overlap=0)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        print("---")


def test_url_protection():
    """Test that URLs are not split."""
    print("\n" + "=" * 60)
    print("TEST 2: URL protection (no overlap)")
    print("=" * 60)

    text = """Short intro. https://example.com/this/is/a/very/long/url/that/should/not/be/broken/in/the/middle/ever More text after the URL that continues for a while to ensure chunking happens."""

    chunks = chunk_text(text, chunk_size=100, overlap=0)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        # Check if URL is complete
        if "https://example.com" in c:
            if "/ever" in c:
                print("[OK] URL is complete")
            else:
                print("[WARNING] URL might be split!")
        print("---")


def test_code_block_protection():
    """Test that code blocks are not split."""
    print("\n" + "=" * 60)
    print("TEST 3: Code block protection (no overlap)")
    print("=" * 60)

    text = """Here is some text before code.

```python
def hello():
    print("Hello, World!")
    return True
```

And here is text after the code block that continues for a while to test chunking behavior."""

    chunks = chunk_text(text, chunk_size=100, overlap=0)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        # Check code block integrity
        if "```python" in c:
            if c.count("```") == 2:
                print("[OK] Code block is complete")
            else:
                print("[WARNING] Code block might be split!")
        print("---")


def test_list_protection():
    """Test that list items are not split."""
    print("\n" + "=" * 60)
    print("TEST 4: List item protection (no overlap)")
    print("=" * 60)

    text = """Here are the main points to consider:

- First item is about configuration and setup requirements
- Second item covers the implementation details
- Third item discusses testing and validation

After the list, we have concluding remarks that wrap up the discussion."""

    chunks = chunk_text(text, chunk_size=120, overlap=0)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        print("---")


def test_slack_url_format():
    """Test Slack-formatted URLs like <url|text>."""
    print("\n" + "=" * 60)
    print("TEST 5: Slack URL format protection (no overlap)")
    print("=" * 60)

    text = """Check out this resource <https://slack.com/help/articles/123456|Slack Help Article> for more information. There is additional context here that explains the topic in more detail and continues for a while."""

    chunks = chunk_text(text, chunk_size=100, overlap=0)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        # Check Slack URL integrity
        if "<https://" in c:
            if ">" in c and c.index(">") > c.index("<https://"):
                print("[OK] Slack URL is complete")
            else:
                print("[WARNING] Slack URL might be split!")
        print("---")


def test_with_overlap():
    """Test chunking with overlap enabled."""
    print("\n" + "=" * 60)
    print("TEST 6: Chunking WITH overlap (overlap=50)")
    print("=" * 60)

    text = """First sentence here. Second sentence continues. Third sentence adds more. Fourth sentence keeps going. Fifth sentence wraps up the first part. Sixth sentence starts new topic. Seventh sentence elaborates."""

    chunks = chunk_text(text, chunk_size=80, overlap=50)

    for i, c in enumerate(chunks):
        print(f"\nChunk {i} ({len(c)} chars):")
        print(c)
        print("---")

    print("\nNote: With overlap, chunks share some content for context continuity.")


if __name__ == "__main__":
    test_basic_chunking()
    test_url_protection()
    test_code_block_protection()
    test_list_protection()
    test_slack_url_format()
    test_with_overlap()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
