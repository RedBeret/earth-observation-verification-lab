import json
from pathlib import Path

import pytest

from terractl.diagnostics import _redact, collect_diagnostics

pytestmark = pytest.mark.unit


def test_diagnostic_collection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.diagnostics.artifacts_root", lambda: tmp_path)
    monkeypatch.setattr(
        "terractl.diagnostics._capture",
        lambda command, timeout=30: {
            "command": command,
            "returncode": 0,
            "stdout": "{}",
            "stderr": "",
        },
    )
    output = collect_diagnostics("unit-diagnostics")
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "unit-diagnostics"
    assert payload["git_revision"]
    assert payload["doctor"]["checks"]
    assert (output / "compose-ps.json").is_file()
    assert (output / "service-logs.txt").is_file()


def test_diagnostic_run_id_cannot_escape_artifact_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.diagnostics.artifacts_root", lambda: tmp_path)
    with pytest.raises(ValueError, match="unsafe"):
        collect_diagnostics("../../outside")


def test_diagnostic_redaction_uses_local_secret_values(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env.local").write_text(
        "NATS_TOKEN=unit-secret-value\nPOSTGRES_USER=terrawatch\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("terractl.diagnostics.project_root", lambda: tmp_path)
    assert _redact("connected with unit-secret-value") == "connected with [REDACTED]"
