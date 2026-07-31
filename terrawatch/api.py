"""Shared FastAPI operational surface and middleware."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from terractl.safety import redact_text
from terrawatch.config import get_settings
from terrawatch.database import database_ready
from terrawatch.logging import configure_logging
from terrawatch.messaging import messaging_ready
from terrawatch.storage import storage_ready

REQUESTS = Counter(
    "terrawatch_api_requests_total",
    "API requests",
    ("service", "method", "path", "status"),
)
LATENCY = Histogram(
    "terrawatch_api_request_duration_seconds",
    "API request latency",
    ("service", "method", "path"),
)

AsyncProbe = Callable[[], Awaitable[tuple[bool, str]]]
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalized_request_id(candidate: str | None) -> str:
    if candidate is not None and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def api_error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": redact_text(message),
                "details": details or {},
                "request_id": getattr(request.state, "request_id", "not-observed"),
            }
        },
    )


def create_app(service_name: str, dependencies: tuple[str, ...]) -> FastAPI:
    configure_logging()
    logger = structlog.get_logger(service=service_name)
    run_id = get_settings().run_id
    app = FastAPI(title=f"TerraWatch {service_name}", version="1.0.0")
    app.state.service_name = service_name
    app.state.dependencies = dependencies

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        if error.status_code == 404:
            return api_error_response(
                request,
                404,
                "resource-not-found",
                "Requested resource was not found.",
            )
        return api_error_response(
            request,
            error.status_code,
            "http-error",
            "The HTTP request could not be completed.",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return api_error_response(
            request,
            422,
            "invalid-request",
            "Request parameters are invalid.",
            details={"error_count": len(error.errors())},
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = normalized_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal-error",
                        "message": "The request could not be completed.",
                        "details": {},
                        "request_id": request_id,
                    }
                },
            )
        duration = time.perf_counter() - started
        response.headers["X-Request-ID"] = request_id
        REQUESTS.labels(service_name, request.method, request.url.path, response.status_code).inc()
        LATENCY.labels(service_name, request.method, request.url.path).observe(duration)
        logger.info(
            "request_completed",
            request_id=request_id,
            run_id=run_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 3),
        )
        return response

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    @app.get("/readyz")
    async def readiness() -> Response:
        checks: dict[str, dict[str, str | bool]] = {}
        if "postgres" in dependencies:
            ok, detail = await asyncio.to_thread(database_ready)
            checks["postgres"] = {"ready": ok, "detail": detail}
        if "minio" in dependencies:
            ok, detail = await asyncio.to_thread(storage_ready)
            checks["minio"] = {"ready": ok, "detail": detail}
        if "nats" in dependencies:
            ok, detail = await messaging_ready()
            checks["nats"] = {"ready": ok, "detail": detail}
        ready = all(bool(check["ready"]) for check in checks.values())
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "ready" if ready else "not-ready", "dependencies": checks},
        )

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
