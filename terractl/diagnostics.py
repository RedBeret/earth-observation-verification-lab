"""Sanitized local diagnostic collection for success and failure paths."""

from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from terractl.doctor import doctor_payload
from terractl.environment import artifacts_root, project_root
from terractl.lifecycle import compose_command
from terractl.safety import redact_text, redact_value, safe_artifact_path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SENSITIVE_ENV_MARKERS = (
    "PASSWORD",
    "TOKEN",
    "SECRET",
    "ACCESS_KEY",
    "ROOT_USER",
)


def _git_revision() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "not observed"


def _local_secrets() -> list[str]:
    path = project_root() / ".env.local"
    if not path.is_file():
        return []
    secrets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if value and any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS):
            secrets.append(value)
    return sorted(secrets, key=len, reverse=True)


def _redact(value: str) -> str:
    redacted = redact_text(value)
    for secret in _local_secrets():
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _capture(command: list[str], timeout: int = 30) -> dict[str, object]:
    try:
        process = subprocess.run(
            command,
            cwd=project_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "returncode": process.returncode,
            "stdout": _redact(process.stdout),
            "stderr": _redact(process.stderr),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": type(error).__name__,
        }


def collect_diagnostics(run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("diagnostic run ID contains unsafe characters")
    root = artifacts_root() / "diagnostics"
    output = safe_artifact_path(root / run_id, root)
    output.mkdir(parents=True, exist_ok=True)
    compose_ps = _capture(compose_command("ps", "--all", "--format", "json"))
    compose_logs = _capture(compose_command("logs", "--no-color", "--tail", "200"), timeout=60)
    docker_version = _capture(["docker", "version", "--format", "{{json .}}"])
    payload = {
        "run_id": run_id,
        "collected_at": datetime.now(UTC).isoformat(),
        "git_revision": _git_revision(),
        "platform": platform.platform(),
        "doctor": doctor_payload(),
        "commands": {
            "compose_ps": {
                "returncode": compose_ps["returncode"],
                "stderr": compose_ps["stderr"],
            },
            "compose_logs": {
                "returncode": compose_logs["returncode"],
                "stderr": compose_logs["stderr"],
            },
            "docker_version": docker_version,
        },
    }
    (output / "diagnostics.json").write_text(
        json.dumps(redact_value(payload), indent=2),
        encoding="utf-8",
    )
    (output / "compose-ps.json").write_text(
        str(compose_ps["stdout"]),
        encoding="utf-8",
    )
    (output / "service-logs.txt").write_text(
        str(compose_logs["stdout"]),
        encoding="utf-8",
    )
    return output


def collect_failure_diagnostics(context: str) -> Path:
    safe_context = re.sub(r"[^A-Za-z0-9._-]+", "-", context).strip("-") or "failure"
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{safe_context}"[:128]
    return collect_diagnostics(run_id)
