"""Generate deterministic spatial and temporal telemetry cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from data.generators.generate_geotiffs import CAPTURE_TIME


def _event(
    suffix: str,
    coordinates: tuple[float, float],
    observed_at: datetime,
    *,
    temperature: float,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "event_id": f"EVENT-SYN-{suffix}",
        "event_type": "temperature-anomaly",
        "observed_at": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "location": {"type": "Point", "coordinates": list(coordinates)},
        "confidence": 0.91,
        "source": "field-sensor-simulator",
        "attributes": {"temperature_c": temperature},
    }


def generate(root: Path) -> list[dict[str, object]]:
    base = datetime.fromisoformat(CAPTURE_TIME.replace("Z", "+00:00"))
    events = [
        _event("INSIDE", (-120.00, 37.20), base + timedelta(minutes=5), temperature=47.2),
        _event("OUTSIDE", (-121.00, 38.00), base + timedelta(minutes=5), temperature=45.0),
        _event("BOUNDARY", (-120.10, 37.20), base, temperature=46.0),
        _event("BEFORE", (-120.00, 37.20), base - timedelta(minutes=16), temperature=44.0),
        _event("AFTER", (-120.00, 37.20), base + timedelta(minutes=16), temperature=48.0),
        _event("WINDOW-START", (-120.00, 37.20), base - timedelta(minutes=15), temperature=43.0),
        _event("WINDOW-END", (-120.00, 37.20), base + timedelta(minutes=15), temperature=49.0),
    ]
    directory = root / "events"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"seed": 240729, "events": events, "duplicate_event_id": "EVENT-SYN-INSIDE"}
    (directory / "events.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return events
