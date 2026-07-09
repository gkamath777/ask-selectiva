"""Application configuration."""
from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Runtime
    app_environment: str = "development"
    create_db_on_startup: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://selectiva:selectiva_dev@localhost:5432/ask_selectiva"
    db_pool_size: int = 20
    db_max_overflow: int = 10

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

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.5"
    openai_temperature: float = 0.3
    openai_max_output_tokens: int = 4096
    openai_request_timeout_seconds: float = 600.0

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # API security
    # When set, protected endpoints require X-API-Key: <value>.
    api_key: Optional[str] = None
    cors_allowed_origins: str = "*"
    max_request_body_bytes: int = 10 * 1024 * 1024
    max_webhook_body_bytes: int = 5 * 1024 * 1024
    max_query_top_k: int = 10

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
    log_format: str = "console"

    @property
    def is_production(self) -> bool:
        """Whether production safety checks should be enforced."""
        return self.app_environment.lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS origins from the comma-separated env var."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Fail fast on unsafe production configuration."""
        if not self.is_production:
            return self

        errors = []
        if not self.api_key:
            errors.append("API_KEY must be set in production")
        if not self.webhook_secret:
            errors.append("WEBHOOK_SECRET must be set in production")
        if "*" in self.cors_origin_list:
            errors.append("CORS_ALLOWED_ORIGINS cannot contain '*' in production")
        if "selectiva_dev" in self.database_url:
            errors.append("DATABASE_URL must not use the default development password in production")
        if self.create_db_on_startup:
            errors.append("CREATE_DB_ON_STARTUP must be false in production; run migrations explicitly")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
