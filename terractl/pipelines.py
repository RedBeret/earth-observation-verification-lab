"""The canonical CI gate sequence and the parity rules every pipeline must satisfy.

Jenkins, GitHub Actions, and GitLab are orchestration only. They call the same
repository entrypoints in the same order, so a green pipeline and a green local run
mean the same thing.
"""

from __future__ import annotations

import re
from pathlib import Path

from terractl.environment import project_root

PIPELINE_FILES: dict[str, str] = {
    "github": ".github/workflows/verification.yml",
    "jenkins": "Jenkinsfile",
    "gitlab": ".gitlab-ci.yml",
}

REQUIRED_GATES: tuple[str, ...] = (
    "./scripts/bootstrap.sh",
    "./scripts/terra.sh doctor",
    "./scripts/terra.sh validate",
    "./scripts/terra.sh traceability",
    "./scripts/terra.sh test unit",
    "./scripts/terra.sh test contract --mode static",
    "./scripts/terra.sh test security",
    "./scripts/terra.sh test pipeline",
    "./scripts/terra.sh up",
    "./scripts/terra.sh status",
    "./scripts/terra.sh test integration",
    "./scripts/terra.sh procedure run TP-ING-002",
    "./scripts/terra.sh procedure run TP-API-004",
    "./scripts/terra.sh procedure run TP-SYS-001",
    "./scripts/terra.sh test contract --mode postman",
    "./scripts/terra.sh test performance",
    "./scripts/terra.sh procedure run TP-RES-003",
    "./scripts/terra.sh test resilience",
    "./scripts/terra.sh procedure run TP-EVD-005",
    "./scripts/terra.sh evidence",
)

# These must run whether the gates passed or failed.
ALWAYS_RUN_COMMANDS: tuple[str, ...] = (
    "./scripts/terra.sh diagnostics",
    "./scripts/terra.sh down",
)

# Static contract checks run before the environment exists; the Postman phase runs
# against the started system. Every pipeline must document that split.
STATIC_CONTRACT_GATE = "./scripts/terra.sh test contract --mode static"
RUNNING_CONTRACT_GATE = "./scripts/terra.sh test contract --mode postman"

ENTRYPOINT_PATTERN = re.compile(r"\./scripts/(?:bootstrap\.sh|terra\.sh)[^\n\"']*")
SECRET_REFERENCE_PATTERN = re.compile(
    r"secrets\.[A-Za-z_][A-Za-z0-9_]*|credentials\(|CI_JOB_TOKEN|CI_REGISTRY_PASSWORD"
)
LENIENT_FAILURE_PATTERN = re.compile(
    r"continue-on-error:\s*true|allow_failure:\s*true|allowEmptyArchive:\s*true"
)


def pipeline_path(name: str, root: Path | None = None) -> Path:
    try:
        relative = PIPELINE_FILES[name]
    except KeyError as error:
        raise ValueError(f"unknown pipeline: {name}") from error
    return (root or project_root()) / relative


def pipeline_text(name: str, root: Path | None = None) -> str:
    return pipeline_path(name, root).read_text(encoding="utf-8")


def pipeline_commands(text: str) -> list[str]:
    """Return every repository entrypoint invocation in the order it appears."""
    return [match.strip().rstrip("'\"") for match in ENTRYPOINT_PATTERN.findall(text)]


def gate_sequence(text: str) -> list[str]:
    """Required gates in first-appearance order.

    A runner may restart the environment for each of its jobs, so a repeated gate is
    not a parity difference. The order in which each gate first runs is.
    """
    seen: list[str] = []
    for command in pipeline_commands(text):
        if command in REQUIRED_GATES and command not in seen:
            seen.append(command)
    return seen


def missing_gates(text: str) -> list[str]:
    commands = pipeline_commands(text)
    return [gate for gate in REQUIRED_GATES if gate not in commands]


def gates_out_of_order(text: str) -> list[str]:
    """Report any required gate that appears before the gate it must follow."""
    commands = pipeline_commands(text)
    positions = {gate: commands.index(gate) for gate in REQUIRED_GATES if gate in commands}
    ordered = [gate for gate in REQUIRED_GATES if gate in positions]
    problems: list[str] = []
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if positions[earlier] > positions[later]:
            problems.append(f"{later} runs before {earlier}")
    return problems


def unsafe_secret_references(text: str) -> list[str]:
    """This lab generates its own local credentials, so no pipeline may need a secret."""
    return sorted({match for match in SECRET_REFERENCE_PATTERN.findall(text)})


def lenient_failure_settings(text: str) -> list[str]:
    return sorted(set(LENIENT_FAILURE_PATTERN.findall(text)))
