"""TerraWatch operator command line."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from terractl.clean_room import clean_room_proof
from terractl.contract import run_newman
from terractl.diagnostics import collect_diagnostics, collect_failure_diagnostics
from terractl.doctor import print_doctor
from terractl.environment import ensure_artifact_directories, project_root
from terractl.evidence import classify_failures
from terractl.faults import FAULT_NAMES, clear_faults, inject_fault
from terractl.lifecycle import compose_down, compose_status, compose_up
from terractl.locking import exclusive_run_lock
from terractl.performance import run_performance
from terractl.procedures import run_procedure
from terractl.reporting import generate_evidence
from terractl.reset import reset_plan, reset_project
from terractl.security import run_security_gate
from terractl.traceability import validate_traceability
from terractl.validation import validate_repository

app = typer.Typer(no_args_is_help=True, help="TerraWatch local operator interface.")
test_app = typer.Typer(no_args_is_help=True, help="Run a verification test level.")
procedure_app = typer.Typer(no_args_is_help=True, help="Validate or execute a formal procedure.")
fault_app = typer.Typer(no_args_is_help=True, help="List, inject, or clear controlled faults.")
app.add_typer(test_app, name="test")
app.add_typer(procedure_app, name="procedure")
app.add_typer(fault_app, name="fault")


def _run(command: list[str], failure_context: str = "command") -> int:
    process = subprocess.run(command, cwd=project_root(), check=False)
    if process.returncode:
        try:
            print(f"Failure diagnostics: {collect_failure_diagnostics(failure_context)}")
        except Exception as error:
            print(f"Diagnostic collection failed: {type(error).__name__}")
    return process.returncode


def _pytest_selection(expression: str, label: str) -> int:
    ensure_artifact_directories()
    output = project_root() / "artifacts" / "junit" / f"{label}.xml"
    return _run(
        [
            str(Path(__import__("sys").executable)),
            "-m",
            "pytest",
            "-m",
            expression,
            f"--junitxml={output}",
        ],
        failure_context=f"test-{label}",
    )


def _pytest(level: str) -> int:
    ensure_artifact_directories()
    output = project_root() / "artifacts" / "junit" / f"{level}.xml"
    command = [
        str(Path(__import__("sys").executable)),
        "-m",
        "pytest",
        "-m",
        level,
        f"--junitxml={output}",
    ]
    if level in {"system", "resilience"}:
        lock_path = project_root() / "artifacts" / "state" / "system-tests.lock"
        try:
            with exclusive_run_lock(lock_path):
                return _run(command, failure_context=f"test-{level}")
        except RuntimeError:
            print("Another system or resilience run holds the project lock.")
            return 2
    return _run(command, failure_context=f"test-{level}")


@app.command()
def doctor() -> None:
    """Inspect required tools without changing the environment."""
    if not print_doctor():
        raise typer.Exit(1)


@app.command()
def validate() -> None:
    """Validate repository schemas, procedures, and traceability."""
    print(json.dumps(validate_repository(), indent=2))


@app.command()
def traceability() -> None:
    """Fail on missing, stale, or invalid requirement mappings."""
    result = validate_traceability()
    print(
        json.dumps(
            {
                "requirements": result.requirements,
                "mapped_requirements": result.mapped_requirements,
                "errors": result.errors,
                "passed": result.passed,
            },
            indent=2,
        )
    )
    if not result.passed:
        raise typer.Exit(1)


@app.command()
def seed() -> None:
    """Generate the deterministic canonical test data."""
    code = _run(
        [
            str(Path(__import__("sys").executable)),
            "-m",
            "data.generators.generate_expected_results",
            "--output",
            "data",
        ],
        failure_context="seed",
    )
    raise typer.Exit(code)


@app.command()
def up() -> None:
    raise typer.Exit(compose_up())


@app.command()
def status() -> None:
    raise typer.Exit(compose_status())


@app.command()
def down() -> None:
    raise typer.Exit(compose_down())


@app.command()
def reset(apply: bool = typer.Option(False, "--apply")) -> None:
    """Tear the project down and remove what teardown leaves behind.

    Reports what it would remove and changes nothing unless `--apply` is given, because
    this deletes the evidence from the last run.
    """
    plan = reset_plan()
    if not apply:
        print(json.dumps({**plan, "applied": False}, indent=2, sort_keys=True))
        print("Refusing to reset without --apply.")
        raise typer.Exit(2)
    code = compose_down()
    if code:
        raise typer.Exit(code)
    try:
        removed = reset_project()
    except Exception as error:
        print(f"Reset failed: {type(error).__name__}")
        raise typer.Exit(1) from error
    print(json.dumps({**removed, "applied": True}, indent=2, sort_keys=True))


@app.command(name="clean-room")
def clean_room() -> None:
    try:
        print(clean_room_proof(create_verification_sentinel=True))
    except Exception as error:
        print(f"Clean-room proof failed: {type(error).__name__}")
        raise typer.Exit(1) from error


@app.command()
def evidence(
    run_id: Annotated[str | None, typer.Option(help="Existing run identifier.")] = None,
    allow_unobserved: Annotated[
        bool,
        typer.Option(
            "--allow-unobserved",
            help="Exit zero when the package reconciles and every failure is a missing "
            "observation. A requirement whose test ran and failed still exits non-zero.",
        ),
    ] = False,
) -> None:
    """Render and reconcile evidence from collected test results."""
    ensure_artifact_directories()
    try:
        package = generate_evidence(run_id)
    except ValueError as error:
        print(f"Evidence generation failed: {error}")
        raise typer.Exit(1) from error
    summary = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps(summary["totals"], indent=2, sort_keys=True))
    print(f"Evidence package: {package.relative_to(project_root())}")

    records = json.loads((package / "test-summary.json").read_text(encoding="utf-8"))["records"]
    executed_failures, unobserved = classify_failures(records)

    # A test that ran and failed is a real failure and always fails the command. Only a
    # missing observation can be waived, and only when the caller asks for it.
    if executed_failures:
        print(f"Executed checks that failed: {len(executed_failures)}")
        raise typer.Exit(1)
    if unobserved:
        print(f"Requirements not observed: {len(unobserved)} of {len(records)}")
        if not allow_unobserved:
            raise typer.Exit(1)


@app.command()
def diagnostics(
    run_id: Annotated[str | None, typer.Option(help="Existing run identifier.")] = None,
) -> None:
    identifier = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    print(collect_diagnostics(identifier))


@test_app.command("unit")
def test_unit() -> None:
    raise typer.Exit(_pytest("unit"))


@test_app.command("contract")
def test_contract(
    mode: Annotated[str, typer.Option(help="static, postman, or all")] = "all",
) -> None:
    if mode not in {"static", "postman", "all"}:
        raise typer.BadParameter("mode must be static, postman, or all")
    if mode == "static":
        raise typer.Exit(_pytest_selection("contract and static", "contract-static"))
    if mode == "postman":
        raise typer.Exit(run_newman())
    code = _pytest("contract")
    if code:
        raise typer.Exit(code)
    raise typer.Exit(run_newman())


@test_app.command("integration")
def test_integration() -> None:
    raise typer.Exit(_pytest("integration"))


@test_app.command("system")
def test_system() -> None:
    raise typer.Exit(_pytest("system"))


@test_app.command("resilience")
def test_resilience() -> None:
    raise typer.Exit(_pytest("resilience"))


@test_app.command("performance")
def test_performance() -> None:
    raise typer.Exit(run_performance())


@test_app.command("security")
def test_security() -> None:
    raise typer.Exit(run_security_gate())


@test_app.command("pipeline")
def test_pipeline() -> None:
    raise typer.Exit(_pytest("pipeline"))


@test_app.command("all")
def test_all() -> None:
    levels = ("unit", "contract", "integration", "system", "resilience", "pipeline", "security")
    for level in levels:
        code = _pytest(level)
        if code:
            raise typer.Exit(code)


@procedure_app.command("run")
def procedure_run(procedure_id: str) -> None:
    raise typer.Exit(run_procedure(procedure_id))


@fault_app.command("list")
def fault_list() -> None:
    print("\n".join(FAULT_NAMES))


@fault_app.command("inject")
def fault_inject(name: str, apply: bool = typer.Option(False, "--apply")) -> None:
    if name not in FAULT_NAMES:
        raise typer.BadParameter("unknown fault")
    if not apply:
        print(f"Refusing to inject {name} without --apply.")
        raise typer.Exit(2)
    try:
        print(json.dumps(inject_fault(name), indent=2))
    except Exception as error:
        print(f"Fault injection failed: {type(error).__name__}")
        try:
            print(f"Failure diagnostics: {collect_failure_diagnostics(f'fault-{name}')}")
        except Exception as diagnostic_error:
            print(f"Diagnostic collection failed: {type(diagnostic_error).__name__}")
        raise typer.Exit(1) from error


@fault_app.command("clear")
def fault_clear(apply: bool = typer.Option(False, "--apply")) -> None:
    if not apply:
        print("Refusing to clear faults without --apply.")
        raise typer.Exit(2)
    try:
        print(json.dumps(clear_faults(), indent=2))
    except Exception as error:
        print(f"Fault clearing failed: {type(error).__name__}")
        try:
            print(f"Failure diagnostics: {collect_failure_diagnostics('fault-clear')}")
        except Exception as diagnostic_error:
            print(f"Diagnostic collection failed: {type(diagnostic_error).__name__}")
        raise typer.Exit(1) from error


if __name__ == "__main__":
    app()
