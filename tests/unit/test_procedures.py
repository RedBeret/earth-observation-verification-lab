import pytest

from terractl.procedures import load_procedure, validate_all_procedures

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
