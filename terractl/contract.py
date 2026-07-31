"""Postman contract collection loading and Newman execution."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from terractl.environment import artifacts_root, ensure_artifact_directories, project_root

COLLECTION_RELATIVE = Path("contract/postman/terrawatch.postman_collection.json")
ENVIRONMENT_RELATIVE: dict[str, Path] = {
    "local": Path("contract/postman/terrawatch.local.postman_environment.json"),
    "compose": Path("contract/postman/terrawatch.compose.postman_environment.json"),
}
REQUIRED_ENVIRONMENT_KEYS = ("ingest_url", "event_url", "analysis_url")
NEWMAN_JSON_REPORT = Path("artifacts/reports/postman.json")
NEWMAN_JUNIT_REPORT = Path("artifacts/junit/postman.xml")


def collection_path(root: Path | None = None) -> Path:
    return (root or project_root()) / COLLECTION_RELATIVE


def environment_path(name: str, root: Path | None = None) -> Path:
    try:
        relative = ENVIRONMENT_RELATIVE[name]
    except KeyError as error:
        raise ValueError(f"unknown Postman environment: {name}") from error
    return (root or project_root()) / relative


def load_collection(root: Path | None = None) -> dict[str, Any]:
    path = collection_path(root)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("the Postman collection must be a JSON object")
    return cast(dict[str, Any], document)


def load_environment(name: str, root: Path | None = None) -> dict[str, str]:
    document = json.loads(environment_path(name, root).read_text(encoding="utf-8"))
    values = document.get("values", [])
    if not isinstance(values, list):
        raise ValueError(f"{name} environment values must be a list")
    return {str(entry["key"]): str(entry["value"]) for entry in values}


def iter_requests(collection: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every leaf request item, regardless of folder nesting depth."""

    def walk(items: list[Any]) -> Iterator[dict[str, Any]]:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("collection items must be objects")
            children = item.get("item")
            if isinstance(children, list):
                yield from walk(children)
            elif "request" in item:
                yield item
            else:
                name = item.get("name")
                raise ValueError(f"collection item is neither folder nor request: {name}")

    yield from walk(collection.get("item", []))


def request_test_script(item: dict[str, Any]) -> str:
    """Return the complete test script attached to a request."""
    lines: list[str] = []
    for event in item.get("event", []):
        if event.get("listen") != "test":
            continue
        lines.extend(str(line) for line in event.get("script", {}).get("exec", []))
    return "\n".join(lines)


def request_assertions(item: dict[str, Any]) -> list[str]:
    """Return every `pm.test` assertion line attached to a request."""
    return [line for line in request_test_script(item).splitlines() if "pm.test(" in line]


def request_url(item: dict[str, Any]) -> str:
    url = item["request"]["url"]
    if isinstance(url, str):
        return url
    return str(url.get("raw", ""))


def newman_reports(root: Path | None = None) -> tuple[Path, Path]:
    repo = root or project_root()
    return repo / NEWMAN_JSON_REPORT, repo / NEWMAN_JUNIT_REPORT


def summarize_newman_report(path: Path) -> dict[str, int]:
    """Read Newman's own JSON report rather than trusting its exit code alone."""
    document = json.loads(path.read_text(encoding="utf-8"))
    statistics = document["run"]["stats"]
    assertions = statistics["assertions"]
    requests = statistics["requests"]
    total = int(assertions["total"])
    failed = int(assertions["failed"])
    if total == 0:
        raise ValueError("Newman executed zero assertions")
    return {
        "assertions": total,
        "failed_assertions": failed,
        "requests": int(requests["total"]),
        "failed_requests": int(requests["failed"]),
    }


def run_newman() -> int:
    """Execute the collection against the running environment via the pinned service."""
    from terractl.lifecycle import assert_environment_green, run_compose

    ensure_artifact_directories()
    assert_environment_green()
    json_report, junit_report = newman_reports()
    result = run_compose("run", "--rm", "--no-deps", "newman", include_test=True, timeout=600)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if not json_report.is_file():
        print(f"Newman produced no JSON report at {json_report.relative_to(project_root())}.")
        return 1
    if not junit_report.is_file():
        print(f"Newman produced no JUnit report at {junit_report.relative_to(project_root())}.")
        return 1
    summary = summarize_newman_report(json_report)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["failed_assertions"] or summary["failed_requests"]:
        return 1
    return result.returncode


def artifact_report_root() -> Path:
    return artifacts_root() / "reports"
