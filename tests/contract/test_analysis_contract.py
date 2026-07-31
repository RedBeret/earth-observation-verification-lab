import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from terractl.environment import project_root
from terrawatch.correlation import deterministic_correlation_id
from terrawatch.database import AnalysisResult, Correlation, Scene, TelemetryEventRecord
from tests.support import (
    live_session_factory,
    reset_live_state,
    wait_for_analysis,
    wait_for_scene,
)

pytestmark = pytest.mark.contract
INGEST_URL = "http://127.0.0.1:18001"
EVENT_URL = "http://127.0.0.1:18002"
ANALYSIS_URL = "http://127.0.0.1:18003"


def _upload_scene(path: Path, metadata: dict[str, object]) -> httpx.Response:
    with httpx.Client(base_url=INGEST_URL, timeout=20) as client:
        return client.post(
            "/v1/scenes",
            data={"metadata": json.dumps(metadata)},
            files={"file": (path.name, path.read_bytes(), "image/tiff")},
        )


def _submit_event(payload: dict[str, object]) -> httpx.Response:
    with httpx.Client(base_url=EVENT_URL, timeout=20) as client:
        return client.post(
            "/v1/events",
            json=payload,
            headers={"Idempotency-Key": f"key-{payload['event_id']}"},
        )


@pytest.fixture()
def correlated_workflow() -> Iterator[dict[str, str]]:
    reset_live_state()
    root = project_root()
    metadata = json.loads(
        (root / "data" / "valid" / "scene-wgs84.metadata.json").read_text(encoding="utf-8")
    )
    accepted = _upload_scene(root / "data" / "valid" / "scene-wgs84.tif", metadata)
    assert accepted.status_code == 202, accepted.text
    wait_for_scene("SCENE-SYN-0001", "accepted")
    document = json.loads((root / "data" / "events" / "events.json").read_text(encoding="utf-8"))
    expected_document = json.loads(
        (root / "data" / "expected" / "correlations.json").read_text(encoding="utf-8")
    )
    expected = {
        result["event_id"]: result["expected_status"] for result in expected_document["results"]
    }
    for event in document["events"]:
        response = _submit_event(event)
        assert response.status_code == 202, response.text
    for event_id, status in expected.items():
        wait_for_analysis(event_id, status)
    yield expected
    reset_live_state()


def _assert_error(response: httpx.Response, code: str) -> None:
    assert response.status_code in {404, 422}
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["details"] == {}
    UUID(body["error"]["request_id"])


def test_expected_spatial_and_temporal_matrix(
    correlated_workflow: dict[str, str],
) -> None:
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        for event_id, expected_status in correlated_workflow.items():
            result = client.get(f"/v1/analysis-results/{event_id}")
            assert result.status_code == 200, result.text
            assert result.json()["status"] == expected_status
            assert result.json()["evaluated_scenes"] == 1
            correlation_id = deterministic_correlation_id("SCENE-SYN-0001", event_id)
            correlation = client.get(f"/v1/correlations/{correlation_id}")
            assert correlation.status_code == 200, correlation.text
            assert correlation.json()["correlation_status"] == expected_status

        boundary_id = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-BOUNDARY")
        boundary = client.get(f"/v1/correlations/{boundary_id}").json()
        assert boundary["spatial_match"] is True
        for event_id in ("EVENT-SYN-WINDOW-START", "EVENT-SYN-WINDOW-END"):
            endpoint_id = deterministic_correlation_id("SCENE-SYN-0001", event_id)
            endpoint = client.get(f"/v1/correlations/{endpoint_id}").json()
            assert endpoint["temporal_delta_seconds"] == 900
            assert endpoint["correlation_status"] == "matched"


def test_scene_event_search_and_pagination(correlated_workflow: dict[str, str]) -> None:
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        scenes = client.get(
            "/v1/scenes",
            params={
                "bbox": "-120.1,37.1,-119.9,37.3",
                "start": "2026-07-29T18:30:00Z",
                "end": "2026-07-29T18:30:00Z",
            },
        )
        assert scenes.status_code == 200, scenes.text
        assert scenes.json()["total"] == 1
        assert scenes.json()["items"][0]["scene_id"] == "SCENE-SYN-0001"

        spatial_events = client.get(
            "/v1/events",
            params={"bbox": "-120.1,37.1,-119.9,37.3", "page": "1", "page_size": "3"},
        )
        assert spatial_events.status_code == 200, spatial_events.text
        assert spatial_events.json()["total"] == 6
        assert len(spatial_events.json()["items"]) == 3

        combined = client.get(
            "/v1/events",
            params={
                "bbox": "-120.1,37.1,-119.9,37.3",
                "start": "2026-07-29T18:15:00Z",
                "end": "2026-07-29T18:45:00Z",
            },
        )
        assert combined.status_code == 200, combined.text
        assert combined.json()["total"] == 4


@pytest.mark.parametrize(
    ("path", "params", "code"),
    [
        ("/v1/scenes", {"bbox": "-119,37,-120,38"}, "invalid-bbox"),
        (
            "/v1/events",
            {
                "start": "2026-07-29T18:31:00Z",
                "end": "2026-07-29T18:30:00Z",
            },
            "invalid-time-range",
        ),
    ],
)
def test_invalid_filters_never_succeed_empty(
    path: str,
    params: dict[str, str],
    code: str,
) -> None:
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        response = client.get(path, params=params)
    _assert_error(response, code)


def test_unknown_resources_use_common_errors() -> None:
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        _assert_error(client.get("/v1/scenes/SCENE-SYN-MISSING"), "scene-not-found")
        _assert_error(client.get("/v1/events/EVENT-SYN-MISSING"), "event-not-found")
        _assert_error(
            client.get("/v1/correlations/CORR-SYN-MISSING"),
            "correlation-not-found",
        )
        _assert_error(
            client.get("/v1/analysis-results/EVENT-SYN-MISSING"),
            "analysis-result-not-found",
        )


def test_provenance_and_database_counts(correlated_workflow: dict[str, str]) -> None:
    correlation_id = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-INSIDE")
    with httpx.Client(base_url=ANALYSIS_URL, timeout=20) as client:
        scene_provenance = client.get("/v1/provenance/scene/SCENE-SYN-0001")
        correlation_provenance = client.get(f"/v1/provenance/correlation/{correlation_id}")
        analysis_provenance = client.get("/v1/provenance/analysis-result/EVENT-SYN-INSIDE")
    assert scene_provenance.status_code == 200
    assert len(scene_provenance.json()["scene_sha256"]) == 64
    assert correlation_provenance.status_code == 200
    assert correlation_provenance.json()["algorithm_version"] == "correlator-1.0.0"
    assert analysis_provenance.status_code == 200
    assert len(analysis_provenance.json()["event_payload_hash"]) == 64

    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 1
        assert session.query(TelemetryEventRecord).count() == 7
        assert session.query(Correlation).count() == 7
        assert session.query(AnalysisResult).count() == 7
