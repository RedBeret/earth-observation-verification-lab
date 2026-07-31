"""Docker isolation survey and independently labeled sentinel proof."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from terractl.diagnostics import collect_failure_diagnostics
from terractl.environment import artifacts_root, project_root
from terractl.lifecycle import assert_environment_green, compose_down, compose_project
from terrawatch.constants import PROJECT_LABEL, PROJECT_LABEL_VALUE

SENTINEL_LABEL = "org.northstar.verification-sentinel"
SENTINEL_PROJECT = "earth-observation-verification-sentinel"


@dataclass(frozen=True)
class ContainerSnapshot:
    identifier: str
    name: str
    status: str
    labels: dict[str, str]


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


def survey_containers() -> list[ContainerSnapshot]:
    listed = _docker("ps", "-a", "-q")
    if listed.returncode:
        raise RuntimeError(listed.stderr.strip() or "unable to survey Docker containers")
    snapshots: list[ContainerSnapshot] = []
    for identifier in listed.stdout.splitlines():
        inspected = _docker("inspect", identifier)
        if inspected.returncode:
            raise RuntimeError(f"unable to inspect container {identifier}")
        document = json.loads(inspected.stdout)[0]
        snapshots.append(
            ContainerSnapshot(
                identifier=str(document["Id"]),
                name=str(document["Name"]).removeprefix("/"),
                status=str(document["State"]["Status"]),
                labels={
                    str(key): str(value)
                    for key, value in (document["Config"].get("Labels") or {}).items()
                },
            )
        )
    return snapshots


def _is_project_container(snapshot: ContainerSnapshot) -> bool:
    return (
        snapshot.labels.get(PROJECT_LABEL) == PROJECT_LABEL_VALUE
        and snapshot.labels.get("com.docker.compose.project") == compose_project()
    )


def _fingerprint(snapshot: ContainerSnapshot) -> str:
    return sha256(
        json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def create_sentinel() -> ContainerSnapshot:
    sentinel_id = str(uuid4())
    name = f"terrawatch-verification-sentinel-{sentinel_id[:8]}"
    result = _docker(
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--label",
        f"{PROJECT_LABEL}={SENTINEL_PROJECT}",
        "--label",
        f"{SENTINEL_LABEL}={sentinel_id}",
        "--entrypoint",
        "/bin/sleep",
        "nats:2.11.4-alpine",
        "300",
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "unable to create verification sentinel")
    identifier = result.stdout.strip()
    snapshot = next(
        (item for item in survey_containers() if item.identifier.startswith(identifier)),
        None,
    )
    if snapshot is None or snapshot.labels.get(SENTINEL_LABEL) != sentinel_id:
        raise RuntimeError("verification sentinel identity could not be confirmed")
    return snapshot


def remove_sentinel(snapshot: ContainerSnapshot) -> None:
    current = next(
        (item for item in survey_containers() if item.identifier == snapshot.identifier),
        None,
    )
    if current is None:
        return
    if current.labels.get(SENTINEL_LABEL) != snapshot.labels.get(SENTINEL_LABEL):
        raise RuntimeError("refusing to remove a changed sentinel identity")
    result = _docker("rm", "--force", snapshot.identifier)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "unable to remove verification sentinel")


def _write_evidence(run_id: str, payload: dict[str, Any]) -> Path:
    output = artifacts_root() / "evidence" / run_id
    output.mkdir(parents=True, exist_ok=True)
    path = output / "clean-room.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def clean_room_proof(*, create_verification_sentinel: bool = False) -> Path:
    assert_environment_green()
    started = datetime.now(UTC)
    initial = survey_containers()
    sentinel: ContainerSnapshot | None = None
    evidence_path: Path | None = None
    try:
        if create_verification_sentinel:
            sentinel = create_sentinel()
        before = survey_containers()
        initial_project_ids = {item.identifier for item in initial if _is_project_container(item)}
        project_before = [item for item in before if _is_project_container(item)]
        if {item.identifier for item in project_before} != initial_project_ids:
            raise RuntimeError("project container identity changed during clean-room setup")
        neighbors = [item for item in before if not _is_project_container(item)]
        if not neighbors:
            raise RuntimeError(
                "clean-room proof refuses teardown without an unrelated neighboring container"
            )
        neighbor_fingerprints = {item.identifier: _fingerprint(item) for item in neighbors}
        down_code = compose_down()
        if down_code:
            raise RuntimeError("identity-guarded project teardown failed")
        after = survey_containers()
        if any(_is_project_container(item) for item in after):
            raise RuntimeError("project containers survived clean-room teardown")
        after_by_id = {item.identifier: item for item in after}
        unchanged = all(
            identifier in after_by_id and _fingerprint(after_by_id[identifier]) == fingerprint
            for identifier, fingerprint in neighbor_fingerprints.items()
        )
        if not unchanged:
            raise RuntimeError("an unrelated neighboring container changed during teardown")
        payload: dict[str, Any] = {
            "run_id": started.strftime("%Y%m%dT%H%M%SZ-clean-room"),
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "compose_project": compose_project(),
            "project_containers_before": len(project_before),
            "project_containers_after": 0,
            "unrelated_neighbors_observed": len(neighbors),
            "neighbor_fingerprints_unchanged": True,
            "sentinel_id": sentinel.identifier if sentinel is not None else None,
            "sentinel_fingerprint": _fingerprint(sentinel) if sentinel is not None else None,
            "sentinel_removed": False,
            "result": "passed",
        }
        evidence_path = _write_evidence(str(payload["run_id"]), payload)
        return evidence_path
    except Exception:
        collect_failure_diagnostics("clean-room")
        raise
    finally:
        if sentinel is not None:
            remove_sentinel(sentinel)
            if evidence_path is not None and evidence_path.is_file():
                payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                payload["sentinel_removed"] = True
                evidence_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
