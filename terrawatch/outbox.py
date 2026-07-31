"""At-least-once transactional outbox dispatcher."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from terractl.safety import redact_text
from terrawatch.database import OutboxEvent, session_scope
from terrawatch.messaging import connect


def pending_outbox(limit: int = 25) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "subject": row.subject,
                "payload": row.payload,
            }
            for row in rows
        ]


def mark_published(identifier: UUID) -> None:
    with session_scope() as session:
        row = session.get(OutboxEvent, identifier)
        if row is not None:
            row.published_at = datetime.now(UTC)
            row.last_error = None


def mark_failed(identifier: UUID, error: Exception) -> None:
    with session_scope() as session:
        row = session.get(OutboxEvent, identifier)
        if row is not None:
            row.attempts += 1
            row.last_error = redact_text(type(error).__name__)


async def publish_pending(limit: int = 25) -> int:
    rows = await asyncio.to_thread(pending_outbox, limit)
    if not rows:
        return 0
    client = await connect()
    published = 0
    try:
        jetstream = client.jetstream()
        for row in rows:
            identifier = row["id"]
            try:
                payload = json.dumps(row["payload"], sort_keys=True).encode("utf-8")
                await jetstream.publish(
                    row["subject"],
                    payload,
                    headers={"Nats-Msg-Id": str(identifier)},
                )
                await asyncio.to_thread(mark_published, identifier)
                published += 1
            except Exception as error:
                await asyncio.to_thread(mark_failed, identifier, error)
    finally:
        await client.drain()
    return published


async def outbox_loop(stop: asyncio.Event, interval_seconds: float = 1.0) -> None:
    logger = structlog.get_logger(component="outbox")
    while not stop.is_set():
        try:
            published = await publish_pending()
            if published:
                logger.info("outbox_published", count=published)
        except Exception as error:
            logger.warning("outbox_unavailable", error_type=type(error).__name__)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
