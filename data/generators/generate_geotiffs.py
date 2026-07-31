"""Generate small deterministic valid and invalid GeoTIFF fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin

SEED = 240729
CAPTURE_TIME = "2026-07-29T18:30:00Z"
SCENE_ID = "SCENE-SYN-0001"
WGS84_BBOX = (-120.10, 37.10, -119.90, 37.30)


def _pixels() -> np.ndarray:
    generator = np.random.default_rng(SEED)
    return generator.integers(0, 1000, size=(64, 64), dtype=np.uint16)


def _write_raster(
    path: Path,
    *,
    crs: str | None,
    transform: rasterio.Affine,
    scene_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="uint16",
        crs=crs,
        transform=transform,
        compress="deflate",
        predictor=2,
        tiled=False,
    ) as dataset:
        dataset.write(_pixels(), 1)
        dataset.update_tags(
            AREA_OR_POINT="Area",
            CAPTURE_TIME=CAPTURE_TIME,
            SCENE_ID=scene_id,
            SOURCE="synthetic-generator",
        )


def generate(root: Path) -> dict[str, Path]:
    valid = root / "valid"
    invalid = root / "invalid"
    valid.mkdir(parents=True, exist_ok=True)
    invalid.mkdir(parents=True, exist_ok=True)

    wgs84 = valid / "scene-wgs84.tif"
    _write_raster(
        wgs84,
        crs="EPSG:4326",
        transform=from_bounds(*WGS84_BBOX, width=64, height=64),
        scene_id=SCENE_ID,
    )
    projected = valid / "scene-projected.tif"
    _write_raster(
        projected,
        crs="EPSG:3857",
        transform=from_origin(-13_370_000.0, 4_500_000.0, 30.0, 30.0),
        scene_id="SCENE-SYN-0002",
    )
    no_crs = invalid / "no-crs.tif"
    _write_raster(
        no_crs,
        crs=None,
        transform=from_bounds(*WGS84_BBOX, width=64, height=64),
        scene_id="SCENE-SYN-INVALID-CRS",
    )
    invalid_bounds = invalid / "invalid-bounds.tif"
    _write_raster(
        invalid_bounds,
        crs="EPSG:4326",
        transform=from_bounds(190.0, 10.0, 191.0, 11.0, width=64, height=64),
        scene_id="SCENE-SYN-INVALID-BOUNDS",
    )
    content = wgs84.read_bytes()
    (invalid / "truncated-raster.tif").write_bytes(content[: max(128, len(content) // 4)])

    metadata = {
        "schema_version": "1.0.0",
        "scene_id": SCENE_ID,
        "source": "synthetic-generator",
        "capture_time": CAPTURE_TIME,
        "declared_sha256": None,
    }
    (valid / "scene-wgs84.metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    invalid_metadata = {
        "schema_version": "1.0.0",
        "scene_id": "invalid id",
        "source": "",
        "capture_time": "not-a-time",
        "declared_sha256": "not-a-digest",
    }
    (invalid / "invalid-metadata.json").write_text(
        json.dumps(invalid_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "wgs84": wgs84,
        "projected": projected,
        "no_crs": no_crs,
        "invalid_bounds": invalid_bounds,
        "truncated": invalid / "truncated-raster.tif",
    }
