"""Imagery ingestion HTTP contract and persistence."""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from pydantic import ValidationError
from sqlalchemy import or_, select

from terractl.safety import redact_text
from terrawatch.config import get_settings
from terrawatch.constants import IMAGERY_SUBJECT, MAX_UPLOAD_BYTES
from terrawatch.database import OutboxEvent, Scene, session_scope
from terrawatch.hashing import sha256_file
from terrawatch.models import SceneMetadata
from terrawatch.outbox import outbox_loop, publish_pending
from terrawatch.raster import RasterValidationError, inspect_raster
from terrawatch.storage import minio_client

INGEST_ACCEPTED = Counter("terrawatch_ingest_accepted_total", "Accepted imagery scenes")
INGEST_REJECTED = Counter(
    "terrawatch_ingest_rejected_total",
    "Rejected imagery scenes",
    ("code",),
)
LOGGER = structlog.get_logger(service="ingest-api")


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    INGEST_REJECTED.labels(code).inc()
    request_id = getattr(request.state, "request_id", "not-observed")
    LOGGER.info(
        "ingest_rejected",
        request_id=request_id,
        run_id=get_settings().run_id,
        status_code=status_code,
        error_code=code,
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": redact_text(message),
                "details": {},
                "request_id": request_id,
            }
        },
    )


async def _stage_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".tif", ".tiff"}:
        raise RasterValidationError(
            "unsupported-media-type", "Only .tif and .tiff uploads are supported."
        )
    total = 0
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="terrawatch-", suffix=suffix, delete=False) as temp:
            path = Path(temp.name)
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise RasterValidationError(
                        "upload-too-large", f"Upload exceeds {MAX_UPLOAD_BYTES} bytes."
                    )
                temp.write(chunk)
            temp.flush()
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if path is None:
        raise RuntimeError("Temporary upload path was not created.")
    if total == 0:
        path.unlink(missing_ok=True)
        raise RasterValidationError("empty-upload", "Uploaded file is empty.")
    return path


def _existing_scenes(scene_id: str, digest: str) -> tuple[Scene | None, Scene | None]:
    with session_scope() as session:
        scenes = (
            session.execute(
                select(Scene).where(or_(Scene.scene_id == scene_id, Scene.sha256 == digest))
            )
            .scalars()
            .all()
        )
        by_id = next((scene for scene in scenes if scene.scene_id == scene_id), None)
        by_digest = next((scene for scene in scenes if scene.sha256 == digest), None)
        return by_id, by_digest


def _scene_payload(scene: Scene, replayed: bool) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "sha256": scene.sha256,
        "processing_status": scene.processing_status,
        "storage_uri": scene.storage_uri,
        "replayed": replayed,
    }


def _persist_scene(metadata: SceneMetadata, digest: str, object_name: str) -> Scene:
    now = datetime.now(UTC)
    message_id = uuid4()
    scene = Scene(
        scene_id=metadata.scene_id,
        source=metadata.source,
        capture_time=metadata.capture_time,
        sha256=digest,
        storage_uri=f"s3://scenes/{object_name}",
        processing_status="pending",
    )
    envelope = {
        "schema_version": "1.0.0",
        "message_id": str(message_id),
        "event_type": "imagery.ingested",
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "aggregate_id": metadata.scene_id,
        "payload": {
            "scene_id": metadata.scene_id,
            "sha256": digest,
            "object_name": object_name,
        },
    }
    with session_scope() as session:
        session.add(scene)
        session.add(
            OutboxEvent(
                id=message_id,
                aggregate_type="scene",
                aggregate_id=metadata.scene_id,
                subject=IMAGERY_SUBJECT,
                payload=envelope,
            )
        )
    return scene


def register_ingest_routes(app: FastAPI) -> None:
    @app.on_event("startup")
    async def start_outbox() -> None:
        stop = asyncio.Event()
        app.state.outbox_stop = stop
        app.state.outbox_task = asyncio.create_task(outbox_loop(stop))

    @app.on_event("shutdown")
    async def stop_outbox() -> None:
        app.state.outbox_stop.set()
        await app.state.outbox_task

    @app.post("/v1/scenes")
    async def ingest_scene(
        request: Request,
        file: Annotated[UploadFile, File()],
        metadata: Annotated[str, Form()],
    ) -> JSONResponse:
        try:
            declared = SceneMetadata.model_validate_json(metadata)
        except (ValidationError, ValueError):
            return error_response(
                request, 422, "invalid-scene-metadata", "Scene metadata is invalid."
            )
        try:
            staged = await _stage_upload(file)
        except RasterValidationError as error:
            status_code = 415 if error.code == "unsupported-media-type" else 413
            if error.code not in {"unsupported-media-type", "upload-too-large"}:
                status_code = 422
            return error_response(request, status_code, error.code, str(error))

        object_name = ""
        object_created = False
        try:
            inspect_raster(staged)
            digest = sha256_file(staged)
            if declared.declared_sha256 and declared.declared_sha256 != digest:
                return error_response(
                    request, 422, "checksum-mismatch", "Declared checksum does not match."
                )
            by_id, by_digest = await asyncio.to_thread(_existing_scenes, declared.scene_id, digest)
            if by_id is not None and by_id.sha256 != digest:
                return error_response(
                    request,
                    409,
                    "scene-id-conflict",
                    "Scene ID already identifies different content.",
                )
            existing = by_id or by_digest
            if existing is not None:
                return JSONResponse(
                    status_code=200,
                    content=_scene_payload(existing, replayed=True),
                )

            inspect_raster(staged, declared)
            object_name = f"sha256/{digest[:2]}/{digest}.tif"
            client = minio_client()
            client.fput_object(
                get_settings().minio_bucket,
                object_name,
                str(staged),
                content_type="image/tiff; application=geotiff",
            )
            object_created = True
            scene = await asyncio.to_thread(_persist_scene, declared, digest, object_name)
            with suppress(Exception):
                await publish_pending()
            INGEST_ACCEPTED.inc()
            return JSONResponse(status_code=202, content=_scene_payload(scene, replayed=False))
        except RasterValidationError as error:
            return error_response(request, 422, error.code, str(error))
        except Exception as error:
            if object_created and object_name:
                with suppress(Exception):
                    minio_client().remove_object(get_settings().minio_bucket, object_name)
            return error_response(
                request,
                500,
                "ingest-failed",
                f"Ingestion failed: {type(error).__name__}",
            )
        finally:
            staged.unlink(missing_ok=True)
