"""Settings loader using Pydantic BaseSettings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI
    openai_api_key: str

    # Slack
    slack_bot_token: str
    slack_app_token: str | None = None  # Socket Mode token (also accepts SOCKET_MODE_TOKEN)
    socket_mode_token: str | None = None  # Alternative name for slack_app_token

    # Chroma
    chroma_persist_directory: str = ".chroma"

    # Embedding model
    embedding_model: str = "text-embedding-3-small"

    # LLM model
    llm_model: str = "gpt-5-mini-2025-08-07"

    # Real-time indexing
    realtime_index_enabled: bool = True
    realtime_index_channels: str = ""  # Comma-separated channel IDs or names (empty = all)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_socket_mode_token(self) -> str | None:
        """Get Socket Mode token (supports both SLACK_APP_TOKEN and SOCKET_MODE_TOKEN)."""
        return self.slack_app_token or self.socket_mode_token


# Global settings instance
settings = Settings()
