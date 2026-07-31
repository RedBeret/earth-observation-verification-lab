"""Environment capability checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass

from terractl.environment import project_root


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str
    required: bool = True


def _command_version(command: list[str]) -> tuple[bool, str]:
    executable = shutil.which(command[0])
    if not executable:
        return False, "not found"
    process = subprocess.run(
        command,
        cwd=project_root(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    output = (process.stdout or process.stderr).strip().splitlines()
    return process.returncode == 0, output[0] if output else f"exit {process.returncode}"


def run_doctor() -> list[Check]:
    python_ok = sys.version_info[:2] == (3, 12)
    git_ok, git_version = _command_version(["git", "--version"])
    docker_ok, docker_version = _command_version(["docker", "--version"])
    compose_ok, compose_version = _command_version(["docker", "compose", "version"])
    daemon_ok, daemon_detail = _command_version(
        ["docker", "version", "--format", "{{.Server.Version}}"]
    )
    return [
        Check("python", python_ok, sys.version.split()[0]),
        Check("git", git_ok, git_version),
        Check("docker-cli", docker_ok, docker_version),
        Check("docker-compose", compose_ok, compose_version),
        Check("docker-engine", daemon_ok, daemon_detail, required=False),
        Check("project-root", (project_root() / "pyproject.toml").is_file(), str(project_root())),
    ]


def doctor_payload() -> dict[str, object]:
    checks = run_doctor()
    return {
        "checks": [asdict(check) for check in checks],
        "passed": all(check.passed for check in checks if check.required),
    }


def print_doctor() -> bool:
    payload = doctor_payload()
    print(json.dumps(payload, indent=2))
    return bool(payload["passed"])
