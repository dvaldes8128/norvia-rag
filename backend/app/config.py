"""Application settings loaded from environment (pydantic-settings)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    # Database
    # The app connects as a NON-superuser role so Row-Level Security actually applies
    # (superusers / BYPASSRLS roles ignore RLS). Migrations use the admin role.
    database_url: str = "postgresql+psycopg://norvia_app:norvia_app@db:5432/norvia"
    admin_database_url: str = "postgresql+psycopg://norvia:norvia@db:5432/norvia"
    app_db_password: str = "norvia_app"

    # Celery / Redis
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # Auth (both API key and JWT)
    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    tenant_api_keys: str = ""  # "tenant:key,tenant2:key2"
    # Platform admin (ops panel). Empty disables /admin/* (401).
    admin_api_key: str = ""

    # Providers
    llm_provider: str = "fake"
    embeddings_provider: str = "fake"
    embeddings_dim: int = 768

    real_llm_base_url: str = ""
    real_llm_api_key: str = ""
    real_llm_model: str = ""
    real_embeddings_base_url: str = ""
    real_embeddings_api_key: str = ""
    real_embeddings_model: str = ""

    provider_timeout_seconds: float = 30.0
    provider_max_retries: int = 3
    provider_backoff_base_seconds: float = 0.5

    # Chunking (D1)
    chunk_size_tokens: int = 900
    chunk_overlap_tokens: int = 150

    # Retrieval
    retrieval_top_k: int = 5
    hybrid_vector_weight: float = 0.6
    hybrid_text_weight: float = 0.4
    # Near-copy fuzzy gate (rapidfuzz token_set_ratio, 0–100). 0 disables.
    retrieval_near_copy_min_ratio: float = 95.0

    # Citation grounding thresholds (B); selection itself is a per-request API param
    citation_min_overlap_tokens: int = 2
    citation_min_overlap_ratio: float = 0.15

    # Uploads (shared volume between API and Celery worker)
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 25

    # OpenTelemetry
    otel_service_name: str = "norvia-rag"
    otel_traces_exporter: str = "console"
    otel_exporter_otlp_endpoint: str = ""

    def api_key_map(self) -> dict[str, str]:
        """Parse TENANT_API_KEYS into {api_key: tenant_id}."""
        out: dict[str, str] = {}
        for pair in self.tenant_api_keys.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            tenant, key = pair.split(":", 1)
            out[key.strip()] = tenant.strip()
        return out


settings = Settings()
