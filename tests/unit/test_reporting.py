import json
from pathlib import Path

import pytest
import yaml

from terractl.evidence import reconcile_evidence
from terractl.reporting import (
    build_summary,
    collect_outcomes,
    generate_evidence,
    parse_junit,
)

pytestmark = pytest.mark.unit

REQUIREMENTS = {
    "version": "1.0.0",
    "requirements": [
        {
            "id": "ING-001",
            "statement": "The system shall accept a valid synthetic scene.",
            "rationale": "primary path",
            "verification_method": "test",
            "procedure_ids": ["TP-SYS-001"],
            "automated_tests": ["tests/system/test_workflow.py::test_nominal_workflow"],
            "status": "planned",
            "evidence_location": "artifacts/evidence/<run-id>/",
        },
        {
            "id": "ING-002",
            "statement": "The system shall preserve a digest for every accepted scene.",
            "rationale": "provenance",
            "verification_method": "test",
            "procedure_ids": ["TP-SYS-001"],
            "automated_tests": ["tests/unit/test_hashing.py::test_sha256_file"],
            "status": "planned",
            "evidence_location": "artifacts/evidence/<run-id>/",
        },
    ],
}


def _junit(cases: str) -> str:
    header = '<?xml version="1.0" encoding="utf-8"?>'
    return f"{header}<testsuites><testsuite>{cases}</testsuite></testsuites>"


def _repository(tmp_path: Path, cases: str) -> Path:
    (tmp_path / "requirements").mkdir(parents=True)
    (tmp_path / "requirements" / "system-requirements.yaml").write_text(
        yaml.safe_dump(REQUIREMENTS), encoding="utf-8"
    )
    junit = tmp_path / "artifacts" / "junit"
    junit.mkdir(parents=True)
    (junit / "unit.xml").write_text(_junit(cases), encoding="utf-8")
    return tmp_path


def test_junit_cases_map_onto_requirement_test_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "unit.xml"
    path.write_text(
        _junit(
            '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.5"/>'
        ),
        encoding="utf-8",
    )
    outcomes = parse_junit(path)
    assert "tests/unit/test_hashing.py::test_sha256_file" in outcomes
    assert outcomes["tests/unit/test_hashing.py::test_sha256_file"].duration_ms == 500


def test_parameter_cases_fold_into_one_result_and_a_single_failure_wins(tmp_path: Path) -> None:
    path = tmp_path / "unit.xml"
    path.write_text(
        _junit(
            '<testcase classname="tests.unit.test_safety" name="test_redaction[a]" time="0.1"/>'
            '<testcase classname="tests.unit.test_safety" name="test_redaction[b]" time="0.1">'
            '<failure message="boom"/></testcase>'
        ),
        encoding="utf-8",
    )
    outcome = parse_junit(path)["tests/unit/test_safety.py::test_redaction"]
    assert outcome.passed is False
    assert outcome.duration_ms == 200


def test_a_skipped_case_is_not_a_pass(tmp_path: Path) -> None:
    path = tmp_path / "unit.xml"
    path.write_text(
        _junit(
            '<testcase classname="tests.unit.test_hashing" name="test_sha256_file">'
            "<skipped/></testcase>"
        ),
        encoding="utf-8",
    )
    assert parse_junit(path)["tests/unit/test_hashing.py::test_sha256_file"].passed is False


def test_missing_results_cannot_be_treated_as_an_empty_pass(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no JUnit results"):
        collect_outcomes(tmp_path)


def test_an_unexecuted_requirement_is_reported_as_not_observed(tmp_path: Path) -> None:
    repo = _repository(
        tmp_path,
        '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.01"/>',
    )
    summary = build_summary("unit-partial", repo)
    by_requirement = {record.requirement_id: record for record in summary.records}
    assert by_requirement["ING-002"].passed is True
    assert by_requirement["ING-001"].observation_status == "not observed"
    assert by_requirement["ING-001"].passed is False
    assert by_requirement["ING-001"].observed is None
    assert summary.total == 2
    assert summary.failed == 1


def test_a_complete_run_renders_and_reconciles(tmp_path: Path, monkeypatch) -> None:
    repo = _repository(
        tmp_path,
        '<testcase classname="tests.system.test_workflow" name="test_nominal_workflow" time="1"/>'
        '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.01"/>',
    )
    monkeypatch.setattr("terractl.reporting.artifacts_root", lambda: repo / "artifacts")
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: repo / "artifacts")
    package = generate_evidence("unit-complete", repo)
    assert {
        "test-summary.json",
        "test-summary.md",
        "requirements-verification.csv",
        "junit.xml",
        "manifest.json",
    } <= {path.name for path in package.iterdir()}
    assert reconcile_evidence(package) == {"total": 2, "failed": 0, "passed": 2}


def test_edited_evidence_fails_its_manifest(tmp_path: Path, monkeypatch) -> None:
    repo = _repository(
        tmp_path,
        '<testcase classname="tests.system.test_workflow" name="test_nominal_workflow" time="1"/>'
        '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.01"/>',
    )
    monkeypatch.setattr("terractl.reporting.artifacts_root", lambda: repo / "artifacts")
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: repo / "artifacts")
    package = generate_evidence("unit-tampered", repo)
    report = package / "test-summary.md"
    report.write_text(report.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash does not match"):
        reconcile_evidence(package)


def test_an_unobserved_check_cannot_be_edited_into_a_pass(tmp_path: Path, monkeypatch) -> None:
    repo = _repository(
        tmp_path,
        '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.01"/>',
    )
    monkeypatch.setattr("terractl.reporting.artifacts_root", lambda: repo / "artifacts")
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: repo / "artifacts")
    package = generate_evidence("unit-unobserved", repo)
    path = package / "test-summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for record in payload["records"]:
        record["passed"] = True
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="unobserved checks cannot pass"):
        reconcile_evidence(package)


def test_the_manifest_records_environment_identity(tmp_path: Path, monkeypatch) -> None:
    repo = _repository(
        tmp_path,
        '<testcase classname="tests.system.test_workflow" name="test_nominal_workflow" time="1"/>'
        '<testcase classname="tests.unit.test_hashing" name="test_sha256_file" time="0.01"/>',
    )
    monkeypatch.setattr("terractl.reporting.artifacts_root", lambda: repo / "artifacts")
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: repo / "artifacts")
    package = generate_evidence("unit-manifest", repo)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "unit-manifest"
    assert set(manifest["environment"]) == {
        "compose_project",
        "software_revision",
        "python_version",
        "platform",
    }
    assert set(manifest["files"]) == {
        "test-summary.json",
        "test-summary.md",
        "requirements-verification.csv",
        "junit.xml",
    }
