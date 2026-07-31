"""Versioned public and internal data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from terrawatch.validation import (
    StructuredId,
    parse_utc_timestamp,
    validate_bbox,
    validate_coordinates,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SceneMetadata(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scene_id: StructuredId
    source: str = Field(min_length=1, max_length=80)
    capture_time: datetime
    declared_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("capture_time")
    @classmethod
    def utc_capture_time(cls, value: datetime) -> datetime:
        return parse_utc_timestamp(value)


class GeoJsonPoint(StrictModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def valid_coordinates(cls, value: tuple[float, float]) -> tuple[float, float]:
        return validate_coordinates(*value)


class TelemetryEvent(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: StructuredId
    event_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]+$")
    observed_at: datetime
    location: GeoJsonPoint
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=80)
    attributes: dict[str, int | float | str | bool] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def utc_observed_at(cls, value: datetime) -> datetime:
        return parse_utc_timestamp(value)


class CorrelationProvenance(StrictModel):
    scene_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    software_revision: str
    requirements_version: str
    algorithm_version: str


class CorrelationResult(StrictModel):
    correlation_id: StructuredId
    scene_id: StructuredId
    event_id: StructuredId
    spatial_match: bool
    temporal_delta_seconds: int = Field(ge=0)
    correlation_status: Literal["matched", "spatial-non-match", "temporal-non-match"]
    provenance: CorrelationProvenance


class SearchFilters(StrictModel):
    bbox: tuple[float, float, float, float] | None = None
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("bbox")
    @classmethod
    def valid_bbox(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        return None if value is None else validate_bbox(value)

    @model_validator(mode="after")
    def valid_time_range(self) -> SearchFilters:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must be supplied together")
        if self.start is not None and self.end is not None:
            start = parse_utc_timestamp(self.start)
            end = parse_utc_timestamp(self.end)
            if start > end:
                raise ValueError("start must not be after end")
            self.start = start
            self.end = end
        return self


class ErrorBody(StrictModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(StrictModel):
    error: ErrorBody
