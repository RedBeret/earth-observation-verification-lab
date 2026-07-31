import json

import pytest

from terractl.lifecycle import ComposeResult, _parse_ps, compose_up

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
