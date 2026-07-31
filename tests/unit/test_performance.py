import json

import pytest

from terractl.performance import (
    REQUIRED_THRESHOLD_KEYS,
    evaluate_summary,
    load_thresholds,
    script_path,
    thresholds_path,
)

pytestmark = pytest.mark.unit


def _summary(
    health_p95: float = 100.0,
    query_p95: float = 400.0,
    error_rate: float = 0.0,
    check_rate: float = 1.0,
    iterations: int = 120,
) -> dict[str, object]:
    return {
        "metrics": {
            "iterations": {"values": {"count": iterations}},
            "terrawatch_health_latency": {"values": {"p(95)": health_p95}},
            "terrawatch_query_latency": {"values": {"p(95)": query_p95}},
            "terrawatch_request_errors": {"values": {"rate": error_rate}},
            "checks": {"values": {"rate": check_rate}},
        }
    }


def test_versioned_thresholds_match_the_documented_gate() -> None:
    assert load_thresholds() == {
        "health_p95_ms": 250.0,
        "query_p95_ms": 750.0,
        "max_error_rate": 0.01,
        "min_check_success_rate": 0.99,
    }


def test_load_profile_is_versioned_alongside_the_thresholds() -> None:
    document = json.loads(thresholds_path().read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0.0"
    assert document["load"]["virtual_users"] >= 1
    assert document["load"]["duration"].endswith("s")


def test_k6_script_reads_every_threshold_from_the_versioned_file() -> None:
    script = script_path().read_text(encoding="utf-8")
    assert "open('../thresholds.json')" in script
    for key in REQUIRED_THRESHOLD_KEYS:
        assert f"limits.{key}" in script


def test_a_clean_run_passes_every_threshold() -> None:
    evaluation = evaluate_summary(_summary(), load_thresholds())
    assert evaluation["failures"] == []
    assert evaluation["observed"]["iterations"] == 120


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (_summary(health_p95=250.0), "health p95 exceeded its threshold"),
        (_summary(query_p95=900.0), "query p95 exceeded its threshold"),
        (_summary(error_rate=0.05), "error rate exceeded its threshold"),
        (_summary(check_rate=0.90), "check success rate fell below its threshold"),
    ],
)
def test_each_threshold_can_fail_independently(summary: dict[str, object], expected: str) -> None:
    assert evaluate_summary(summary, load_thresholds())["failures"] == [expected]


def test_a_run_with_no_iterations_cannot_report_success() -> None:
    with pytest.raises(ValueError, match="zero iterations"):
        evaluate_summary(_summary(iterations=0), load_thresholds())


def test_a_missing_metric_cannot_be_silently_ignored() -> None:
    summary = _summary()
    del summary["metrics"]["checks"]  # type: ignore[index]
    with pytest.raises(ValueError, match="no rate for checks"):
        evaluate_summary(summary, load_thresholds())
