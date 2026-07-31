import asyncio
from pathlib import Path

import httpx
import pytest
from minio import Minio
from sqlalchemy import create_engine, inspect, text

from terractl.environment import project_root
from terractl.lifecycle import assert_loopback_ports, rendered_compose_config
from terrawatch.config import Settings
from terrawatch.messaging import DLQ_STREAM, EVENT_STREAM, connect

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings(_env_file=project_root() / ".env.local")


def test_compose_ports_labels_and_resource_limits() -> None:
    config = rendered_compose_config()
    assert_loopback_ports(config)
    postgres_healthcheck = config["services"]["postgres"]["healthcheck"]["test"]
    assert "-h 127.0.0.1" in " ".join(postgres_healthcheck)
    required = {
        "postgres",
        "minio",
        "nats",
        "ingest-api",
        "event-api",
        "analysis-api",
        "imagery-worker",
        "correlation-worker",
    }
    assert required <= set(config["services"])
    for service_name in required:
        service = config["services"][service_name]
        assert service["labels"]["org.northstar.project"] == "earth-observation-verification-lab"
        assert service["deploy"]["resources"]["limits"]["memory"]
        assert service["security_opt"] == ["no-new-privileges:true"]


def test_postgis_migration_and_constraints() -> None:
    settings = _settings()
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT PostGIS_Version()")).scalar_one()
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0001_initial_schema"
        )
    table_names = set(inspect(engine).get_table_names())
    assert {
        "scenes",
        "telemetry_events",
        "correlations",
        "analysis_results",
        "outbox_events",
        "processing_attempts",
        "dead_letters",
    } <= table_names


def test_minio_bucket_exists() -> None:
    settings = _settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    assert client.bucket_exists(settings.minio_bucket)
    assert list(client.list_objects(settings.minio_bucket, recursive=True)) == []


def test_nats_streams_exist() -> None:
    async def inspect_streams() -> set[str]:
        client = await connect(_settings())
        try:
            jetstream = client.jetstream()
            return {
                (await jetstream.stream_info(EVENT_STREAM)).config.name,
                (await jetstream.stream_info(DLQ_STREAM)).config.name,
            }
        finally:
            await client.drain()

    assert asyncio.run(inspect_streams()) == {EVENT_STREAM, DLQ_STREAM}


@pytest.mark.parametrize("port", [18001, 18002, 18003])
def test_health_and_readiness(port: int) -> None:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        metrics = client.get("/metrics")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    assert metrics.status_code == 200
    assert "terrawatch_api_requests_total" in metrics.text


def test_generated_configuration_is_local_only() -> None:
    path = Path(project_root() / ".env.local")
    content = path.read_text(encoding="utf-8")
    assert "127.0.0.1" in content
    assert "0.0.0.0" not in content
    assert "POSTGRES_PASSWORD=" in content
