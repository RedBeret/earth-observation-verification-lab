"""Multi-format evidence rendering and reconciliation."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from terractl.environment import artifacts_root, compose_project_name, repository_revision
from terractl.models import VerificationSummary
from terractl.safety import redact_text, redact_value, safe_artifact_path

MANIFEST_NAME = "manifest.json"
RENDERED_NAMES = (
    "test-summary.json",
    "test-summary.md",
    "requirements-verification.csv",
    "junit.xml",
)


def render_evidence(summary: VerificationSummary, output: Path | None = None) -> Path:
    package = safe_artifact_path(
        output or artifacts_root() / "evidence" / summary.run_id,
        artifacts_root(),
    )
    package.mkdir(parents=True, exist_ok=True)
    payload = redact_value(summary.model_dump(mode="json"))
    (package / "test-summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    markdown = [
        f"# Verification summary: {summary.run_id}",
        "",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        f"- Total: {summary.total}",
        "",
        "| Requirement | Check | Observation | Result |",
        "|---|---|---|---|",
    ]
    for record in summary.records:
        observation = (
            "not observed" if record.observation_status == "not observed" else str(record.observed)
        )
        markdown.append(
            f"| {record.requirement_id} | {record.check_id} | "
            f"{redact_text(observation)} | {'PASS' if record.passed else 'FAIL'} |"
        )
    (package / "test-summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    with (package / "requirements-verification.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "requirement_id",
                "procedure_id",
                "check_id",
                "expected",
                "observed",
                "observation_status",
                "passed",
                "duration_ms",
                "evidence_path",
            ],
        )
        writer.writeheader()
        for record in summary.records:
            writer.writerow(redact_value(record.model_dump(mode="json")))

    suite = ElementTree.Element(
        "testsuite",
        name="terrawatch-verification",
        tests=str(summary.total),
        failures=str(summary.failed),
        skipped="0",
    )
    for record in summary.records:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname=record.requirement_id,
            name=record.check_id,
            time=f"{record.duration_ms / 1000:.3f}",
        )
        if not record.passed:
            failure = ElementTree.SubElement(case, "failure", message="verification failed")
            failure.text = redact_text(
                f"expected={record.expected!r}; observed={record.observed!r}"
            )
    ElementTree.ElementTree(suite).write(
        package / "junit.xml",
        encoding="utf-8",
        xml_declaration=True,
    )
    write_manifest(package, summary)
    reconcile_evidence(package)
    return package


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_manifest(package: Path, summary: VerificationSummary) -> Path:
    """Record file hashes and environment identity so evidence cannot be edited quietly."""
    manifest = {
        "schema_version": "1.0.0",
        "run_id": summary.run_id,
        "generated_at": summary.generated_at.isoformat(),
        "environment": {
            "compose_project": compose_project_name(),
            "software_revision": repository_revision(),
            "python_version": platform.python_version(),
            "platform": sys.platform,
        },
        "totals": {
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
        },
        "files": {
            name: file_digest(package / name)
            for name in RENDERED_NAMES
            if (package / name).is_file()
        },
    }
    path = package / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def reconcile_evidence(package: Path) -> dict[str, int]:
    missing = [name for name in RENDERED_NAMES if not (package / name).is_file()]
    if missing:
        raise ValueError(f"evidence package is missing: {sorted(missing)}")

    json_payload = json.loads((package / "test-summary.json").read_text(encoding="utf-8"))
    records = json_payload["records"]
    if not records:
        raise ValueError("zero checks cannot reconcile")
    json_total = len(records)
    json_failed = sum(not record["passed"] for record in records)

    unobserved_passes = [
        record["check_id"]
        for record in records
        if record["observation_status"] == "not observed" and record["passed"]
    ]
    if unobserved_passes:
        raise ValueError(f"unobserved checks cannot pass: {sorted(unobserved_passes)}")

    with (package / "requirements-verification.csv").open(encoding="utf-8", newline="") as handle:
        csv_total = sum(1 for _ in csv.DictReader(handle))

    junit_root = ElementTree.parse(package / "junit.xml").getroot()
    junit_total = int(junit_root.attrib["tests"])
    junit_failed = int(junit_root.attrib["failures"])
    if len({json_total, csv_total, junit_total}) != 1:
        raise ValueError("evidence totals do not agree")
    if json_failed != junit_failed:
        raise ValueError("evidence failures do not agree")

    for name in RENDERED_NAMES:
        text = (package / name).read_text(encoding="utf-8")
        if redact_text(text) != text:
            raise ValueError(f"evidence redaction failed for {name}")

    manifest_path = package / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError("evidence package has no manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        observed = file_digest(package / name)
        if observed != expected:
            raise ValueError(f"evidence manifest hash does not match {name}")
    if manifest["totals"]["total"] != json_total:
        raise ValueError("evidence manifest totals do not agree")

    return {"total": json_total, "failed": json_failed, "passed": json_total - json_failed}


def classify_failures(records: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Split records into checks that ran and failed, and checks that never ran.

    The two are not interchangeable. A check that executed and failed is a defect and must
    always stop a release. A check that never executed is an absence of information, which
    the project reports as `not observed` and may choose to publish alongside.
    """
    executed_failures = sorted(
        record["check_id"]
        for record in records
        if record["observation_status"] != "not observed" and not record["passed"]
    )
    unobserved = sorted(
        record["check_id"] for record in records if record["observation_status"] == "not observed"
    )
    return executed_failures, unobserved
