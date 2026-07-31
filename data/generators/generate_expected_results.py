"""Generate all canonical inputs and expected semantic results."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from data.generators.generate_events import generate as generate_events
from data.generators.generate_geotiffs import CAPTURE_TIME, SCENE_ID, WGS84_BBOX
from data.generators.generate_geotiffs import generate as generate_geotiffs


def _expected_stac(asset_hash: str) -> dict[str, object]:
    west, south, east, north = WGS84_BBOX
    return {
        "stac_version": "1.0.0",
        "type": "Feature",
        "id": SCENE_ID,
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
            "datetime": CAPTURE_TIME,
            "source": "synthetic-generator",
            "proj:epsg": 4326,
        },
        "assets": {
            "data": {
                "href": f"s3://scenes/sha256/{asset_hash[:2]}/{asset_hash}.tif",
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "checksum:multihash": f"1220{asset_hash}",
            }
        },
        "links": [],
    }


def generate(output: Path) -> None:
    paths = generate_geotiffs(output)
    events = generate_events(output)
    digest = sha256(paths["wgs84"].read_bytes()).hexdigest()
    expected = output / "expected"
    expected.mkdir(parents=True, exist_ok=True)
    (expected / "stac-scene-syn-0001.json").write_text(
        json.dumps(_expected_stac(digest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    statuses = {
        "EVENT-SYN-INSIDE": "matched",
        "EVENT-SYN-OUTSIDE": "spatial-non-match",
        "EVENT-SYN-BOUNDARY": "matched",
        "EVENT-SYN-BEFORE": "temporal-non-match",
        "EVENT-SYN-AFTER": "temporal-non-match",
        "EVENT-SYN-WINDOW-START": "matched",
        "EVENT-SYN-WINDOW-END": "matched",
    }
    correlations = {
        "scene_id": SCENE_ID,
        "temporal_window_seconds": 900,
        "results": [
            {
                "event_id": event["event_id"],
                "expected_status": statuses[str(event["event_id"])],
            }
            for event in events
        ],
    }
    (expected / "correlations.json").write_text(
        json.dumps(correlations, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        str(path.relative_to(output)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    (expected / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output.resolve())
    print(f"Generated deterministic fixtures under {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
