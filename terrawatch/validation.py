"""Public input validation shared by APIs, workers, and tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator

_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,7}$")


def validate_identifier(value: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError("identifier must be uppercase, hyphen-delimited, and structured")
    if len(value) > 96:
        raise ValueError("identifier exceeds 96 characters")
    return value


StructuredId = Annotated[str, AfterValidator(validate_identifier)]


def validate_coordinates(longitude: float, latitude: float) -> tuple[float, float]:
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("longitude must be between -180 and 180")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("latitude must be between -90 and 90")
    return longitude, latitude


def validate_bbox(values: list[float] | tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise ValueError("bounding box requires four values")
    west, south, east, north = (float(value) for value in values)
    validate_coordinates(west, south)
    validate_coordinates(east, north)
    if west >= east or south >= north:
        raise ValueError("bounding box minimums must be less than maximums")
    return west, south, east, north


def parse_utc_timestamp(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    normalized = parsed.astimezone(UTC)
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return normalized


def validate_time_range(
    start: str | datetime | None,
    end: str | datetime | None,
) -> tuple[datetime, datetime] | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("time range requires both start and end")
    start_utc = parse_utc_timestamp(start)
    end_utc = parse_utc_timestamp(end)
    if start_utc > end_utc:
        raise ValueError("time range start must not be after end")
    return start_utc, end_utc


def within_temporal_window(
    capture_time: datetime,
    observed_at: datetime,
    window_seconds: int,
) -> tuple[bool, int]:
    if window_seconds < 0:
        raise ValueError("window must be non-negative")
    capture = parse_utc_timestamp(capture_time)
    observed = parse_utc_timestamp(observed_at)
    delta = int(abs((observed - capture).total_seconds()))
    return delta <= window_seconds, delta
