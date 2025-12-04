# Slack RAG Bot Dockerfile
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies for chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first (for better caching)
COPY pyproject.toml README.md ./

# Install dependencies
RUN uv pip install --system --no-cache .

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Create directory for ChromaDB persistence
RUN mkdir -p /app/.chroma

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CHROMA_PERSIST_DIRECTORY=/app/.chroma

# Run the bot
CMD ["python", "-m", "app.main"]
