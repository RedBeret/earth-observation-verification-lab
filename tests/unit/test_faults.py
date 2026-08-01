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


def _compose(stdout: str, returncode: int = 0):
    def runner(*arguments, **kwargs):
        return type("Result", (), {"returncode": returncode, "stdout": stdout, "stderr": ""})()

    return runner


def _docker_router(states: dict[str, str], labels: str):
    def runner(*arguments, **kwargs):
        if arguments[0] == "inspect" and arguments[-1] == "{{.State.Status}}":
            return subprocess.CompletedProcess([], 0, states[arguments[1]], "")
        if arguments[0] == "inspect":
            return subprocess.CompletedProcess([], 0, labels, "")
        return subprocess.CompletedProcess([], 0, "ok", "")

    return runner


LABELS = (
    '{"org.northstar.project": "earth-observation-verification-lab", '
    '"com.docker.compose.project": "project-one"}'
)


def test_a_paused_container_still_resolves(monkeypatch) -> None:
    from terractl.faults import _service_container_id

    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults.run_compose", _compose("container-one\n"))
    monkeypatch.setattr(
        "terractl.faults._docker", _docker_router({"container-one": "paused"}, LABELS)
    )

    assert _service_container_id("postgres") == "container-one"


def test_stale_exited_containers_are_ignored(monkeypatch) -> None:
    from terractl.faults import _service_container_id

    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults.run_compose", _compose("old-one\ncontainer-one\n"))
    monkeypatch.setattr(
        "terractl.faults._docker",
        _docker_router({"old-one": "exited", "container-one": "running"}, LABELS),
    )

    assert _service_container_id("postgres") == "container-one"


def test_two_live_containers_refuse_to_resolve(monkeypatch) -> None:
    from terractl.faults import _service_container_id

    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults.run_compose", _compose("one\ntwo\n"))
    monkeypatch.setattr(
        "terractl.faults._docker", _docker_router({"one": "running", "two": "running"}, LABELS)
    )

    with pytest.raises(RuntimeError, match="exactly one live container"):
        _service_container_id("postgres")


def test_intent_is_recorded_before_the_container_is_paused(monkeypatch) -> None:
    writes: list[dict] = []
    monkeypatch.setattr("terractl.faults.load_fault_state", lambda: None)
    monkeypatch.setattr("terractl.faults.assert_environment_green", lambda: None)
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "container-one")
    monkeypatch.setattr("terractl.faults._write_state", lambda state: writes.append(dict(state)))

    def paused_only_after_write(*arguments, **kwargs):
        assert writes, "the fault was applied before its intent was recorded"
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr("terractl.faults._docker", paused_only_after_write)

    inject_fault("postgres-unavailable")

    assert writes[0]["active"] is False
    assert writes[-1]["active"] is True


def test_a_failed_pause_leaves_no_stale_state(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "active-fault.json"
    monkeypatch.setattr("terractl.faults.load_fault_state", lambda: None)
    monkeypatch.setattr("terractl.faults.assert_environment_green", lambda: None)
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "container-one")
    monkeypatch.setattr("terractl.faults.fault_state_path", lambda: state_path)
    monkeypatch.setattr(
        "terractl.faults._docker",
        lambda *a, **k: subprocess.CompletedProcess([], 1, "", "pause refused"),
    )

    with pytest.raises(RuntimeError, match="pause refused"):
        inject_fault("postgres-unavailable")
    assert not state_path.exists()


def test_clearing_an_unapplied_pause_does_not_unpause(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "active-fault.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[tuple] = []
    monkeypatch.setattr(
        "terractl.faults.load_fault_state",
        lambda: {
            "fault": "postgres-unavailable",
            "compose_project": "project-one",
            "action": "pause",
            "service": "postgres",
            "container_id": "container-one",
            "active": False,
        },
    )
    monkeypatch.setattr("terractl.faults.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.faults._service_container_id", lambda service: "container-one")
    monkeypatch.setattr("terractl.faults._container_state", lambda identifier: "running")
    monkeypatch.setattr("terractl.faults.fault_state_path", lambda: state_path)

    def record(*arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr("terractl.faults._docker", record)

    assert clear_faults()["cleared"] is True
    assert not any(call and call[0] == "unpause" for call in calls)
    assert not state_path.exists()
