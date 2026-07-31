"""MinIO object-storage helpers."""

from __future__ import annotations

import urllib3
from minio import Minio

from terrawatch.config import Settings, get_settings


def minio_client(settings: Settings | None = None) -> Minio:
    config = settings or get_settings()
    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=2.0, read=2.0),
        retries=False,
    )
    return Minio(
        config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=config.minio_secure,
        http_client=http_client,
    )


def storage_ready(settings: Settings | None = None) -> tuple[bool, str]:
    config = settings or get_settings()
    try:
        exists = minio_client(config).bucket_exists(config.minio_bucket)
        return exists, config.minio_bucket if exists else "bucket missing"
    except Exception as error:
        return False, type(error).__name__
