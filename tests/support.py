"""Shared live-system test helpers."""

from __future__ import annotations

import time
from collections.abc import Iterator

from minio import Minio
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from terractl.environment import project_root
from terrawatch.config import Settings
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    DeadLetter,
    OutboxEvent,
    ProcessingAttempt,
    Scene,
    TelemetryEventRecord,
    create_session_factory,
)


def live_settings() -> Settings:
    return Settings(_env_file=project_root() / ".env.local")


def live_session_factory() -> sessionmaker[Session]:
    return create_session_factory(live_settings().database_url)


def live_minio() -> Minio:
    settings = live_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def reset_live_state() -> None:
    factory = live_session_factory()
    with factory.begin() as session:
        for model in (
            DeadLetter,
            ProcessingAttempt,
            AnalysisResult,
            Correlation,
            OutboxEvent,
            TelemetryEventRecord,
            Scene,
        ):
            session.execute(delete(model))
    client = live_minio()
    bucket = live_settings().minio_bucket
    for object_info in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, object_info.object_name)


def wait_for_scene(scene_id: str, status: str, timeout: float = 20) -> Scene:
    deadline = time.monotonic() + timeout
    factory = live_session_factory()
    while time.monotonic() < deadline:
        with factory() as session:
            scene = session.get(Scene, scene_id)
            if scene is not None and scene.processing_status == status:
                session.expunge(scene)
                return scene
        time.sleep(0.25)
    raise AssertionError(f"scene {scene_id} did not reach {status}")


def wait_for_processing_attempt(
    message_id: str,
    status: str,
    timeout: float = 20,
) -> ProcessingAttempt:
    deadline = time.monotonic() + timeout
    factory = live_session_factory()
    while time.monotonic() < deadline:
        with factory() as session:
            attempt = (
                session.query(ProcessingAttempt)
                .filter_by(message_id=message_id, status=status)
                .one_or_none()
            )
            if attempt is not None:
                session.expunge(attempt)
                return attempt
        time.sleep(0.25)
    raise AssertionError(f"message {message_id} did not record a {status} attempt")


def scene_rows() -> Iterator[Scene]:
    factory = live_session_factory()
    with factory() as session:
        rows = list(session.query(Scene).all())
        for row in rows:
            session.expunge(row)
            yield row
