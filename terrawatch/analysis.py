"""Read-only catalog, event, correlation, analysis, and provenance APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from terrawatch.api import api_error_response
from terrawatch.config import get_settings
from terrawatch.constants import ALGORITHM_VERSION, REQUIREMENTS_VERSION
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    Scene,
    SessionFactory,
    TelemetryEventRecord,
)
from terrawatch.validation import validate_bbox, validate_time_range


class QueryContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_pagination(page: str, page_size: str) -> tuple[int, int]:
    try:
        page_value = int(page)
        size_value = int(page_size)
    except ValueError as error:
        raise QueryContractError(
            "invalid-pagination",
            "Page and page_size must be integers.",
        ) from error
    if page_value < 1 or size_value < 1 or size_value > 100:
        raise QueryContractError(
            "invalid-pagination",
            "Page must be positive and page_size must be between 1 and 100.",
        )
    return page_value, size_value


def parse_filters(
    bbox: str | None,
    start: str | None,
    end: str | None,
) -> tuple[
    tuple[float, float, float, float] | None,
    tuple[datetime, datetime] | None,
]:
    parsed_bbox: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            parsed_bbox = validate_bbox([float(part) for part in bbox.split(",")])
        except ValueError as error:
            raise QueryContractError(
                "invalid-bbox",
                "Bounding box must contain ordered WGS84 west,south,east,north values.",
            ) from error
    try:
        parsed_time = validate_time_range(start, end)
    except ValueError as error:
        raise QueryContractError(
            "invalid-time-range",
            "Start and end must form an inclusive ordered UTC interval.",
        ) from error
    return parsed_bbox, parsed_time


def scene_payload(scene: Scene) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "source": scene.source,
        "capture_time": utc_text(scene.capture_time),
        "sha256": scene.sha256,
        "crs": scene.crs,
        "bbox": scene.bbox,
        "width": scene.width,
        "height": scene.height,
        "resolution": scene.resolution,
        "storage_uri": scene.storage_uri,
        "processing_status": scene.processing_status,
        "stac_item": scene.stac_item,
    }


def event_payload(event: TelemetryEventRecord) -> dict[str, Any]:
    point = to_shape(event.location)
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "observed_at": utc_text(event.observed_at),
        "location": {
            "type": "Point",
            "coordinates": [point.x, point.y],
        },
        "confidence": event.confidence,
        "source": event.source,
        "attributes": event.attributes,
        "payload_hash": event.payload_hash,
        "processing_status": event.processing_status,
    }


def correlation_payload(correlation: Correlation) -> dict[str, Any]:
    return {
        "correlation_id": correlation.correlation_id,
        "scene_id": correlation.scene_id,
        "event_id": correlation.event_id,
        "spatial_match": correlation.spatial_match,
        "temporal_delta_seconds": correlation.temporal_delta_seconds,
        "correlation_status": correlation.correlation_status,
        "algorithm_version": correlation.algorithm_version,
        "provenance": correlation.provenance,
    }


def analysis_payload(result: AnalysisResult) -> dict[str, Any]:
    return {
        "event_id": result.event_id,
        "algorithm_version": result.algorithm_version,
        "status": result.status,
        "evaluated_scenes": result.evaluated_scenes,
        "matched_correlation_ids": result.matched_correlation_ids,
        "details": result.details,
        "provenance": result.provenance,
    }


def _query_error(request: Request, error: QueryContractError) -> JSONResponse:
    return api_error_response(request, 422, error.code, str(error))


def register_analysis_routes(app: FastAPI) -> None:
    @app.get("/v1/scenes/{scene_id}")
    def get_scene(scene_id: str, request: Request) -> JSONResponse:
        with SessionFactory() as session:
            scene = session.get(Scene, scene_id)
            if scene is None or scene.processing_status != "accepted":
                return api_error_response(
                    request,
                    404,
                    "scene-not-found",
                    "Scene was not found.",
                )
            return JSONResponse(content=scene_payload(scene))

    @app.get("/v1/scenes/{scene_id}/stac")
    def get_scene_stac(scene_id: str, request: Request) -> JSONResponse:
        with SessionFactory() as session:
            scene = session.get(Scene, scene_id)
            if scene is None or scene.processing_status != "accepted" or scene.stac_item is None:
                return api_error_response(
                    request,
                    404,
                    "scene-not-found",
                    "Accepted scene catalog item was not found.",
                )
            return JSONResponse(content=scene.stac_item)

    @app.get("/v1/scenes")
    def search_scenes(
        request: Request,
        bbox: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: str = "1",
        page_size: str = "50",
    ) -> JSONResponse:
        try:
            parsed_bbox, parsed_time = parse_filters(bbox, start, end)
            page_value, size_value = parse_pagination(page, page_size)
        except QueryContractError as error:
            return _query_error(request, error)
        conditions: list[ColumnElement[bool]] = [Scene.processing_status == "accepted"]
        if parsed_bbox is not None:
            conditions.append(
                func.ST_Intersects(
                    Scene.footprint,
                    func.ST_MakeEnvelope(*parsed_bbox, 4326),
                )
            )
        if parsed_time is not None:
            conditions.extend(
                [
                    Scene.capture_time >= parsed_time[0],
                    Scene.capture_time <= parsed_time[1],
                ]
            )
        with SessionFactory() as session:
            total = session.scalar(select(func.count()).select_from(Scene).where(*conditions)) or 0
            scenes = (
                session.execute(
                    select(Scene)
                    .where(*conditions)
                    .order_by(Scene.scene_id)
                    .offset((page_value - 1) * size_value)
                    .limit(size_value)
                )
                .scalars()
                .all()
            )
            return JSONResponse(
                content={
                    "items": [scene_payload(scene) for scene in scenes],
                    "page": page_value,
                    "page_size": size_value,
                    "total": total,
                }
            )

    @app.get("/v1/events/{event_id}")
    def get_event(event_id: str, request: Request) -> JSONResponse:
        with SessionFactory() as session:
            event = session.get(TelemetryEventRecord, event_id)
            if event is None:
                return api_error_response(
                    request,
                    404,
                    "event-not-found",
                    "Telemetry event was not found.",
                )
            return JSONResponse(content=event_payload(event))

    @app.get("/v1/events")
    def search_events(
        request: Request,
        bbox: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: str = "1",
        page_size: str = "50",
    ) -> JSONResponse:
        try:
            parsed_bbox, parsed_time = parse_filters(bbox, start, end)
            page_value, size_value = parse_pagination(page, page_size)
        except QueryContractError as error:
            return _query_error(request, error)
        conditions: list[ColumnElement[bool]] = []
        if parsed_bbox is not None:
            conditions.append(
                func.ST_Covers(
                    func.ST_MakeEnvelope(*parsed_bbox, 4326),
                    TelemetryEventRecord.location,
                )
            )
        if parsed_time is not None:
            conditions.extend(
                [
                    TelemetryEventRecord.observed_at >= parsed_time[0],
                    TelemetryEventRecord.observed_at <= parsed_time[1],
                ]
            )
        with SessionFactory() as session:
            total = (
                session.scalar(
                    select(func.count()).select_from(TelemetryEventRecord).where(*conditions)
                )
                or 0
            )
            events = (
                session.execute(
                    select(TelemetryEventRecord)
                    .where(*conditions)
                    .order_by(TelemetryEventRecord.event_id)
                    .offset((page_value - 1) * size_value)
                    .limit(size_value)
                )
                .scalars()
                .all()
            )
            return JSONResponse(
                content={
                    "items": [event_payload(event) for event in events],
                    "page": page_value,
                    "page_size": size_value,
                    "total": total,
                }
            )

    @app.get("/v1/correlations/{correlation_id}")
    def get_correlation(correlation_id: str, request: Request) -> JSONResponse:
        with SessionFactory() as session:
            correlation = session.get(Correlation, correlation_id)
            if correlation is None:
                return api_error_response(
                    request,
                    404,
                    "correlation-not-found",
                    "Correlation was not found.",
                )
            return JSONResponse(content=correlation_payload(correlation))

    @app.get("/v1/analysis-results/{event_id}")
    def get_analysis_result(event_id: str, request: Request) -> JSONResponse:
        with SessionFactory() as session:
            result = session.get(AnalysisResult, (event_id, ALGORITHM_VERSION))
            if result is None:
                return api_error_response(
                    request,
                    404,
                    "analysis-result-not-found",
                    "Analysis result was not found.",
                )
            return JSONResponse(content=analysis_payload(result))

    @app.get("/v1/provenance/{resource_type}/{resource_id}")
    def get_provenance(
        resource_type: str,
        resource_id: str,
        request: Request,
    ) -> JSONResponse:
        settings = get_settings()
        with SessionFactory() as session:
            provenance: dict[str, Any] | None = None
            if resource_type == "scene":
                scene = session.get(Scene, resource_id)
                if scene is not None:
                    provenance = {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "source": scene.source,
                        "scene_sha256": scene.sha256,
                        "storage_uri": scene.storage_uri,
                        "software_revision": settings.software_revision,
                        "requirements_version": REQUIREMENTS_VERSION,
                    }
            elif resource_type == "event":
                event = session.get(TelemetryEventRecord, resource_id)
                if event is not None:
                    provenance = {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "source": event.source,
                        "event_payload_hash": event.payload_hash,
                        "software_revision": settings.software_revision,
                        "requirements_version": REQUIREMENTS_VERSION,
                    }
            elif resource_type == "correlation":
                correlation = session.get(Correlation, resource_id)
                if correlation is not None:
                    provenance = {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        **correlation.provenance,
                    }
            elif resource_type == "analysis-result":
                result = session.get(AnalysisResult, (resource_id, ALGORITHM_VERSION))
                if result is not None:
                    provenance = {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        **result.provenance,
                    }
            if provenance is None:
                return api_error_response(
                    request,
                    404,
                    "provenance-not-found",
                    "Provenance was not found.",
                )
            return JSONResponse(content=provenance)
