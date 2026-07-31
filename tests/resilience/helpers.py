from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select

from terractl import faults
from terractl.environment import artifacts_root, project_root
from terractl.lifecycle import assert_environment_green
from terrawatch.constants import TELEMETRY_SUBJECT
from terrawatch.correlation import DURABLE_NAME
from terrawatch.database import OutboxEvent
from terrawatch.messaging import DLQ_STREAM, EVENT_STREAM, connect
from tests.support import live_session_factory, live_settings

INGEST_URL = "http://127.0.0.1:18001"
EVENT_URL = "http://127.0.0.1:18002"
ANALYSIS_URL = "http://127.0.0.1:18003"


def wait_until(
    observation: Callable[[], bool],
    *,
    description: str,
    timeout: float = 20,
    interval: float = 0.25,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if observation():
                return
            last_error = None
        except Exception as error:
            last_error = error
        time.sleep(interval)
    suffix = f"; last error: {type(last_error).__name__}" if last_error else ""
    raise AssertionError(f"timed out waiting for {description}{suffix}")


def wait_for_readiness(base_url: str, status_code: int, timeout: float = 20) -> dict[str, Any]:
    observed: dict[str, Any] = {"status_code": "not observed", "body": "not observed"}

    def matches() -> bool:
        try:
            response = httpx.get(f"{base_url}/readyz", timeout=8)
            observed["status_code"] = response.status_code
            observed["body"] = response.json()
            return response.status_code == status_code
        except (httpx.HTTPError, ValueError) as error:
            observed["status_code"] = 0
            observed["body"] = type(error).__name__
            return False

    wait_until(matches, description=f"{base_url} readiness {status_code}", timeout=timeout)
    return observed


def wait_for_green(timeout: float = 30) -> None:
    wait_until(
        _environment_is_green,
        description="all required services to return to a green baseline",
        timeout=timeout,
        interval=0.5,
    )


def _environment_is_green() -> bool:
    try:
        assert_environment_green()
        return True
    except RuntimeError:
        return False


def upload_canonical_scene() -> None:
    root = project_root()
    metadata = json.loads(
        (root / "data" / "valid" / "scene-wgs84.metadata.json").read_text(encoding="utf-8")
    )
    path = root / "data" / "valid" / "scene-wgs84.tif"
    with httpx.Client(base_url=INGEST_URL, timeout=20) as client:
        response = client.post(
            "/v1/scenes",
            data={"metadata": json.dumps(metadata)},
            files={"file": (path.name, path.read_bytes(), "image/tiff")},
        )
    assert response.status_code == 202, response.text


def generated_events() -> list[dict[str, Any]]:
    document = json.loads(
        (project_root() / "data" / "events" / "events.json").read_text(encoding="utf-8")
    )
    return list(document["events"])


def submit_event(event: dict[str, Any], key: str | None = None) -> None:
    idempotency_key = key or f"resilience-{event['event_id'].lower()}"
    with httpx.Client(base_url=EVENT_URL, timeout=20) as client:
        response = client.post(
            "/v1/events",
            json=event,
            headers={"Idempotency-Key": idempotency_key},
        )
    assert response.status_code == 202, response.text


def wait_for_published_events(event_ids: set[str], timeout: float = 20) -> None:
    factory = live_session_factory()

    def published() -> bool:
        with factory() as session:
            rows = (
                session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.subject == TELEMETRY_SUBJECT,
                        OutboxEvent.aggregate_id.in_(event_ids),
                    )
                )
                .scalars()
                .all()
            )
            return len(rows) == len(event_ids) and all(row.published_at is not None for row in rows)

    wait_until(published, description="all telemetry outbox records to publish", timeout=timeout)


def pause_service(service: str) -> str:
    identifier = faults._service_container_id(service)
    result = faults._docker("pause", identifier)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"unable to pause {service}")
    return identifier


def unpause_service(service: str, expected_identifier: str) -> None:
    current_identifier = faults._service_container_id(service)
    if current_identifier != expected_identifier:
        raise RuntimeError(f"refusing to unpause changed {service} container")
    result = faults._docker("unpause", current_identifier)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"unable to unpause {service}")


def container_started_at(service: str) -> str:
    identifier = faults._service_container_id(service)
    result = faults._docker("inspect", identifier, "--format", "{{.State.StartedAt}}")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"unable to inspect {service}")
    return result.stdout.strip()


async def _purge_streams() -> None:
    client = await connect(live_settings())
    try:
        jetstream = client.jetstream()
        await jetstream.purge_stream(EVENT_STREAM)
        await jetstream.purge_stream(DLQ_STREAM)
    finally:
        await client.drain()


def purge_streams() -> None:
    asyncio.run(_purge_streams())


async def _consumer_redeliveries() -> int:
    client = await connect(live_settings())
    try:
        info = await client.jetstream().consumer_info(EVENT_STREAM, DURABLE_NAME)
        return int(info.num_redelivered)
    finally:
        await client.drain()


def consumer_redeliveries() -> int:
    return asyncio.run(_consumer_redeliveries())


async def _stream_messages(stream: str) -> int:
    client = await connect(live_settings())
    try:
        return int((await client.jetstream().stream_info(stream)).state.messages)
    finally:
        await client.drain()


def stream_messages(stream: str) -> int:
    return asyncio.run(_stream_messages(stream))


async def _publish_missing_event(message_id: str) -> None:
    envelope = {
        "schema_version": "1.0.0",
        "message_id": message_id,
        "event_type": "telemetry.accepted",
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "aggregate_id": "EVENT-SYN-MISSING",
        "payload": {
            "event_id": "EVENT-SYN-MISSING",
            "payload_hash": "0" * 64,
        },
    }
    client = await connect(live_settings())
    try:
        await client.jetstream().publish(
            TELEMETRY_SUBJECT,
            json.dumps(envelope, sort_keys=True).encode("utf-8"),
            headers={"Nats-Msg-Id": f"resilience-{uuid4()}"},
        )
    finally:
        await client.drain()


def publish_missing_event(message_id: str) -> None:
    asyncio.run(_publish_missing_event(message_id))


def write_fault_observation(record: dict[str, Any]) -> Path:
    required = {
        "fault",
        "expected",
        "observed",
        "detection",
        "behavior",
        "data_loss",
        "duplicates",
        "recovery",
        "requirements",
        "result",
    }
    missing = required - set(record)
    if missing:
        raise ValueError(f"fault observation is missing fields: {sorted(missing)}")
    if record["result"] != "passed":
        raise ValueError("only passing observed fault results may be recorded")
    run_id = live_settings().run_id
    output = artifacts_root() / "evidence" / run_id
    output.mkdir(parents=True, exist_ok=True)
    path = output / "faults.json"
    existing: dict[str, Any] = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "observations": [],
    }
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    key = (str(record["fault"]), str(record.get("scenario", "default")))
    observations = [
        item
        for item in existing.get("observations", [])
        if (str(item["fault"]), str(item.get("scenario", "default"))) != key
    ]
    observations.append(record)
    payload = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "observations": sorted(
            observations,
            key=lambda item: (str(item["fault"]), str(item.get("scenario", "default"))),
        ),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    if json.loads(path.read_text(encoding="utf-8")) != payload:
        raise RuntimeError("fault evidence read-back did not reconcile")
    return path
