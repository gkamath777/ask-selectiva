"""Application configuration."""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://selectiva:selectiva_dev@localhost:5432/ask_selectiva"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    # Max ms between poll() iterations while processing a message (default broker-side ~5m).
    # Large PDFs + local embeddings exceed that → CommitFailedError / rebalance.
    kafka_max_poll_interval_ms: int = 1_800_000  # 30 minutes

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    # Use a model you have pulled (e.g. llama3.1:8b). Set to mixtral only after `ollama pull mixtral`.
    ollama_escalation_model: str = "llama3.1:8b"
    ollama_temperature: float = 0.3
    ollama_max_tokens: int = 1024
    # httpx read timeout for /api/chat (seconds). First model load + long RAG prompts often exceed 120s.
    ollama_request_timeout_seconds: float = 600.0

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # Webhook
    webhook_secret: Optional[str] = None

    # Google Drive push → ingest PDFs from a watched folder
    # Folder must be shared with the service account email (Viewer).
    google_drive_folder_id: Optional[str] = None
    google_drive_tenant_id: Optional[str] = None
    google_service_account_file: Optional[str] = None
    google_service_account_json: Optional[str] = None
    # Public https URL of this API, e.g. https://your-domain.com (no trailing slash)
    google_drive_public_base_url: Optional[str] = None
    # Query token on the push URL; must match ?token= on the registered watch address
    google_drive_webhook_token: Optional[str] = None

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
