"""End to end workflow: ingest, correlate, query provenance, then replay everything.

One pass over the nominal path, asserting that a replay of the same scene and the same
event changes no counts and produces no second correlation.

Verifies: ING-002, ING-006, EVT-002, COR-001, COR-005, API-003
"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from terractl.environment import project_root, repository_revision
from terrawatch.correlation import deterministic_correlation_id, evaluate_event
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    OutboxEvent,
    Scene,
    TelemetryEventRecord,
)
from tests.support import (
    live_minio,
    live_session_factory,
    live_settings,
    reset_live_state,
    wait_for_analysis,
    wait_for_scene,
)

pytestmark = pytest.mark.system
INGEST_URL = "http://127.0.0.1:18001"
EVENT_URL = "http://127.0.0.1:18002"
ANALYSIS_URL = "http://127.0.0.1:18003"


@pytest.fixture(autouse=True)
def clean_live_state() -> Iterator[None]:
    reset_live_state()
    yield
    reset_live_state()


def _upload(path: Path, metadata: dict[str, object]) -> httpx.Response:
    with httpx.Client(base_url=INGEST_URL, timeout=20) as client:
        return client.post(
            "/v1/scenes",
            data={"metadata": json.dumps(metadata)},
            files={"file": (path.name, path.read_bytes(), "image/tiff")},
        )


def _submit(event: dict[str, object]) -> httpx.Response:
    with httpx.Client(base_url=EVENT_URL, timeout=20) as client:
        return client.post(
            "/v1/events",
            json=event,
            headers={"Idempotency-Key": "system-inside-key"},
        )


def test_nominal_workflow_provenance_and_replay() -> None:
    root = project_root()
    scene_path = root / "data" / "valid" / "scene-wgs84.tif"
    metadata = json.loads(
        (root / "data" / "valid" / "scene-wgs84.metadata.json").read_text(encoding="utf-8")
    )
    event = json.loads((root / "data" / "events" / "events.json").read_text(encoding="utf-8"))[
        "events"
    ][0]

    accepted_scene = _upload(scene_path, metadata)
    assert accepted_scene.status_code == 202, accepted_scene.text
    scene = wait_for_scene("SCENE-SYN-0001", "accepted")
    accepted_event = _submit(event)
    assert accepted_event.status_code == 202, accepted_event.text
    analysis = wait_for_analysis("EVENT-SYN-INSIDE", "matched")
    assert len(analysis.matched_correlation_ids) == 1

    correlation_id = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-INSIDE")
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        scene_query = client.get("/v1/scenes/SCENE-SYN-0001")
        event_query = client.get("/v1/events/EVENT-SYN-INSIDE")
        correlation_query = client.get(f"/v1/correlations/{correlation_id}")
        provenance = client.get(f"/v1/provenance/correlation/{correlation_id}")
    assert scene_query.status_code == 200
    assert scene_query.json()["sha256"] == scene.sha256
    assert event_query.status_code == 200
    assert correlation_query.status_code == 200
    assert correlation_query.json()["correlation_status"] == "matched"
    assert provenance.json()["scene_sha256"] == scene.sha256
    assert provenance.json()["software_revision"] == repository_revision()
    assert provenance.json()["requirements_version"] == "1.0.0"
    assert provenance.json()["algorithm_version"] == "correlator-1.0.0"

    assert evaluate_event("EVENT-SYN-INSIDE")["status"] == "matched"
    assert evaluate_event("EVENT-SYN-INSIDE")["status"] == "matched"
    replayed_scene = _upload(scene_path, metadata)
    replayed_event = _submit(event)
    assert replayed_scene.status_code == 200
    assert replayed_event.status_code == 200
    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 1
        assert session.query(TelemetryEventRecord).count() == 1
        assert session.query(Correlation).count() == 1
        assert session.query(AnalysisResult).count() == 1
        assert session.query(OutboxEvent).count() == 2
    objects = list(live_minio().list_objects(live_settings().minio_bucket, recursive=True))
    assert len(objects) == 1
