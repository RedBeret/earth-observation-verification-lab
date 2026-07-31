"""Structural checks on the release scripts.

The clean checkout script has to run the same sequence as the pipelines, and the publish
gate has to run its checks before anything reaches a remote. Both properties are easy to
break by editing a script, so they are asserted rather than trusted.
"""

from __future__ import annotations

import pytest

from terractl.environment import project_root
from terractl.pipelines import REQUIRED_GATES, pipeline_commands

pytestmark = [pytest.mark.pipeline, pytest.mark.static]

CLEAN_CHECKOUT = project_root() / "scripts" / "verify-clean-checkout.sh"
PUBLISH_GATE = project_root() / "scripts" / "publish-gate.sh"
PUSH_MARKERS = ("git push", "gh repo create")


def _text(name: str) -> str:
    return (project_root() / "scripts" / name).read_text(encoding="utf-8")


def test_the_release_scripts_exist() -> None:
    assert CLEAN_CHECKOUT.is_file()
    assert PUBLISH_GATE.is_file()


@pytest.mark.parametrize("name", ["verify-clean-checkout.sh", "publish-gate.sh"])
def test_release_scripts_fail_fast(name: str) -> None:
    assert "set -euo pipefail" in _text(name)


@pytest.mark.parametrize("name", ["verify-clean-checkout.sh", "publish-gate.sh"])
def test_release_scripts_refuse_a_dirty_tree(name: str) -> None:
    text = _text(name)
    assert "git status --porcelain" in text
    assert "Refusing" in text


def test_the_clean_checkout_runs_every_required_gate() -> None:
    commands = pipeline_commands(_text("verify-clean-checkout.sh"))
    missing = [gate for gate in REQUIRED_GATES if gate not in commands]
    assert missing == []


def test_the_clean_checkout_proves_isolation_and_leaves_nothing_running() -> None:
    commands = pipeline_commands(_text("verify-clean-checkout.sh"))
    assert "./scripts/terra.sh clean-room" in commands
    assert commands[-1] == "./scripts/terra.sh down"


def test_the_clean_checkout_uses_a_separate_directory() -> None:
    text = _text("verify-clean-checkout.sh")
    assert "git clone" in text
    assert "mktemp -d" in text


def test_the_publish_gate_checks_before_it_pushes() -> None:
    lines = _text("publish-gate.sh").splitlines()
    checks = [
        index for index, line in enumerate(lines) if "./scripts/terra.sh test security" in line
    ]
    pushes = [
        index
        for index, line in enumerate(lines)
        if any(marker in line for marker in PUSH_MARKERS) and not line.strip().startswith("#")
    ]
    assert checks, "the publish gate never runs the security checks"
    assert pushes, "the publish gate never pushes"
    assert max(checks) < min(pushes)


def test_the_publish_gate_requires_reconciled_evidence() -> None:
    assert "./scripts/terra.sh evidence" in pipeline_commands(_text("publish-gate.sh"))


def test_the_publish_gate_pushes_the_stage_branches_in_order() -> None:
    text = _text("publish-gate.sh")
    stages = [
        "codex/stage-2-infrastructure",
        "codex/stage-3-imagery",
        "codex/stage-4-correlation",
        "codex/stage-5-resilience",
        "codex/stage-6-evidence",
        "codex/stage-7-ci",
        "codex/stage-8-release",
    ]
    positions = [text.index(stage) for stage in stages if stage in text]
    assert len(positions) == len(stages)
    assert positions == sorted(positions)
