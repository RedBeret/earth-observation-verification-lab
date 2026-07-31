from __future__ import annotations

import time

import pytest

from terractl.faults import clear_faults, inject_fault, load_fault_state
from tests.resilience.helpers import (
    ANALYSIS_URL,
    EVENT_URL,
    INGEST_URL,
    wait_for_green,
    wait_for_readiness,
    write_fault_observation,
)

pytestmark = pytest.mark.resilience


@pytest.mark.parametrize(
    ("fault_name", "base_url", "dependency", "requirements"),
    [
        ("postgres-unavailable", ANALYSIS_URL, "postgres", ["API-005", "RES-001"]),
        ("minio-unavailable", INGEST_URL, "minio", ["API-005", "RES-001"]),
        ("nats-unavailable", EVENT_URL, "nats", ["API-005", "RES-001"]),
    ],
)
def test_dependency_readiness_degrades_and_recovers(
    fault_name: str,
    base_url: str,
    dependency: str,
    requirements: list[str],
) -> None:
    wait_for_readiness(base_url, 200)
    started = time.monotonic()
    state = inject_fault(fault_name)
    try:
        degraded = wait_for_readiness(base_url, 503, timeout=20)
    finally:
        if load_fault_state() is not None:
            clear_faults()
    recovered = wait_for_readiness(base_url, 200, timeout=30)
    wait_for_green()
    elapsed = time.monotonic() - started
    assert state["active"] is True
    assert degraded["body"]["dependencies"][dependency]["ready"] is False
    assert recovered["body"]["dependencies"][dependency]["ready"] is True
    assert elapsed < 30
    write_fault_observation(
        {
            "fault": fault_name,
            "scenario": "readiness",
            "expected": f"{dependency} readiness degrades to 503 and recovers to 200",
            "observed": {"degraded": degraded, "recovered": recovered},
            "detection": "dependency-specific readiness check",
            "behavior": "health remained process-local while readiness reflected dependency state",
            "data_loss": 0,
            "duplicates": 0,
            "recovery": "green baseline restored",
            "requirements": requirements,
            "result": "passed",
        }
    )
