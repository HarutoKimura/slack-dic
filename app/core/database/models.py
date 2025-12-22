"""
Pydantic models for database entities.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MessageChunk(BaseModel):
    """A chunk of a Slack message stored in the vector database."""

    id: str = Field(..., description="Unique ID: {channel_id}_{ts}_{chunk_idx}")
    channel_id: str = Field(..., description="Slack channel ID")
    channel_name: Optional[str] = Field(None, description="Slack channel name")
    message_ts: str = Field(..., description="Slack message timestamp")
    chunk_index: int = Field(default=0, description="Index of chunk within message")
    text: str = Field(..., description="Chunk text content")
    embedding: list[float] = Field(..., description="Vector embedding (1536 dims)")
    user_id: Optional[str] = Field(None, description="Slack user ID")
    user_name: Optional[str] = Field(None, description="Slack user display name")
    permalink: Optional[str] = Field(None, description="Link to original message")
    indexed_at: Optional[datetime] = Field(None, description="When chunk was indexed")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")

    def to_db_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name or "",
            "message_ts": self.message_ts,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "embedding": self.embedding,
            "user_id": self.user_id or "",
            "user_name": self.user_name or "",
            "permalink": self.permalink or "",
            "metadata": self.metadata,
        }


class SearchResult(BaseModel):
    """Result from a vector similarity search."""

    id: str
    channel_name: Optional[str]
    text: str
    permalink: Optional[str]
    user_name: Optional[str]
    similarity: float = Field(..., ge=0.0, le=1.0)

    @property
    def source_info(self) -> str:
        """Format source information for display."""
        parts = []
        if self.channel_name:
            parts.append(f"#{self.channel_name}")
        if self.user_name:
            parts.append(f"by {self.user_name}")
        return " ".join(parts) if parts else "Unknown source"
