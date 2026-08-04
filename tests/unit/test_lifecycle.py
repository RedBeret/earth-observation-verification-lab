import json
from io import BytesIO, TextIOWrapper

import pytest

from terractl.lifecycle import (
    ComposeResult,
    _parse_ps,
    _write_console,
    assert_environment_green,
    compose_up,
    up_timeout_seconds,
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


def test_the_startup_timeout_allows_a_cold_first_build(monkeypatch) -> None:
    """A clean machine pulls three service images and builds five of its own before
    anything is healthy. The ceiling has to survive that, or the first run someone ever
    does is the one that fails."""
    monkeypatch.delenv("TERRA_UP_TIMEOUT_SECONDS", raising=False)
    assert up_timeout_seconds() >= 1200


def test_the_startup_timeout_is_overridable(monkeypatch) -> None:
    monkeypatch.setenv("TERRA_UP_TIMEOUT_SECONDS", "2400")
    assert up_timeout_seconds() == 2400


@pytest.mark.parametrize("value", ["0", "-1", "soon"])
def test_an_unusable_startup_timeout_is_refused(monkeypatch, value: str) -> None:
    monkeypatch.setenv("TERRA_UP_TIMEOUT_SECONDS", value)
    with pytest.raises(RuntimeError):
        up_timeout_seconds()


def _service_payload(paused: str | None = None) -> list[dict[str, str]]:
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
        state = "paused" if name == paused else "running"
        services.append(
            {
                "Service": name,
                "State": state,
                # A paused container reports no useful health, which is the point.
                "Health": "" if name.endswith("worker") or state == "paused" else "healthy",
            }
        )
    return services


def test_a_paused_service_is_not_green_by_default(monkeypatch) -> None:
    payload = _service_payload(paused="correlation-worker")
    monkeypatch.setattr(
        "terractl.lifecycle.run_compose",
        lambda *arguments, **kwargs: ComposeResult(0, json.dumps(payload), ""),
    )
    with pytest.raises(RuntimeError, match="not running"):
        assert_environment_green()


def test_fault_injection_tolerates_a_deliberately_paused_service(monkeypatch) -> None:
    """A resilience drill pauses a worker to queue messages and then injects a fault. If
    the guard counted that pause as a missing service the drill could never run."""
    payload = _service_payload(paused="correlation-worker")
    monkeypatch.setattr(
        "terractl.lifecycle.run_compose",
        lambda *arguments, **kwargs: ComposeResult(0, json.dumps(payload), ""),
    )
    assert_environment_green(allow_paused=True)


def test_a_stopped_service_is_never_green(monkeypatch) -> None:
    payload = _service_payload()
    payload[0]["State"] = "exited"
    monkeypatch.setattr(
        "terractl.lifecycle.run_compose",
        lambda *arguments, **kwargs: ComposeResult(0, json.dumps(payload), ""),
    )
    for allow in (False, True):
        with pytest.raises(RuntimeError, match="not running"):
            assert_environment_green(allow_paused=allow)


def test_an_unhealthy_service_is_never_green(monkeypatch) -> None:
    payload = _service_payload()
    payload[0]["Health"] = "unhealthy"
    monkeypatch.setattr(
        "terractl.lifecycle.run_compose",
        lambda *arguments, **kwargs: ComposeResult(0, json.dumps(payload), ""),
    )
    for allow in (False, True):
        with pytest.raises(RuntimeError, match="not healthy"):
            assert_environment_green(allow_paused=allow)
