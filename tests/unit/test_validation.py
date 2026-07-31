from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from terrawatch.models import GeoJsonPoint, SearchFilters, TelemetryEvent
from terrawatch.validation import (
    parse_utc_timestamp,
    validate_bbox,
    validate_coordinates,
    validate_identifier,
    validate_time_range,
    within_temporal_window,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "identifier",
    ["SCENE-SYN-0001", "EVENT-SYN-WINDOW-START", "CORR-SYN-ABC123"],
)
def test_valid_identifier(identifier: str) -> None:
    assert validate_identifier(identifier) == identifier


@pytest.mark.parametrize("identifier", ["lower-case-1", "SCENE", "SCENE bad 1", ""])
def test_invalid_identifier(identifier: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(identifier)


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(-180.1, 0), (180.1, 0), (0, -90.1), (0, 90.1)],
)
def test_invalid_coordinates(longitude: float, latitude: float) -> None:
    with pytest.raises(ValueError):
        validate_coordinates(longitude, latitude)


def test_coordinate_boundaries_are_valid() -> None:
    assert validate_coordinates(-180, -90) == (-180, -90)
    assert validate_coordinates(180, 90) == (180, 90)


def test_valid_bbox() -> None:
    assert validate_bbox([-120.1, 37.1, -119.9, 37.3]) == (-120.1, 37.1, -119.9, 37.3)


@pytest.mark.parametrize(
    "bbox",
    [
        [-120, 37, -120, 38],
        [-119, 37, -120, 38],
        [-120, 38, -119, 37],
        [-181, 37, -119, 38],
        [-120, 37, -119],
    ],
)
def test_invalid_bbox(bbox: list[float]) -> None:
    with pytest.raises(ValueError):
        validate_bbox(bbox)


def test_utc_timestamp_required() -> None:
    assert parse_utc_timestamp("2026-07-29T18:30:00Z").tzinfo == UTC
    with pytest.raises(ValueError):
        parse_utc_timestamp("2026-07-29T18:30:00")
    with pytest.raises(ValueError):
        parse_utc_timestamp("2026-07-29T11:30:00-07:00")


def test_time_range_requires_both_values() -> None:
    with pytest.raises(ValueError):
        validate_time_range("2026-07-29T18:30:00Z", None)
    with pytest.raises(ValidationError):
        SearchFilters(start=datetime.now(UTC))


def test_time_range_order() -> None:
    with pytest.raises(ValueError):
        validate_time_range("2026-07-29T19:30:00Z", "2026-07-29T18:30:00Z")


def test_temporal_window_boundaries() -> None:
    capture = datetime(2026, 7, 29, 18, 30, tzinfo=UTC)
    assert within_temporal_window(capture, capture - timedelta(seconds=900), 900) == (True, 900)
    assert within_temporal_window(capture, capture + timedelta(seconds=900), 900) == (True, 900)
    assert within_temporal_window(capture, capture + timedelta(seconds=901), 900) == (False, 901)


def test_telemetry_model_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TelemetryEvent(
            schema_version="1.0.0",
            event_id="EVENT-SYN-0001",
            event_type="temperature-anomaly",
            observed_at="2026-07-29T18:35:00Z",
            location=GeoJsonPoint(coordinates=(-120.0, 37.2)),
            confidence=0.91,
            source="field-sensor-simulator",
            attributes={},
            unexpected=True,
        )
