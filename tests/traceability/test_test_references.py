"""TST-002: every automated system or integration test names what it is there for.

A system or integration test is expensive to run and slow to debug, so one that does not
say which requirement it exists for tends to survive long after the reason for it has
gone. The resilience suite already records requirement ids alongside its observations.
This applies the same rule to the other two high level suites.

Verifies: TST-002
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from terractl.environment import project_root

pytestmark = [pytest.mark.unit, pytest.mark.static]

REQUIREMENT_PATTERN = re.compile(r"\b(?:ING|CAT|EVT|COR|API|RES|SEC|EVD|TST)-\d{3}\b")
HIGH_LEVEL_SUITES = ("system", "integration", "resilience")


def _modules() -> list[Path]:
    root = project_root() / "tests"
    modules: list[Path] = []
    for suite in HIGH_LEVEL_SUITES:
        modules.extend(sorted((root / suite).glob("test_*.py")))
    return modules


def test_the_high_level_suites_exist() -> None:
    """Guard the guard. If the suites move, this file must fail rather than pass over an
    empty list and report success while checking nothing."""
    assert _modules(), "no system, integration, or resilience test modules were found"


@pytest.mark.parametrize("module", _modules(), ids=lambda path: path.name)
def test_requirement_markers(module: Path) -> None:
    text = module.read_text(encoding="utf-8")
    referenced = sorted(set(REQUIREMENT_PATTERN.findall(text)))
    assert referenced, (
        f"{module.relative_to(project_root()).as_posix()} names no requirement. "
        "Add the requirement ids it verifies to the module docstring."
    )


def test_the_checker_rejects_a_module_with_no_reference(tmp_path: Path) -> None:
    """Prove the check can fail, so a passing run means something."""
    module = tmp_path / "test_unreferenced.py"
    module.write_text('"""No requirement here."""\n', encoding="utf-8")
    assert REQUIREMENT_PATTERN.findall(module.read_text(encoding="utf-8")) == []
