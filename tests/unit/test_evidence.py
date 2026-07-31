import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from terractl.evidence import reconcile_evidence, render_evidence
from terractl.models import VerificationRecord, VerificationSummary

pytestmark = pytest.mark.unit


def _record(*, passed: bool = True, missing: bool = False) -> VerificationRecord:
    return VerificationRecord(
        requirement_id="COR-001",
        procedure_id="TP-SYS-001",
        check_id="correlation.spatial_match",
        expected=True,
        observed=None if missing else passed,
        observation_status="not observed" if missing else "observed",
        passed=passed,
        duration_ms=125,
        evidence_path="artifacts/evidence/example/test-summary.json",
    )


def test_zero_checks_fail() -> None:
    with pytest.raises(ValidationError, match="zero executed checks"):
        VerificationSummary(run_id="unit-zero", records=[])


def test_missing_observation_fails() -> None:
    record = _record(passed=True, missing=True)
    assert not record.passed
    assert record.observation_status == "not observed"
    assert record.observed is None


def test_all_formats_and_reconciliation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: tmp_path)
    summary = VerificationSummary(run_id="unit-formats", records=[_record()])
    package = render_evidence(summary, tmp_path / "evidence" / "unit-formats")
    assert {
        "test-summary.json",
        "test-summary.md",
        "requirements-verification.csv",
        "junit.xml",
    } <= {path.name for path in package.iterdir()}
    assert reconcile_evidence(package) == {"total": 1, "failed": 0, "passed": 1}


def test_reconciliation_detects_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: tmp_path)
    package = render_evidence(
        VerificationSummary(run_id="unit-mismatch", records=[_record()]),
        tmp_path / "evidence" / "unit-mismatch",
    )
    payload = json.loads((package / "test-summary.json").read_text(encoding="utf-8"))
    payload["records"].append(payload["records"][0])
    (package / "test-summary.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="totals do not agree"):
        reconcile_evidence(package)


def test_evidence_redacts_credential_shapes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.evidence.artifacts_root", lambda: tmp_path)
    record = _record()
    record.observed = "password=example-sensitive-value"
    package = render_evidence(
        VerificationSummary(run_id="unit-redaction", records=[record]),
        tmp_path / "evidence" / "unit-redaction",
    )
    combined = "\n".join(path.read_text(errors="ignore") for path in package.iterdir())
    assert "example-sensitive-value" not in combined
