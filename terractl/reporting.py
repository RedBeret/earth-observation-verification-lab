"""Build the single verification model that every evidence format is rendered from.

Raw runner output is the only source of truth. A requirement whose automated test is
absent from that output is reported as `not observed`, which fails. Nothing here can
promote a missing result into a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

from terractl.environment import artifacts_root, project_root
from terractl.evidence import render_evidence
from terractl.models import VerificationRecord, VerificationSummary

PARAMETER_SUFFIX = re.compile(r"\[.*\]$")


@dataclass(frozen=True)
class TestOutcome:
    node_id: str
    passed: bool
    duration_ms: int
    source: str


def _node_id(classname: str, name: str) -> str:
    module = classname.replace(".", "/")
    return f"{module}.py::{PARAMETER_SUFFIX.sub('', name)}"


def parse_junit(path: Path) -> dict[str, TestOutcome]:
    """Read one JUnit file. Later parameter cases fold into their base node id."""
    outcomes: dict[str, TestOutcome] = {}
    root = ElementTree.parse(path).getroot()
    for case in root.iter("testcase"):
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        if not classname or not name:
            continue
        node_id = _node_id(classname, name)
        failed = any(child.tag in {"failure", "error"} for child in case)
        skipped = any(child.tag == "skipped" for child in case)
        duration_ms = int(float(case.attrib.get("time", "0")) * 1000)
        previous = outcomes.get(node_id)
        passed = not failed and not skipped
        if previous is not None:
            passed = previous.passed and passed
            duration_ms += previous.duration_ms
        outcomes[node_id] = TestOutcome(node_id, passed, duration_ms, path.name)
    return outcomes


def collect_outcomes(root: Path | None = None) -> dict[str, TestOutcome]:
    junit_root = (root or project_root()) / "artifacts" / "junit"
    if not junit_root.is_dir():
        raise ValueError("no JUnit results exist; run a test level first")
    files = sorted(junit_root.glob("*.xml"))
    if not files:
        raise ValueError("no JUnit results exist; run a test level first")
    merged: dict[str, TestOutcome] = {}
    for path in files:
        for node_id, outcome in parse_junit(path).items():
            previous = merged.get(node_id)
            if previous is None or (previous.passed and not outcome.passed):
                merged[node_id] = outcome
    return merged


def load_requirements(root: Path | None = None) -> list[dict[str, Any]]:
    repo = root or project_root()
    document = yaml.safe_load(
        (repo / "requirements" / "system-requirements.yaml").read_text(encoding="utf-8")
    )
    requirements = document["requirements"]
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("system requirements are empty")
    return [dict(item) for item in requirements]


def build_summary(run_id: str, root: Path | None = None) -> VerificationSummary:
    repo = root or project_root()
    outcomes = collect_outcomes(repo)
    records: list[VerificationRecord] = []
    for requirement in load_requirements(repo):
        procedure_ids = requirement.get("procedure_ids") or ["not observed"]
        for node_id in requirement.get("automated_tests") or []:
            outcome = outcomes.get(str(node_id))
            observed = outcome is not None
            records.append(
                VerificationRecord(
                    requirement_id=str(requirement["id"]),
                    procedure_id=str(procedure_ids[0]),
                    check_id=str(node_id),
                    expected=str(requirement["statement"]),
                    observed=("passed" if outcome and outcome.passed else "failed")
                    if observed
                    else None,
                    observation_status="observed" if observed else "not observed",
                    passed=bool(outcome and outcome.passed),
                    duration_ms=outcome.duration_ms if outcome else 0,
                    evidence_path=(
                        f"artifacts/junit/{outcome.source}" if outcome else "artifacts/junit/"
                    ),
                )
            )
    if not records:
        raise ValueError("requirements declare no automated tests")
    return VerificationSummary(run_id=run_id, records=records)


def generate_evidence(run_id: str | None = None, root: Path | None = None) -> Path:
    identifier = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = build_summary(identifier, root)
    package = render_evidence(summary, artifacts_root() / "evidence" / identifier)
    return package
