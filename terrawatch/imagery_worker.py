"""Durable imagery-ingestion message consumer."""

from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import nats
import structlog
from geoalchemy2.shape import from_shape
from nats.aio.msg import Msg
from shapely.geometry import box  # type: ignore[import-untyped]
from sqlalchemy import select

from terractl.safety import redact_text
from terrawatch.config import get_settings
from terrawatch.constants import IMAGERY_DLQ_SUBJECT, IMAGERY_SUBJECT
from terrawatch.database import (
    DeadLetter,
    ProcessingAttempt,
    Scene,
    session_scope,
)
from terrawatch.messaging import connect
from terrawatch.models import SceneMetadata
from terrawatch.raster import RasterMetadata, inspect_raster, stac_item
from terrawatch.retry import backoff_seconds, retry_exhausted
from terrawatch.storage import minio_client

LOGGER = structlog.get_logger(service="imagery-worker")
DURABLE_NAME = "imagery-worker-v1"


def _scene_metadata(scene_id: str) -> tuple[SceneMetadata, str, str]:
    with session_scope() as session:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise ValueError("scene record not found")
        return (
            SceneMetadata(
                scene_id=scene.scene_id,
                source=scene.source,
                capture_time=scene.capture_time,
            ),
            scene.sha256,
            scene.storage_uri.removeprefix("s3://scenes/"),
        )


def _complete_scene(
    scene_id: str,
    digest: str,
    object_name: str,
    metadata: RasterMetadata,
) -> None:
    footprint = box(*metadata.bbox)
    with session_scope() as session:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise ValueError("scene record disappeared")
        item = stac_item(
            scene_id=scene_id,
            source=scene.source,
            digest=digest,
            object_name=object_name,
            metadata=metadata,
        )
        scene.crs = metadata.crs
        scene.bbox = list(metadata.bbox)
        scene.footprint = from_shape(footprint, srid=4326)
        scene.width = metadata.width
        scene.height = metadata.height
        scene.resolution = list(metadata.resolution)
        scene.stac_item = item
        scene.processing_status = "accepted"
        scene.processing_error = None


def _record_attempt(
    message_id: str,
    attempt: int,
    status: str,
    error: str | None = None,
) -> None:
    with session_scope() as session:
        session.add(
            ProcessingAttempt(
                message_id=message_id,
                service="imagery-worker",
                attempt=attempt,
                status=status,
                error=redact_text(error) if error else None,
                finished_at=datetime.now(UTC),
            )
        )


def _record_dead_letter(
    message_id: str,
    attempt: int,
    error: Exception,
    payload: bytes,
    scene_id: str | None,
) -> None:
    with session_scope() as session:
        existing = session.execute(
            select(DeadLetter).where(
                DeadLetter.message_id == message_id,
                DeadLetter.service == "imagery-worker",
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DeadLetter(
                    message_id=message_id,
                    service="imagery-worker",
                    subject=IMAGERY_DLQ_SUBJECT,
                    error_type=type(error).__name__,
                    error=redact_text(str(error)),
                    attempts=attempt,
                    payload_hash=sha256(payload).hexdigest(),
                    recoverable=False,
                )
            )
        if scene_id:
            scene = session.get(Scene, scene_id)
            if scene is not None:
                scene.processing_status = "rejected"
                scene.processing_error = redact_text(type(error).__name__)


async def _process_message(message: Msg) -> None:
    payload = message.data
    envelope: dict[str, Any] = json.loads(payload)
    message_id = str(envelope["message_id"])
    scene_id = str(envelope["payload"]["scene_id"])
    attempt = message.metadata.num_delivered if message.metadata else 1
    path: Path | None = None
    try:
        declared, expected_digest, object_name = await asyncio.to_thread(_scene_metadata, scene_id)
        with tempfile.NamedTemporaryFile(
            prefix="terrawatch-worker-", suffix=".tif", delete=False
        ) as temp:
            path = Path(temp.name)
        await asyncio.to_thread(
            minio_client().fget_object,
            get_settings().minio_bucket,
            object_name,
            str(path),
        )
        actual_digest = sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError("stored object digest does not match the scene record")
        raster_metadata = await asyncio.to_thread(inspect_raster, path, declared)
        await asyncio.to_thread(
            _complete_scene,
            scene_id,
            expected_digest,
            object_name,
            raster_metadata,
        )
        await asyncio.to_thread(_record_attempt, message_id, attempt, "passed")
        await message.ack()
        LOGGER.info("imagery_processed", scene_id=scene_id, attempt=attempt)
    except Exception as error:
        with suppress(Exception):
            await asyncio.to_thread(
                _record_attempt,
                message_id,
                attempt,
                "failed",
                type(error).__name__,
            )
        if retry_exhausted(attempt, get_settings().max_attempts):
            client = await connect()
            try:
                await client.jetstream().publish(
                    IMAGERY_DLQ_SUBJECT,
                    payload,
                    headers={"Nats-Msg-Id": f"dlq-{message_id}"},
                )
            finally:
                await client.drain()
            try:
                await asyncio.to_thread(
                    _record_dead_letter,
                    message_id,
                    attempt,
                    error,
                    payload,
                    scene_id,
                )
            finally:
                await message.ack()
        else:
            delay = backoff_seconds(attempt)
            await message.nak(delay=delay)
        LOGGER.warning(
            "imagery_processing_failed",
            scene_id=scene_id,
            attempt=attempt,
            error_type=type(error).__name__,
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def run_imagery_worker(stop: asyncio.Event) -> None:
    client = await connect()
    try:
        subscription = await client.jetstream().pull_subscribe(
            IMAGERY_SUBJECT,
            durable=DURABLE_NAME,
        )
        LOGGER.info("imagery_consumer_ready", durable=DURABLE_NAME)
        while not stop.is_set():
            try:
                messages = await subscription.fetch(1, timeout=1)
            except (TimeoutError, nats.errors.TimeoutError):
                continue
            for message in messages:
                await _process_message(message)
    finally:
        await client.drain()
