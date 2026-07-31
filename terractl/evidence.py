"""Multi-format evidence rendering and reconciliation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.etree import ElementTree

from terractl.environment import artifacts_root
from terractl.models import VerificationSummary
from terractl.safety import redact_text, redact_value, safe_artifact_path


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
        f"# Verification summary — {summary.run_id}",
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
            "not observed"
            if record.observation_status == "not observed"
            else str(record.observed)
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
    reconcile_evidence(package)
    return package


def reconcile_evidence(package: Path) -> dict[str, int]:
    json_payload = json.loads((package / "test-summary.json").read_text(encoding="utf-8"))
    records = json_payload["records"]
    if not records:
        raise ValueError("zero checks cannot reconcile")
    json_total = len(records)
    json_failed = sum(not record["passed"] for record in records)

    with (package / "requirements-verification.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        csv_total = sum(1 for _ in csv.DictReader(handle))

    junit_root = ElementTree.parse(package / "junit.xml").getroot()
    junit_total = int(junit_root.attrib["tests"])
    junit_failed = int(junit_root.attrib["failures"])
    if len({json_total, csv_total, junit_total}) != 1:
        raise ValueError("evidence totals do not agree")
    if json_failed != junit_failed:
        raise ValueError("evidence failures do not agree")
    return {"total": json_total, "failed": json_failed, "passed": json_total - json_failed}
