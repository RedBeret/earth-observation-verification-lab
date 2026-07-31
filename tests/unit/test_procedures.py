import pytest

from terractl.procedures import (
    PROCEDURE_TEST_TARGETS,
    load_procedure,
    run_procedure,
    validate_all_procedures,
)

pytestmark = pytest.mark.unit


def test_all_formal_procedures_validate() -> None:
    assert validate_all_procedures() == [
        "TP-API-004",
        "TP-EVD-005",
        "TP-ING-002",
        "TP-RES-003",
        "TP-SYS-001",
    ]


def test_unknown_procedure_fails() -> None:
    with pytest.raises(ValueError, match="unknown procedure"):
        load_procedure("TP-NOT-999")


def test_ingest_procedure_has_a_live_execution_target() -> None:
    assert PROCEDURE_TEST_TARGETS["TP-ING-002"] == (
        "contract",
        "tests/contract/test_ingest_contract.py",
    )


def test_stage_four_procedures_have_live_execution_targets() -> None:
    assert PROCEDURE_TEST_TARGETS["TP-API-004"] == (
        "contract",
        "tests/contract/test_event_contract.py",
        "tests/contract/test_analysis_contract.py",
    )
    assert PROCEDURE_TEST_TARGETS["TP-SYS-001"] == (
        "system",
        "tests/system/test_workflow.py",
    )


def test_ingest_procedure_runs_its_bound_test_target(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, *, cwd, check):
        observed.update(command=command, cwd=cwd, check=check)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("terractl.procedures.subprocess.run", fake_run)

    assert run_procedure("TP-ING-002") == 0
    command = observed["command"]
    assert "tests/contract/test_ingest_contract.py" in command
    assert any(str(part).endswith("procedure-TP-ING-002.xml") for part in command)
