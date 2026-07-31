"""Versioned telemetry ingestion with transactional idempotency."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from geoalchemy2.shape import from_shape
from pydantic import ValidationError
from shapely.geometry import Point  # type: ignore[import-untyped]
from sqlalchemy import or_, select

from terrawatch.api import api_error_response
from terrawatch.config import get_settings
from terrawatch.constants import TELEMETRY_SUBJECT
from terrawatch.database import OutboxEvent, TelemetryEventRecord, session_scope
from terrawatch.models import TelemetryEvent
from terrawatch.outbox import outbox_loop, publish_pending

LOGGER = structlog.get_logger(service="event-api")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def canonical_event_payload(event: TelemetryEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def event_payload_hash(event: TelemetryEvent) -> str:
    encoded = json.dumps(
        canonical_event_payload(event),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _existing_events(
    event_id: str,
    idempotency_key: str,
) -> tuple[TelemetryEventRecord | None, TelemetryEventRecord | None]:
    with session_scope() as session:
        events = (
            session.execute(
                select(TelemetryEventRecord).where(
                    or_(
                        TelemetryEventRecord.event_id == event_id,
                        TelemetryEventRecord.idempotency_key == idempotency_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = next((event for event in events if event.event_id == event_id), None)
        by_key = next(
            (event for event in events if event.idempotency_key == idempotency_key),
            None,
        )
        return by_id, by_key


def _event_response(event: TelemetryEventRecord, replayed: bool) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "payload_hash": event.payload_hash,
        "processing_status": event.processing_status,
        "replayed": replayed,
    }


def _persist_event(
    event: TelemetryEvent,
    idempotency_key: str,
    payload_hash: str,
) -> TelemetryEventRecord:
    now = datetime.now(UTC)
    message_id = uuid4()
    longitude, latitude = event.location.coordinates
    record = TelemetryEventRecord(
        event_id=event.event_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        event_type=event.event_type,
        observed_at=event.observed_at,
        location=from_shape(Point(longitude, latitude), srid=4326),
        confidence=event.confidence,
        source=event.source,
        attributes=event.attributes,
        processing_status="accepted",
    )
    envelope = {
        "schema_version": "1.0.0",
        "message_id": str(message_id),
        "event_type": "telemetry.accepted",
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "aggregate_id": event.event_id,
        "payload": {
            "event_id": event.event_id,
            "payload_hash": payload_hash,
        },
    }
    with session_scope() as session:
        session.add(record)
        session.add(
            OutboxEvent(
                id=message_id,
                aggregate_type="telemetry-event",
                aggregate_id=event.event_id,
                subject=TELEMETRY_SUBJECT,
                payload=envelope,
            )
        )
    return record


def _event_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    LOGGER.info(
        "event_rejected",
        request_id=getattr(request.state, "request_id", "not-observed"),
        run_id=get_settings().run_id,
        status_code=status_code,
        error_code=code,
    )
    return api_error_response(request, status_code, code, message)


def register_event_routes(app: FastAPI) -> None:
    @app.on_event("startup")
    async def start_outbox() -> None:
        stop = asyncio.Event()
        app.state.outbox_stop = stop
        app.state.outbox_task = asyncio.create_task(outbox_loop(stop))

    @app.on_event("shutdown")
    async def stop_outbox() -> None:
        app.state.outbox_stop.set()
        await app.state.outbox_task

    @app.post("/v1/events")
    async def ingest_event(request: Request) -> JSONResponse:
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key is None or not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            return _event_error(
                request,
                422,
                "invalid-idempotency-key",
                "Idempotency-Key must contain 1 to 128 safe characters.",
            )
        try:
            raw_payload = await request.json()
            if not isinstance(raw_payload, dict):
                raise ValueError("event payload must be an object")
            event = TelemetryEvent.model_validate(raw_payload)
        except (ValidationError, ValueError, json.JSONDecodeError):
            return _event_error(
                request,
                422,
                "invalid-event",
                "Telemetry event is invalid.",
            )

        payload_hash = event_payload_hash(event)
        by_id, by_key = await asyncio.to_thread(
            _existing_events,
            event.event_id,
            idempotency_key,
        )
        exact = (
            by_id is not None
            and by_key is not None
            and by_id.event_id == by_key.event_id
            and by_id.payload_hash == payload_hash
        )
        if exact:
            assert by_id is not None
            return JSONResponse(status_code=200, content=_event_response(by_id, replayed=True))
        if by_key is not None:
            return _event_error(
                request,
                409,
                "idempotency-key-conflict",
                "Idempotency-Key already identifies a different event.",
            )
        if by_id is not None:
            return _event_error(
                request,
                409,
                "event-id-conflict",
                "Event ID already identifies a different submission.",
            )
        try:
            record = await asyncio.to_thread(
                _persist_event,
                event,
                idempotency_key,
                payload_hash,
            )
            try:
                await publish_pending()
            except Exception as error:
                LOGGER.warning("event_outbox_deferred", error_type=type(error).__name__)
            return JSONResponse(status_code=202, content=_event_response(record, replayed=False))
        except Exception as error:
            LOGGER.error("event_ingest_failed", error_type=type(error).__name__)
            return _event_error(
                request,
                500,
                "event-ingest-failed",
                f"Event ingestion failed: {type(error).__name__}",
            )
