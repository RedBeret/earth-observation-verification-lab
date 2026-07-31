"""Identity-guarded Docker Compose lifecycle operations."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from terractl.environment import initialize_environment, project_root
from terractl.safety import assert_project_identity


@dataclass(frozen=True)
class ComposeResult:
    returncode: int
    stdout: str
    stderr: str


def _collect_lifecycle_failure(context: str) -> None:
    try:
        from terractl.diagnostics import collect_failure_diagnostics

        print(f"Failure diagnostics: {collect_failure_diagnostics(context)}")
    except Exception as error:
        print(f"Diagnostic collection failed: {type(error).__name__}")


def _local_values() -> dict[str, str]:
    path = initialize_environment()
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def compose_project() -> str:
    return _local_values()["COMPOSE_PROJECT_NAME"]


def compose_command(*arguments: str, include_test: bool = False) -> list[str]:
    command = [
        "docker",
        "compose",
        "--env-file",
        ".env.local",
        "-f",
        "compose.yml",
    ]
    if include_test:
        command.extend(["-f", "compose.test.yml"])
    return [*command, *arguments]


def run_compose(
    *arguments: str,
    include_test: bool = False,
    timeout: int = 300,
) -> ComposeResult:
    process = subprocess.run(
        compose_command(*arguments, include_test=include_test),
        cwd=project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return ComposeResult(process.returncode, process.stdout, process.stderr)


def compose_up() -> int:
    initialize_environment()
    result = run_compose(
        "up",
        "-d",
        "--build",
        "--wait",
        "--wait-timeout",
        "180",
        timeout=600,
    )
    print(result.stdout, end="")
    if result.returncode:
        print(result.stderr, end="")
        _collect_lifecycle_failure("startup")
    return result.returncode


def _parse_ps(output: str) -> list[dict[str, Any]]:
    stripped = output.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return [json.loads(line) for line in stripped.splitlines() if line.strip()]
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError("unexpected docker compose ps output")


def compose_status() -> int:
    result = run_compose("ps", "--all", "--format", "json", timeout=30)
    if result.returncode:
        print(result.stderr, end="")
        _collect_lifecycle_failure("status")
        return result.returncode
    services = _parse_ps(result.stdout)
    required_running = {
        "postgres",
        "minio",
        "nats",
        "ingest-api",
        "event-api",
        "analysis-api",
        "imagery-worker",
        "correlation-worker",
    }
    running = {
        str(service.get("Service"))
        for service in services
        if str(service.get("State", "")).lower() == "running"
    }
    missing = sorted(required_running - running)
    payload = {
        "compose_project": compose_project(),
        "services": services,
        "required_running": sorted(required_running),
        "missing_or_stopped": missing,
        "passed": not missing,
    }
    print(json.dumps(payload, indent=2))
    if missing:
        _collect_lifecycle_failure("readiness")
    return 0 if not missing else 1


def assert_environment_green() -> None:
    result = run_compose("ps", "--all", "--format", "json", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "unable to inspect environment")
    services = {str(item.get("Service")): item for item in _parse_ps(result.stdout)}
    required_running = {
        "postgres",
        "minio",
        "nats",
        "ingest-api",
        "event-api",
        "analysis-api",
        "imagery-worker",
        "correlation-worker",
    }
    required_healthy = {
        "postgres",
        "minio",
        "nats",
        "ingest-api",
        "event-api",
        "analysis-api",
    }
    for service in required_running:
        item = services.get(service)
        if item is None or str(item.get("State", "")).lower() != "running":
            raise RuntimeError(f"required service is not running: {service}")
        if service in required_healthy and str(item.get("Health", "")).lower() != "healthy":
            raise RuntimeError(f"required service is not healthy: {service}")


def project_container_ids() -> list[str]:
    process = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={compose_project()}",
        ],
        cwd=project_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "unable to list project containers")
    return [line for line in process.stdout.splitlines() if line]


def verify_project_containers() -> list[str]:
    identifiers = project_container_ids()
    for identifier in identifiers:
        process = subprocess.run(
            ["docker", "inspect", identifier, "--format", "{{json .Config.Labels}}"],
            cwd=project_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(f"unable to inspect container {identifier}")
        labels = json.loads(process.stdout)
        assert_project_identity(labels, compose_project())
    return identifiers


def compose_down() -> int:
    identifiers = verify_project_containers()
    if not identifiers:
        print("No labeled project containers exist; nothing to remove.")
        return 0
    result = run_compose("down", "--volumes", "--remove-orphans", "--timeout", "30", timeout=120)
    print(result.stdout, end="")
    if result.returncode:
        print(result.stderr, end="")
        _collect_lifecycle_failure("teardown")
        return result.returncode
    survivors = project_container_ids()
    if survivors:
        print(f"Project containers survived teardown: {survivors}")
        _collect_lifecycle_failure("teardown-survivors")
        return 1
    print(f"Removed {len(identifiers)} verified project containers.")
    return 0


def rendered_compose_config() -> dict[str, Any]:
    result = run_compose("config", "--format", "json", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return cast(dict[str, Any], json.loads(result.stdout))


def assert_loopback_ports(config: dict[str, Any]) -> None:
    for service_name, service in config.get("services", {}).items():
        for port in service.get("ports", []):
            host_ip = port.get("host_ip")
            if host_ip != "127.0.0.1":
                raise ValueError(f"{service_name} publishes a non-loopback port: {host_ip}")


def project_path() -> Path:
    return project_root()
