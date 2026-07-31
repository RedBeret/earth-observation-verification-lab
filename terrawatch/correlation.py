"""Durable spatial and temporal correlation worker."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import nats
import structlog
from nats.aio.msg import Msg
from sqlalchemy import func, select

from terractl.safety import redact_text
from terrawatch.config import get_settings
from terrawatch.constants import (
    ALGORITHM_VERSION,
    CORRELATION_DLQ_SUBJECT,
    REQUIREMENTS_VERSION,
    TELEMETRY_SUBJECT,
)
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    DeadLetter,
    ProcessingAttempt,
    Scene,
    TelemetryEventRecord,
    session_scope,
)
from terrawatch.messaging import connect
from terrawatch.retry import backoff_seconds, retry_exhausted
from terrawatch.validation import within_temporal_window

LOGGER = structlog.get_logger(service="correlation-worker")
DURABLE_NAME = "correlation-worker-v1"


def deterministic_correlation_id(
    scene_id: str,
    event_id: str,
    algorithm_version: str = ALGORITHM_VERSION,
) -> str:
    digest = sha256(f"{scene_id}\n{event_id}\n{algorithm_version}".encode()).hexdigest()
    return f"CORR-V1-{digest[:24].upper()}"


def _correlation_status(spatial_match: bool, temporal_match: bool) -> str:
    if not spatial_match:
        return "spatial-non-match"
    if not temporal_match:
        return "temporal-non-match"
    return "matched"


def _event_analysis_status(statuses: list[str]) -> str:
    if "matched" in statuses:
        return "matched"
    if "temporal-non-match" in statuses:
        return "temporal-non-match"
    if "spatial-non-match" in statuses:
        return "spatial-non-match"
    return "no-scenes"


def evaluate_event(event_id: str) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        event = session.get(TelemetryEventRecord, event_id)
        if event is None:
            raise ValueError("telemetry event record not found")
        rows = session.execute(
            select(
                Scene,
                func.ST_Covers(Scene.footprint, event.location).label("spatial_match"),
            ).where(Scene.processing_status == "accepted")
        ).all()
        statuses: list[str] = []
        matched_ids: list[str] = []
        scene_digests: dict[str, str] = {}
        for scene, spatial_value in rows:
            spatial_match = bool(spatial_value)
            temporal_match, temporal_delta = within_temporal_window(
                scene.capture_time,
                event.observed_at,
                settings.temporal_window_seconds,
            )
            status = _correlation_status(spatial_match, temporal_match)
            correlation_id = deterministic_correlation_id(scene.scene_id, event.event_id)
            provenance = {
                "scene_sha256": scene.sha256,
                "software_revision": settings.software_revision,
                "requirements_version": REQUIREMENTS_VERSION,
                "algorithm_version": ALGORITHM_VERSION,
            }
            correlation = session.get(Correlation, correlation_id)
            if correlation is None:
                session.add(
                    Correlation(
                        correlation_id=correlation_id,
                        scene_id=scene.scene_id,
                        event_id=event.event_id,
                        spatial_match=spatial_match,
                        temporal_delta_seconds=temporal_delta,
                        correlation_status=status,
                        algorithm_version=ALGORITHM_VERSION,
                        provenance=provenance,
                    )
                )
            statuses.append(status)
            scene_digests[scene.scene_id] = scene.sha256
            if status == "matched":
                matched_ids.append(correlation_id)

        analysis_status = _event_analysis_status(statuses)
        analysis = session.get(AnalysisResult, (event.event_id, ALGORITHM_VERSION))
        analysis_provenance = {
            "software_revision": settings.software_revision,
            "requirements_version": REQUIREMENTS_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "scene_digests": scene_digests,
            "event_payload_hash": event.payload_hash,
        }
        if analysis is None:
            session.add(
                AnalysisResult(
                    event_id=event.event_id,
                    algorithm_version=ALGORITHM_VERSION,
                    status=analysis_status,
                    evaluated_scenes=len(rows),
                    matched_correlation_ids=matched_ids,
                    details={"correlation_statuses": statuses},
                    provenance=analysis_provenance,
                )
            )
        else:
            analysis.status = analysis_status
            analysis.evaluated_scenes = len(rows)
            analysis.matched_correlation_ids = matched_ids
            analysis.details = {"correlation_statuses": statuses}
            analysis.provenance = analysis_provenance
        event.processing_status = "processed"
        return {
            "event_id": event.event_id,
            "status": analysis_status,
            "evaluated_scenes": len(rows),
            "matched_correlation_ids": matched_ids,
        }


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
                service="correlation-worker",
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
) -> None:
    with session_scope() as session:
        existing = session.execute(
            select(DeadLetter).where(
                DeadLetter.message_id == message_id,
                DeadLetter.service == "correlation-worker",
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DeadLetter(
                    message_id=message_id,
                    service="correlation-worker",
                    subject=CORRELATION_DLQ_SUBJECT,
                    error_type=type(error).__name__,
                    error=redact_text(str(error)),
                    attempts=attempt,
                    payload_hash=sha256(payload).hexdigest(),
                    recoverable=False,
                )
            )


async def _process_message(message: Msg) -> None:
    payload = message.data
    envelope: dict[str, Any] = json.loads(payload)
    message_id = str(envelope["message_id"])
    event_id = str(envelope["payload"]["event_id"])
    attempt = message.metadata.num_delivered if message.metadata else 1
    try:
        result = await asyncio.to_thread(evaluate_event, event_id)
        await asyncio.to_thread(_record_attempt, message_id, attempt, "passed")
        await message.ack()
        LOGGER.info(
            "correlation_completed",
            event_id=event_id,
            attempt=attempt,
            analysis_status=result["status"],
        )
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
                    CORRELATION_DLQ_SUBJECT,
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
                )
            finally:
                await message.ack()
        else:
            await message.nak(delay=backoff_seconds(attempt))
        LOGGER.warning(
            "correlation_failed",
            event_id=event_id,
            attempt=attempt,
            error_type=type(error).__name__,
        )


async def run_correlation_worker(stop: asyncio.Event) -> None:
    client = await connect()
    try:
        subscription = await client.jetstream().pull_subscribe(
            TELEMETRY_SUBJECT,
            durable=DURABLE_NAME,
        )
        LOGGER.info("correlation_consumer_ready", durable=DURABLE_NAME)
        while not stop.is_set():
            try:
                messages = await subscription.fetch(1, timeout=1)
            except (TimeoutError, nats.errors.TimeoutError):
                continue
            for message in messages:
                await _process_message(message)
    finally:
        await client.drain()
