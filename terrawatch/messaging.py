"""NATS JetStream connection, stream setup, and probes."""

from __future__ import annotations

import asyncio

import nats
from nats.aio.client import Client as NATS
from nats.js.api import RetentionPolicy, StorageType, StreamConfig

from terrawatch.config import Settings, get_settings
from terrawatch.constants import (
    CORRELATION_DLQ_SUBJECT,
    IMAGERY_DLQ_SUBJECT,
    IMAGERY_SUBJECT,
    TELEMETRY_SUBJECT,
)

EVENT_STREAM = "TERRAWATCH_EVENTS"
DLQ_STREAM = "TERRAWATCH_DLQ"


async def connect(settings: Settings | None = None) -> NATS:
    config = settings or get_settings()
    return await nats.connect(
        config.nats_url,
        token=config.nats_token,
        connect_timeout=3,
        max_reconnect_attempts=2,
        reconnect_time_wait=0.5,
    )


async def ensure_streams(settings: Settings | None = None) -> None:
    client = await connect(settings)
    try:
        jetstream = client.jetstream()
        for config in (
            StreamConfig(
                name=EVENT_STREAM,
                subjects=[IMAGERY_SUBJECT, TELEMETRY_SUBJECT],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_age=7 * 24 * 60 * 60,
                duplicate_window=120,
            ),
            StreamConfig(
                name=DLQ_STREAM,
                subjects=[IMAGERY_DLQ_SUBJECT, CORRELATION_DLQ_SUBJECT],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_age=30 * 24 * 60 * 60,
            ),
        ):
            stream_name = config.name
            if stream_name is None:
                raise ValueError("stream configuration requires a name")
            try:
                await jetstream.stream_info(stream_name)
                await jetstream.update_stream(config)
            except nats.js.errors.NotFoundError:
                await jetstream.add_stream(config)
    finally:
        await client.drain()


async def messaging_ready(settings: Settings | None = None) -> tuple[bool, str]:
    try:
        client = await connect(settings)
        try:
            info = await client.jetstream().stream_info(EVENT_STREAM)
            return True, info.config.name or EVENT_STREAM
        finally:
            await client.drain()
    except Exception as error:
        return False, type(error).__name__


def setup_main() -> int:
    asyncio.run(ensure_streams())
    print(f"Configured streams: {EVENT_STREAM}, {DLQ_STREAM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(setup_main())
