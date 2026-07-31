"""Sanitized local diagnostic collection."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from terractl.doctor import doctor_payload
from terractl.environment import artifacts_root, project_root
from terractl.safety import redact_text


def _git_revision() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "not observed"


def collect_diagnostics(run_id: str) -> Path:
    output = artifacts_root() / "diagnostics" / run_id
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "collected_at": datetime.now(UTC).isoformat(),
        "git_revision": _git_revision(),
        "platform": platform.platform(),
        "doctor": doctor_payload(),
    }
    (output / "diagnostics.json").write_text(
        redact_text(json.dumps(payload, indent=2)),
        encoding="utf-8",
    )
    return output
