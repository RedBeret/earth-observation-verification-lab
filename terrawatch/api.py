"""Shared FastAPI operational surface and middleware."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from terrawatch.database import database_ready
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


def create_app(service_name: str, dependencies: tuple[str, ...]) -> FastAPI:
    app = FastAPI(title=f"TerraWatch {service_name}", version="1.0.0")
    app.state.service_name = service_name
    app.state.dependencies = dependencies

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
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
