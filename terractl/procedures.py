"""Formal YAML procedure validation and execution registry."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import jsonschema  # type: ignore[import-untyped]
import yaml

from terractl.environment import ensure_artifact_directories, project_root
from terractl.locking import exclusive_run_lock

PROCEDURE_TEST_TARGETS: dict[str, tuple[str, ...]] = {
    "TP-API-004": (
        "contract",
        "tests/contract/test_event_contract.py",
        "tests/contract/test_analysis_contract.py",
    ),
    "TP-ING-002": ("contract", "tests/contract/test_ingest_contract.py"),
    "TP-SYS-001": ("system", "tests/system/test_workflow.py"),
}


def load_procedure(procedure_id: str, root: Path | None = None) -> dict[str, Any]:
    repo = root or project_root()
    path = repo / "procedures" / f"{procedure_id}.yaml"
    if not path.is_file():
        raise ValueError(f"unknown procedure: {procedure_id}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = yaml.safe_load(
        (repo / "requirements" / "schemas" / "test-procedure.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(document, schema)
    if document["id"] != procedure_id:
        raise ValueError("procedure file and document identifiers differ")
    return cast(dict[str, Any], document)


def validate_all_procedures(root: Path | None = None) -> list[str]:
    repo = root or project_root()
    identifiers: list[str] = []
    for path in sorted((repo / "procedures").glob("TP-*.yaml")):
        load_procedure(path.stem, repo)
        identifiers.append(path.stem)
    if not identifiers:
        raise ValueError("no procedures found")
    return identifiers


def run_procedure(procedure_id: str) -> int:
    document = load_procedure(procedure_id)
    print(f"{procedure_id} is valid with {len(document['steps'])} executable step definitions.")
    target = PROCEDURE_TEST_TARGETS.get(procedure_id)
    if target is None:
        print(f"{procedure_id} has no enabled execution handler in this implementation stage.")
        return 2
    marker, *test_paths = target
    ensure_artifact_directories()
    output = project_root() / "artifacts" / "junit" / f"procedure-{procedure_id}.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        marker,
        *test_paths,
        "-vv",
        f"--junitxml={output}",
    ]

    def execute() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            command,
            cwd=project_root(),
            check=False,
        )

    if procedure_id in {"TP-SYS-001", "TP-RES-003"}:
        lock_path = project_root() / "artifacts" / "state" / "system-tests.lock"
        try:
            with exclusive_run_lock(lock_path):
                process = execute()
        except RuntimeError:
            print("Another system or resilience run holds the project lock.")
            return 2
    else:
        process = execute()
    if process.returncode:
        try:
            from terractl.diagnostics import collect_failure_diagnostics

            print(
                f"Failure diagnostics: {collect_failure_diagnostics(f'procedure-{procedure_id}')}"
            )
        except Exception as error:
            print(f"Diagnostic collection failed: {type(error).__name__}")
    return process.returncode
