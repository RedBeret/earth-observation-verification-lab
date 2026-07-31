"""Versioned performance thresholds and k6 execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from terractl.environment import ensure_artifact_directories, project_root

THRESHOLDS_RELATIVE = Path("performance/thresholds.json")
SCRIPT_RELATIVE = Path("performance/k6/api-load.js")
SUMMARY_RELATIVE = Path("artifacts/reports/k6-summary.json")
REQUIRED_THRESHOLD_KEYS = (
    "health_p95_ms",
    "query_p95_ms",
    "max_error_rate",
    "min_check_success_rate",
)


def thresholds_path(root: Path | None = None) -> Path:
    return (root or project_root()) / THRESHOLDS_RELATIVE


def script_path(root: Path | None = None) -> Path:
    return (root or project_root()) / SCRIPT_RELATIVE


def summary_path(root: Path | None = None) -> Path:
    return (root or project_root()) / SUMMARY_RELATIVE


def load_thresholds(root: Path | None = None) -> dict[str, float]:
    document = json.loads(thresholds_path(root).read_text(encoding="utf-8"))
    thresholds = document["thresholds"]
    missing = [key for key in REQUIRED_THRESHOLD_KEYS if key not in thresholds]
    if missing:
        raise ValueError(f"thresholds file is missing: {sorted(missing)}")
    return {key: float(thresholds[key]) for key in REQUIRED_THRESHOLD_KEYS}


def _metric(summary: dict[str, Any], name: str, value_key: str) -> float:
    try:
        return float(summary["metrics"][name]["values"][value_key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"k6 summary has no {value_key} for {name}") from error


def evaluate_summary(summary: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    """Re-check every threshold in Python instead of trusting the k6 exit code."""
    iterations = int(_metric(summary, "iterations", "count"))
    if iterations <= 0:
        raise ValueError("k6 recorded zero iterations")
    observed = {
        "iterations": iterations,
        "health_p95_ms": _metric(summary, "terrawatch_health_latency", "p(95)"),
        "query_p95_ms": _metric(summary, "terrawatch_query_latency", "p(95)"),
        "error_rate": _metric(summary, "terrawatch_request_errors", "rate"),
        "check_success_rate": _metric(summary, "checks", "rate"),
    }
    failures: list[str] = []
    if observed["health_p95_ms"] >= thresholds["health_p95_ms"]:
        failures.append("health p95 exceeded its threshold")
    if observed["query_p95_ms"] >= thresholds["query_p95_ms"]:
        failures.append("query p95 exceeded its threshold")
    if observed["error_rate"] >= thresholds["max_error_rate"]:
        failures.append("error rate exceeded its threshold")
    if observed["check_success_rate"] < thresholds["min_check_success_rate"]:
        failures.append("check success rate fell below its threshold")
    return {"thresholds": thresholds, "observed": observed, "failures": failures}


def run_performance() -> int:
    from terractl.lifecycle import assert_environment_green, run_compose

    ensure_artifact_directories()
    assert_environment_green()
    thresholds = load_thresholds()
    result = run_compose("run", "--rm", "--no-deps", "k6", include_test=True, timeout=900)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    summary_file = summary_path()
    if not summary_file.is_file():
        print("k6 produced no summary; treating the run as not observed.")
        return 1
    summary = cast(dict[str, Any], json.loads(summary_file.read_text(encoding="utf-8")))
    evaluation = evaluate_summary(summary, thresholds)
    print(json.dumps(evaluation, indent=2, sort_keys=True))
    if evaluation["failures"]:
        return 1
    return result.returncode
