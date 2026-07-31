"""Environment-backed service configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "terrawatch"
    run_id: str = "local"
    software_revision: str = "working-tree"
    database_url: str = (
        "postgresql+psycopg://terrawatch:terrawatch@127.0.0.1:15432/terrawatch"
        "?connect_timeout=3&tcp_user_timeout=3000"
    )
    minio_endpoint: str = "127.0.0.1:19000"
    minio_access_key: str = "local-placeholder"
    minio_secret_key: str = "local-placeholder"
    minio_secure: bool = False
    minio_bucket: str = "scenes"
    nats_url: str = "nats://127.0.0.1:14222"
    nats_token: str = "local-placeholder"
    temporal_window_seconds: int = Field(default=900, ge=0, le=86400)
    max_attempts: int = Field(default=5, ge=1, le=20)


@lru_cache
def get_settings() -> Settings:
    return Settings()
