"""MinIO object-storage helpers."""

from __future__ import annotations

from minio import Minio

from terrawatch.config import Settings, get_settings


def minio_client(settings: Settings | None = None) -> Minio:
    config = settings or get_settings()
    return Minio(
        config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=config.minio_secure,
    )


def storage_ready(settings: Settings | None = None) -> tuple[bool, str]:
    config = settings or get_settings()
    try:
        exists = minio_client(config).bucket_exists(config.minio_bucket)
        return exists, config.minio_bucket if exists else "bucket missing"
    except Exception as error:
        return False, type(error).__name__
