"""Identity-guarded controlled fault injection and recovery."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select

from terractl.environment import artifacts_root, project_root
from terractl.lifecycle import (
    assert_environment_green,
    compose_project,
    run_compose,
)
from terractl.safety import assert_project_identity
from terrawatch.config import get_settings
from terrawatch.constants import TELEMETRY_SUBJECT
from terrawatch.database import OutboxEvent, Scene, session_scope
from terrawatch.messaging import connect
from terrawatch.storage import minio_client

FAULT_NAMES = (
    "postgres-unavailable",
    "minio-unavailable",
    "nats-unavailable",
    "duplicate-event",
    "malformed-raster",
    "stale-catalog-metadata",
    "worker-restart",
)

PAUSE_FAULTS = {
    "postgres-unavailable": "postgres",
    "minio-unavailable": "minio",
    "nats-unavailable": "nats",
}


def fault_state_path() -> Path:
    path = artifacts_root() / "state" / "active-fault.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _docker(*arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        cwd=project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


LIVE_CONTAINER_STATES = frozenset({"running", "paused", "restarting"})


def _container_state(identifier: str) -> str:
    result = _docker("inspect", identifier, "--format", "{{.State.Status}}")
    if result.returncode:
        raise RuntimeError(f"unable to inspect container: {identifier}")
    return result.stdout.strip().lower()


def _service_container_id(service: str) -> str:
    """Resolve the one live container for a service, including a paused one.

    The lookup asks for every container so that a paused target still resolves. Without
    that, clearing a pause fault could not find the container it had just paused, and the
    guarded recovery path would be unusable exactly when it is needed.
    """
    result = run_compose("ps", "-q", "--all", service, timeout=30)
    if result.returncode:
        raise RuntimeError(f"unable to resolve service: {service}")
    candidates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    live = [
        identifier
        for identifier in candidates
        if _container_state(identifier) in LIVE_CONTAINER_STATES
    ]
    if len(live) != 1:
        raise RuntimeError(f"expected exactly one live container for {service}, found {len(live)}")
    identifier = live[0]
    inspect = _docker("inspect", identifier, "--format", "{{json .Config.Labels}}")
    if inspect.returncode:
        raise RuntimeError(f"unable to inspect service: {service}")
    labels = json.loads(inspect.stdout)
    assert_project_identity(labels, compose_project())
    return identifier


def _write_state(state: dict[str, Any]) -> None:
    path = fault_state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def load_fault_state() -> dict[str, Any] | None:
    path = fault_state_path()
    if not path.is_file():
        return None
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


async def _publish_duplicate_event() -> str:
    with session_scope() as session:
        outbox = session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.subject == TELEMETRY_SUBJECT)
            .order_by(OutboxEvent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if outbox is None:
            raise RuntimeError("duplicate-event requires an existing telemetry outbox record")
        payload = json.dumps(outbox.payload, sort_keys=True).encode("utf-8")
        aggregate_id = outbox.aggregate_id
    client = await connect()
    try:
        await client.jetstream().publish(
            TELEMETRY_SUBJECT,
            payload,
            headers={"Nats-Msg-Id": f"fault-duplicate-{uuid4()}"},
        )
    finally:
        await client.drain()
    return aggregate_id


def inject_fault(name: str) -> dict[str, Any]:
    if name not in FAULT_NAMES:
        raise ValueError("unknown fault")
    if load_fault_state() is not None:
        raise RuntimeError("another controlled fault is already active")
    # A resilience drill pauses a service before injecting a fault, so a paused container
    # here is the expected state rather than a broken environment.
    assert_environment_green(allow_paused=True)
    now = datetime.now(UTC).isoformat()
    state: dict[str, Any] = {
        "fault": name,
        "applied_at": now,
        "compose_project": compose_project(),
        "active": False,
    }
    if name in PAUSE_FAULTS:
        service = PAUSE_FAULTS[name]
        identifier = _service_container_id(service)
        # Record the intent before acting. If the process dies mid-fault, the operator
        # still has a record of what was about to change.
        state.update(action="pause", service=service, container_id=identifier)
        _write_state(state)
        result = _docker("pause", identifier)
        if result.returncode:
            fault_state_path().unlink(missing_ok=True)
            raise RuntimeError(result.stderr.strip() or f"unable to pause {service}")
        state["active"] = True
        _write_state(state)
    elif name == "worker-restart":
        identifier = _service_container_id("correlation-worker")
        result = _docker("restart", "--time", "10", identifier, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "unable to restart correlation-worker")
        state.update(action="restart", service="correlation-worker", container_id=identifier)
    elif name == "malformed-raster":
        object_name = f"faults/malformed-{uuid4()}.tif"
        payload = b"synthetic malformed raster fault\n"
        state.update(action="object-create", object_name=object_name)
        _write_state(state)
        minio_client().put_object(
            get_settings().minio_bucket,
            object_name,
            BytesIO(payload),
            len(payload),
            content_type="image/tiff",
        )
        state["active"] = True
        _write_state(state)
    elif name == "stale-catalog-metadata":
        with session_scope() as session:
            scene = session.execute(
                select(Scene)
                .where(Scene.processing_status == "accepted")
                .order_by(Scene.scene_id)
                .limit(1)
            ).scalar_one_or_none()
            if scene is None or scene.width is None:
                raise RuntimeError("stale-catalog-metadata requires an accepted scene")
            scene_id = scene.scene_id
            original_width = scene.width
        state.update(action="metadata-change", scene_id=scene_id, original_width=original_width)
        _write_state(state)
        with session_scope() as session:
            target = session.get(Scene, scene_id)
            if target is None:
                fault_state_path().unlink(missing_ok=True)
                raise RuntimeError("scene disappeared before the fault could be applied")
            target.width = original_width + 1
        state["active"] = True
        _write_state(state)
    elif name == "duplicate-event":
        event_id = asyncio.run(_publish_duplicate_event())
        state.update(action="duplicate-publish", event_id=event_id)
    return state


def clear_faults() -> dict[str, Any]:
    state = load_fault_state()
    if state is None:
        return {"cleared": False, "message": "no active fault"}
    if state.get("compose_project") != compose_project():
        raise RuntimeError("fault state belongs to a different Compose project")
    action = state.get("action")
    if action == "pause":
        service = str(state["service"])
        current_identifier = _service_container_id(service)
        if current_identifier != state.get("container_id"):
            raise RuntimeError("fault target container identity changed")
        # The container may not be paused if the process died between recording the
        # intent and applying it. Clearing has to be safe to run either way.
        if _container_state(current_identifier) == "paused":
            result = _docker("unpause", current_identifier)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or f"unable to unpause {service}")
    elif action == "object-create":
        minio_client().remove_object(
            get_settings().minio_bucket,
            str(state["object_name"]),
        )
    elif action == "metadata-change":
        with session_scope() as session:
            scene = session.get(Scene, str(state["scene_id"]))
            if scene is None:
                raise RuntimeError("faulted scene no longer exists")
            scene.width = int(state["original_width"])
    fault_state_path().unlink(missing_ok=True)
    return {
        "cleared": True,
        "fault": state["fault"],
        "cleared_at": datetime.now(UTC).isoformat(),
    }
