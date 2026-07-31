import subprocess
from pathlib import Path

import pytest

from terractl.faults import clear_faults, inject_fault

pytestmark = pytest.mark.unit


def _success(*arguments, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, "ok", "")


def test_pause_fault_is_label_checked_and_recorded(monkeypatch) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr("terractl.faults.load_fault_state", lambda: None)
    monkeypatch.setattr("terractl.faults.assert_environment_green", lambda: None)
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "container-one")
    monkeypatch.setattr("terractl.faults._docker", _success)
    monkeypatch.setattr(
        "terractl.faults._write_state",
        lambda state: observed.update(state),
    )

    result = inject_fault("postgres-unavailable")

    assert result["active"] is True
    assert result["service"] == "postgres"
    assert result["container_id"] == "container-one"
    assert observed["compose_project"] == "project-one"


def test_injection_refuses_when_another_fault_is_active(monkeypatch) -> None:
    monkeypatch.setattr("terractl.faults.load_fault_state", lambda: {"active": True})
    with pytest.raises(RuntimeError, match="already active"):
        inject_fault("nats-unavailable")


def test_clear_revalidates_container_before_unpause(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "active-fault.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "terractl.faults.load_fault_state",
        lambda: {
            "fault": "postgres-unavailable",
            "compose_project": "project-one",
            "action": "pause",
            "service": "postgres",
            "container_id": "container-one",
        },
    )
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "container-one")
    monkeypatch.setattr("terractl.faults._docker", _success)
    monkeypatch.setattr("terractl.faults.fault_state_path", lambda: state_path)

    result = clear_faults()

    assert result["cleared"] is True
    assert not state_path.exists()


def test_clear_refuses_changed_container_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        "terractl.faults.load_fault_state",
        lambda: {
            "fault": "postgres-unavailable",
            "compose_project": "project-one",
            "action": "pause",
            "service": "postgres",
            "container_id": "original",
        },
    )
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "replacement")

    with pytest.raises(RuntimeError, match="identity changed"):
        clear_faults()
