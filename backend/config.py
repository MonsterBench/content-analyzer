"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    apify_api_token: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Database
    database_url: str = "sqlite:///./content_analyzer.db"

    # ChromaDB
    chroma_persist_dir: str = "./chroma_data"

    # App
    app_name: str = "Content Analyzer"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]

    # Scraping
    apify_max_retries: int = 3
    apify_retry_delay: int = 5
    whisper_batch_size: int = 5

    # AI
    claude_model: str = "claude-sonnet-4-5-20250929"
    embedding_model: str = "text-embedding-3-small"
    chat_history_limit: int = 10

    # Chat limits
    max_message_length: int = 100_000
    max_keyword_extract_chars: int = 500
    max_keywords: int = 15
    max_user_msg_to_claude: int = 12_000
    max_system_prompt_chars: int = 120_000

    # File upload
    max_file_size: int = 500_000  # 500KB
    max_files_per_message: int = 3
    allowed_file_extensions: list[str] = [".txt", ".md", ".csv", ".json"]

    # Knowledge generation
    knowledge_summary_batch_size: int = 10
    knowledge_rate_limit_delay: float = 1.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
