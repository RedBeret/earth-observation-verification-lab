import json
from io import BytesIO, TextIOWrapper

import pytest

from terractl.lifecycle import (
    ComposeResult,
    _parse_ps,
    _write_console,
    assert_environment_green,
    compose_up,
)

pytestmark = pytest.mark.unit


def test_parse_compose_ps_array() -> None:
    assert _parse_ps(json.dumps([{"Service": "postgres", "State": "running"}])) == [
        {"Service": "postgres", "State": "running"}
    ]


def test_parse_compose_ps_json_lines() -> None:
    output = "\n".join(
        [
            json.dumps({"Service": "postgres", "State": "running"}),
            json.dumps({"Service": "minio", "State": "running"}),
        ]
    )
    assert _parse_ps(output) == [
        {"Service": "postgres", "State": "running"},
        {"Service": "minio", "State": "running"},
    ]


def test_console_output_replaces_unrepresentable_progress_symbols() -> None:
    buffer = BytesIO()
    stream = TextIOWrapper(buffer, encoding="cp1252")
    _write_console("built ✓\n", stream)
    stream.flush()
    assert buffer.getvalue().decode("cp1252").splitlines() == ["built ?"]


def test_compose_up_refreshes_environment_before_interpolation(monkeypatch) -> None:
    observed: list[str] = []

    def fake_initialize():
        observed.append("environment")

    def fake_run(*arguments, **kwargs):
        observed.append("compose")
        return ComposeResult(0, "", "")

    monkeypatch.setattr("terractl.lifecycle.initialize_environment", fake_initialize)
    monkeypatch.setattr("terractl.lifecycle.run_compose", fake_run)

    assert compose_up() == 0
    assert observed == ["environment", "compose"]


def test_green_environment_requires_running_healthy_services(monkeypatch) -> None:
    services = []
    for name in (
        "postgres",
        "minio",
        "nats",
        "ingest-api",
        "event-api",
        "analysis-api",
        "imagery-worker",
        "correlation-worker",
    ):
        services.append(
            {
                "Service": name,
                "State": "running",
                "Health": "" if name.endswith("worker") else "healthy",
            }
        )
    monkeypatch.setattr(
        "terractl.lifecycle.run_compose",
        lambda *arguments, **kwargs: ComposeResult(0, json.dumps(services), ""),
    )
    assert_environment_green()

    services[0]["Health"] = "unhealthy"
    with pytest.raises(RuntimeError, match="not healthy"):
        assert_environment_green()
