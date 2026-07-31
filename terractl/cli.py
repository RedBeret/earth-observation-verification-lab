"""TerraWatch operator command line."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from terractl.diagnostics import collect_diagnostics
from terractl.doctor import print_doctor
from terractl.environment import ensure_artifact_directories, project_root
from terractl.faults import FAULT_NAMES
from terractl.lifecycle import unavailable
from terractl.procedures import run_procedure
from terractl.traceability import validate_traceability
from terractl.validation import validate_repository

app = typer.Typer(no_args_is_help=True, help="TerraWatch local operator interface.")
test_app = typer.Typer(no_args_is_help=True, help="Run a verification test level.")
procedure_app = typer.Typer(no_args_is_help=True, help="Validate or execute a formal procedure.")
fault_app = typer.Typer(no_args_is_help=True, help="List, inject, or clear controlled faults.")
app.add_typer(test_app, name="test")
app.add_typer(procedure_app, name="procedure")
app.add_typer(fault_app, name="fault")


def _run(command: list[str]) -> int:
    process = subprocess.run(command, cwd=project_root(), check=False)
    return process.returncode


def _pytest(level: str) -> int:
    ensure_artifact_directories()
    output = project_root() / "artifacts" / "junit" / f"{level}.xml"
    return _run(
        [
            str(Path(__import__("sys").executable)),
            "-m",
            "pytest",
            "-m",
            level,
            f"--junitxml={output}",
        ]
    )


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
        ]
    )
    raise typer.Exit(code)


@app.command()
def up() -> None:
    raise typer.Exit(unavailable("up"))


@app.command()
def status() -> None:
    raise typer.Exit(unavailable("status"))


@app.command()
def down() -> None:
    raise typer.Exit(unavailable("down"))


@app.command(name="clean-room")
def clean_room() -> None:
    raise typer.Exit(unavailable("clean-room"))


@app.command()
def evidence() -> None:
    """Generate evidence from collected test results."""
    print("Evidence aggregation is enabled in Stage 6.")
    raise typer.Exit(2)


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
    if mode == "postman":
        raise typer.Exit(unavailable("contract postman"))
    raise typer.Exit(_pytest("contract"))


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
    raise typer.Exit(unavailable("performance"))


@test_app.command("security")
def test_security() -> None:
    raise typer.Exit(_pytest("security"))


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
    raise typer.Exit(unavailable(f"fault inject {name}"))


@fault_app.command("clear")
def fault_clear(apply: bool = typer.Option(False, "--apply")) -> None:
    if not apply:
        print("Refusing to clear faults without --apply.")
        raise typer.Exit(2)
    raise typer.Exit(unavailable("fault clear"))


if __name__ == "__main__":
    app()
