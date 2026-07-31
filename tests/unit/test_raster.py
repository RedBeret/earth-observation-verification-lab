import json

import pytest

from data.generators.generate_geotiffs import CAPTURE_TIME
from terractl.environment import project_root
from terrawatch.hashing import sha256_file
from terrawatch.models import SceneMetadata
from terrawatch.raster import RasterValidationError, inspect_raster, stac_item

pytestmark = pytest.mark.unit


def test_valid_wgs84_raster_and_stac() -> None:
    root = project_root()
    path = root / "data" / "valid" / "scene-wgs84.tif"
    declared = SceneMetadata(
        scene_id="SCENE-SYN-0001",
        source="synthetic-generator",
        capture_time=CAPTURE_TIME,
    )
    metadata = inspect_raster(path, declared)
    assert metadata.crs == "EPSG:4326"
    assert metadata.width == 64
    assert metadata.height == 64
    assert metadata.bbox == pytest.approx((-120.1, 37.1, -119.9, 37.3))
    digest = sha256_file(path)
    actual = stac_item(
        scene_id=declared.scene_id,
        source=declared.source,
        digest=digest,
        object_name=f"sha256/{digest[:2]}/{digest}.tif",
        metadata=metadata,
    )
    expected = json.loads(
        (root / "data" / "expected" / "stac-scene-syn-0001.json").read_text(encoding="utf-8")
    )
    assert actual == expected


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("no-crs.tif", "missing-crs"),
        ("invalid-bounds.tif", "invalid-bounds"),
        ("truncated-raster.tif", "unreadable-raster"),
    ],
)
def test_negative_rasters(name: str, code: str) -> None:
    path = project_root() / "data" / "invalid" / name
    with pytest.raises(RasterValidationError) as captured:
        inspect_raster(path)
    assert captured.value.code == code


def test_declared_capture_time_mismatch() -> None:
    path = project_root() / "data" / "valid" / "scene-wgs84.tif"
    declared = SceneMetadata(
        scene_id="SCENE-SYN-0001",
        source="synthetic-generator",
        capture_time="2026-07-29T18:31:00Z",
    )
    with pytest.raises(RasterValidationError) as captured:
        inspect_raster(path, declared)
    assert captured.value.code == "capture-time-mismatch"
