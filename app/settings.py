"""Settings loader using Pydantic BaseSettings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI
    openai_api_key: str

    # Slack
    slack_bot_token: str
    slack_app_token: str | None = None

    # Chroma
    chroma_persist_directory: str = ".chroma"

    # Embedding model
    embedding_model: str = "text-embedding-3-small"

    # LLM model
    llm_model: str = "gpt-5-mini-2025-08-07"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
settings = Settings()
