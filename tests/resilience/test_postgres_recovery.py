from __future__ import annotations

import pytest
from sqlalchemy import select

from terractl.faults import clear_faults, inject_fault, load_fault_state
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    DeadLetter,
    OutboxEvent,
    ProcessingAttempt,
    TelemetryEventRecord,
)
from tests.resilience.helpers import (
    ANALYSIS_URL,
    consumer_redeliveries,
    generated_events,
    pause_service,
    submit_event,
    unpause_service,
    upload_canonical_scene,
    wait_for_green,
    wait_for_published_events,
    wait_for_readiness,
    wait_until,
    write_fault_observation,
)
from tests.support import live_session_factory, wait_for_analysis, wait_for_scene

pytestmark = pytest.mark.resilience


def test_postgres_outage_retries_and_recovers_without_loss() -> None:
    upload_canonical_scene()
    wait_for_scene("SCENE-SYN-0001", "accepted")
    worker_id = pause_service("correlation-worker")
    worker_paused = True
    event_ids: set[str] = set()
    try:
        for event in generated_events()[:3]:
            event_id = str(event["event_id"])
            event_ids.add(event_id)
            submit_event(event)
        wait_for_published_events(event_ids)
        inject_fault("postgres-unavailable")
        try:
            unpause_service("correlation-worker", worker_id)
            worker_paused = False
            degraded = wait_for_readiness(ANALYSIS_URL, 503, timeout=20)
            wait_until(
                lambda: consumer_redeliveries() >= 1,
                description="at least one correlation message redelivery",
                timeout=20,
                interval=0.5,
            )
        finally:
            if load_fault_state() is not None:
                clear_faults()
        recovered = wait_for_readiness(ANALYSIS_URL, 200, timeout=30)
        wait_for_green()
        expected_statuses = {
            "EVENT-SYN-INSIDE": "matched",
            "EVENT-SYN-OUTSIDE": "spatial-non-match",
            "EVENT-SYN-BOUNDARY": "matched",
        }
        for event_id, status in expected_statuses.items():
            wait_for_analysis(event_id, status, timeout=30)

        factory = live_session_factory()
        with factory() as session:
            event_count = session.query(TelemetryEventRecord).count()
            analysis_count = session.query(AnalysisResult).count()
            correlation_count = session.query(Correlation).count()
            dead_letter_count = session.query(DeadLetter).count()
            event_message_ids = set(
                session.execute(
                    select(OutboxEvent.id).where(OutboxEvent.aggregate_id.in_(event_ids))
                ).scalars()
            )
            passed_attempts = (
                session.execute(
                    select(ProcessingAttempt).where(
                        ProcessingAttempt.message_id.in_({str(item) for item in event_message_ids}),
                        ProcessingAttempt.status == "passed",
                    )
                )
                .scalars()
                .all()
            )
        assert event_count == 3
        assert analysis_count == 3
        assert correlation_count == 3
        assert dead_letter_count == 0
        assert len(passed_attempts) == 3
        assert max(attempt.attempt for attempt in passed_attempts) >= 2
        evidence_path = write_fault_observation(
            {
                "fault": "postgres-unavailable",
                "scenario": "queued-event-recovery",
                "expected": "three accepted events retry and process once after a temporary outage",
                "observed": {
                    "readiness_during": degraded,
                    "readiness_after": recovered,
                    "events": event_count,
                    "analyses": analysis_count,
                    "correlations": correlation_count,
                    "dead_letters": dead_letter_count,
                    "max_successful_delivery_attempt": max(
                        attempt.attempt for attempt in passed_attempts
                    ),
                },
                "detection": "analysis readiness 503 and JetStream redelivery count",
                "behavior": "messages remained pending and were explicitly retried",
                "data_loss": 0,
                "duplicates": 0,
                "recovery": "three deterministic analyses completed and baseline returned green",
                "requirements": [
                    "EVT-004",
                    "API-005",
                    "RES-001",
                    "RES-002",
                    "RES-003",
                    "RES-004",
                    "RES-005",
                    "SEC-002",
                    "SEC-003",
                ],
                "result": "passed",
            }
        )
        assert evidence_path.is_file()
    finally:
        if worker_paused:
            unpause_service("correlation-worker", worker_id)
        if load_fault_state() is not None:
            clear_faults()
