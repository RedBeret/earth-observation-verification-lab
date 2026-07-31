"""GeoTIFF inspection, validation, and STAC generation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import rasterio  # type: ignore[import-untyped]
from rasterio.errors import RasterioIOError  # type: ignore[import-untyped]
from rasterio.warp import transform_bounds  # type: ignore[import-untyped]

from terrawatch.models import SceneMetadata
from terrawatch.validation import parse_utc_timestamp, validate_bbox


class RasterValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RasterMetadata:
    crs: str
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    resolution: tuple[float, float]
    capture_time: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_raster(path: Path, declared: SceneMetadata | None = None) -> RasterMetadata:
    try:
        with rasterio.open(path) as dataset:
            if dataset.driver != "GTiff":
                raise RasterValidationError("unsupported-raster", "Raster must be a GeoTIFF.")
            if dataset.crs is None:
                raise RasterValidationError("missing-crs", "Raster has no coordinate system.")
            if dataset.width <= 0 or dataset.height <= 0 or dataset.count <= 0:
                raise RasterValidationError(
                    "invalid-raster-structure", "Raster dimensions and band count must be positive."
                )
            tags = dataset.tags()
            capture_tag = tags.get("CAPTURE_TIME")
            if not capture_tag:
                raise RasterValidationError(
                    "missing-capture-time", "Raster CAPTURE_TIME metadata is required."
                )
            capture = parse_utc_timestamp(capture_tag)
            if declared is not None:
                if capture != declared.capture_time:
                    raise RasterValidationError(
                        "capture-time-mismatch",
                        "Declared capture time does not match the stored raster.",
                    )
                raster_scene_id = tags.get("SCENE_ID")
                if raster_scene_id and raster_scene_id != declared.scene_id:
                    raise RasterValidationError(
                        "scene-id-mismatch",
                        "Declared scene ID does not match the raster metadata.",
                    )

            bounds = dataset.bounds
            if dataset.crs.to_epsg() == 4326:
                wgs84 = (bounds.left, bounds.bottom, bounds.right, bounds.top)
            else:
                wgs84 = transform_bounds(
                    dataset.crs,
                    "EPSG:4326",
                    bounds.left,
                    bounds.bottom,
                    bounds.right,
                    bounds.top,
                    densify_pts=21,
                )
            if not all(math.isfinite(value) for value in wgs84):
                raise RasterValidationError("invalid-bounds", "Raster bounds are not finite.")
            try:
                bbox = validate_bbox(wgs84)
            except ValueError as error:
                raise RasterValidationError("invalid-bounds", str(error)) from error
            return RasterMetadata(
                crs=dataset.crs.to_string(),
                bbox=bbox,
                width=dataset.width,
                height=dataset.height,
                resolution=(abs(dataset.res[0]), abs(dataset.res[1])),
                capture_time=capture.isoformat().replace("+00:00", "Z"),
            )
    except RasterValidationError:
        raise
    except (RasterioIOError, ValueError, OSError) as error:
        raise RasterValidationError("unreadable-raster", "Raster could not be read.") from error


def stac_item(
    *,
    scene_id: str,
    source: str,
    digest: str,
    object_name: str,
    metadata: RasterMetadata,
) -> dict[str, Any]:
    west, south, east, north = metadata.bbox
    epsg = int(metadata.crs.split(":")[-1]) if metadata.crs.startswith("EPSG:") else None
    return {
        "stac_version": "1.0.0",
        "type": "Feature",
        "id": scene_id,
        "bbox": [west, south, east, north],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        },
        "properties": {
            "datetime": metadata.capture_time,
            "source": source,
            "proj:epsg": epsg,
            "proj:shape": [metadata.height, metadata.width],
            "proj:transform": None,
        },
        "assets": {
            "data": {
                "href": f"s3://scenes/{object_name}",
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "checksum:multihash": f"1220{digest}",
            }
        },
        "links": [],
    }
