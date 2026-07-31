import json
from pathlib import Path

import pytest

from terractl.diagnostics import collect_diagnostics

pytestmark = pytest.mark.unit


def test_diagnostic_collection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("terractl.diagnostics.artifacts_root", lambda: tmp_path)
    output = collect_diagnostics("unit-diagnostics")
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "unit-diagnostics"
    assert payload["git_revision"]
    assert payload["doctor"]["checks"]
