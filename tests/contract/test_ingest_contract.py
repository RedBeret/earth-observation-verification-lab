import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import rasterio

from terractl.environment import project_root
from terrawatch.database import OutboxEvent, Scene
from tests.support import (
    live_minio,
    live_session_factory,
    live_settings,
    reset_live_state,
    wait_for_processing_attempt,
    wait_for_scene,
)

pytestmark = pytest.mark.contract
BASE_URL = "http://127.0.0.1:18001"


@pytest.fixture(autouse=True)
def clean_live_state():
    reset_live_state()
    yield
    reset_live_state()


def _metadata(scene_id: str = "SCENE-SYN-0001", **updates) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "scene_id": scene_id,
        "source": "synthetic-generator",
        "capture_time": "2026-07-29T18:30:00Z",
        "declared_sha256": None,
    }
    payload.update(updates)
    return payload


def _upload(path: Path, metadata: dict[str, object], filename: str | None = None):
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        return client.post(
            "/v1/scenes",
            data={"metadata": json.dumps(metadata)},
            files={
                "file": (
                    filename or path.name,
                    path.read_bytes(),
                    "image/tiff",
                )
            },
        )


def _assert_no_state() -> None:
    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 0
    assert list(live_minio().list_objects(live_settings().minio_bucket, recursive=True)) == []


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["details"] == {}
    UUID(body["error"]["request_id"])
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def test_valid_scene_upload_worker_and_replay() -> None:
    root = project_root()
    path = root / "data" / "valid" / "scene-wgs84.tif"
    response = _upload(path, _metadata())
    assert response.status_code == 202, response.text
    assert response.json()["replayed"] is False
    scene = wait_for_scene("SCENE-SYN-0001", "accepted")
    assert scene.stac_item == json.loads(
        (root / "data" / "expected" / "stac-scene-syn-0001.json").read_text(encoding="utf-8")
    )
    objects = list(live_minio().list_objects(live_settings().minio_bucket, recursive=True))
    assert len(objects) == 1
    assert scene.sha256 in objects[0].object_name
    assert scene.footprint is not None
    assert (scene.width, scene.height) == (64, 64)
    factory = live_session_factory()
    with factory() as session:
        outbox = session.query(OutboxEvent).one()
        assert outbox.published_at is not None
        message_id = str(outbox.id)
    attempt = wait_for_processing_attempt(message_id, "passed")
    assert attempt.service == "imagery-worker"
    assert attempt.attempt == 1

    replay = _upload(path, _metadata())
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    with factory() as session:
        assert session.query(Scene).count() == 1
        assert session.query(OutboxEvent).count() == 1
    assert len(list(live_minio().list_objects(live_settings().minio_bucket, recursive=True))) == 1


@pytest.mark.parametrize(
    ("relative_path", "scene_id", "expected_code"),
    [
        ("data/invalid/truncated-raster.tif", "SCENE-SYN-TRUNCATED", "unreadable-raster"),
        ("data/invalid/no-crs.tif", "SCENE-SYN-INVALID-CRS", "missing-crs"),
        (
            "data/invalid/invalid-bounds.tif",
            "SCENE-SYN-INVALID-BOUNDS",
            "invalid-bounds",
        ),
    ],
)
def test_invalid_raster_rejection(relative_path: str, scene_id: str, expected_code: str) -> None:
    response = _upload(project_root() / relative_path, _metadata(scene_id))
    _assert_error(response, 422, expected_code)
    _assert_no_state()


def test_invalid_metadata_rejection() -> None:
    response = _upload(
        project_root() / "data" / "valid" / "scene-wgs84.tif",
        {"schema_version": "1.0.0", "scene_id": "invalid"},
    )
    _assert_error(response, 422, "invalid-scene-metadata")
    _assert_no_state()


def test_checksum_mismatch_rejection() -> None:
    response = _upload(
        project_root() / "data" / "valid" / "scene-wgs84.tif",
        _metadata(declared_sha256="0" * 64),
    )
    _assert_error(response, 422, "checksum-mismatch")
    _assert_no_state()


def test_unsupported_file_rejection() -> None:
    response = _upload(
        project_root() / "README.md",
        _metadata(),
        filename="not-a-raster.txt",
    )
    _assert_error(response, 415, "unsupported-media-type")
    _assert_no_state()


def test_scene_id_conflict() -> None:
    root = project_root()
    accepted = _upload(root / "data" / "valid" / "scene-wgs84.tif", _metadata())
    assert accepted.status_code == 202
    wait_for_scene("SCENE-SYN-0001", "accepted")
    conflict = _upload(
        root / "data" / "valid" / "scene-projected.tif",
        _metadata(),
    )
    _assert_error(conflict, 409, "scene-id-conflict")
    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 1
        original = session.get(Scene, "SCENE-SYN-0001")
        assert original is not None
        assert original.processing_status == "accepted"
    objects = list(live_minio().list_objects(live_settings().minio_bucket, recursive=True))
    assert len(objects) == 1


def test_same_digest_different_external_id_replays_canonical_scene() -> None:
    root = project_root()
    path = root / "data" / "valid" / "scene-wgs84.tif"
    assert _upload(path, _metadata()).status_code == 202
    wait_for_scene("SCENE-SYN-0001", "accepted")
    replay = _upload(path, _metadata("SCENE-SYN-ALIAS"))
    assert replay.status_code == 200
    assert replay.json()["scene_id"] == "SCENE-SYN-0001"
    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 1


def test_changed_content_with_matching_raster_scene_id_conflicts(tmp_path: Path) -> None:
    root = project_root()
    original = root / "data" / "valid" / "scene-wgs84.tif"
    assert _upload(original, _metadata()).status_code == 202
    wait_for_scene("SCENE-SYN-0001", "accepted")
    changed = tmp_path / "changed.tif"
    with rasterio.open(original) as source:
        profile = source.profile
        pixels = source.read(1)
        tags = source.tags()
    pixels[0, 0] += 1
    with rasterio.open(changed, "w", **profile) as destination:
        destination.write(pixels, 1)
        destination.update_tags(**tags)
    response = _upload(changed, _metadata())
    _assert_error(response, 409, "scene-id-conflict")
    factory = live_session_factory()
    with factory() as session:
        assert session.query(Scene).count() == 1
    assert len(list(live_minio().list_objects(live_settings().minio_bucket, recursive=True))) == 1
