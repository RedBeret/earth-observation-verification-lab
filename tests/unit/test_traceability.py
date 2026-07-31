import copy
import shutil
from pathlib import Path

import pytest
import yaml

from terractl.environment import project_root
from terractl.traceability import validate_traceability

pytestmark = pytest.mark.unit


def _copy_inputs(destination: Path) -> None:
    shutil.copytree(project_root() / "requirements", destination / "requirements")
    shutil.copytree(project_root() / "procedures", destination / "procedures")


def test_complete_mapping() -> None:
    result = validate_traceability()
    assert result.passed, result.errors
    assert result.requirements == 40
    assert result.mapped_requirements == 40


def test_stale_reference_fails(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    matrix_path = tmp_path / "requirements" / "verification-matrix.yaml"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    stale = copy.deepcopy(matrix["mappings"][0])
    stale["requirement_id"] = "OLD-999"
    matrix["mappings"].append(stale)
    matrix_path.write_text(yaml.safe_dump(matrix, sort_keys=False), encoding="utf-8")
    result = validate_traceability(tmp_path)
    assert not result.passed
    assert any("unknown requirement: OLD-999" in error for error in result.errors)


def test_missing_procedure_fails(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    (tmp_path / "procedures" / "TP-SYS-001.yaml").unlink()
    result = validate_traceability(tmp_path)
    assert not result.passed
    assert any("missing procedure: TP-SYS-001" in error for error in result.errors)
