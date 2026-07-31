from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from terractl.faults import clear_faults, inject_fault, load_fault_state
from terrawatch.database import (
    AnalysisResult,
    Correlation,
    DeadLetter,
    OutboxEvent,
    ProcessingAttempt,
    Scene,
)
from terrawatch.messaging import DLQ_STREAM
from tests.resilience.helpers import (
    container_started_at,
    generated_events,
    publish_missing_event,
    stream_messages,
    submit_event,
    upload_canonical_scene,
    wait_for_green,
    wait_until,
    write_fault_observation,
)
from tests.support import (
    live_minio,
    live_session_factory,
    live_settings,
    wait_for_analysis,
    wait_for_scene,
)

pytestmark = pytest.mark.resilience


def test_duplicate_delivery_is_idempotent() -> None:
    upload_canonical_scene()
    wait_for_scene("SCENE-SYN-0001", "accepted")
    event = generated_events()[0]
    submit_event(event)
    wait_for_analysis("EVENT-SYN-INSIDE", "matched")
    factory = live_session_factory()
    with factory() as session:
        message_id = str(
            session.execute(
                select(OutboxEvent.id).where(OutboxEvent.aggregate_id == "EVENT-SYN-INSIDE")
            ).scalar_one()
        )
        initial_attempts = session.query(ProcessingAttempt).filter_by(message_id=message_id).count()
    inject_fault("duplicate-event")

    def duplicate_processed() -> bool:
        with factory() as session:
            return (
                session.query(ProcessingAttempt).filter_by(message_id=message_id).count()
                >= initial_attempts + 1
            )

    wait_until(duplicate_processed, description="duplicate event delivery to be acknowledged")
    with factory() as session:
        assert session.query(Correlation).count() == 1
        assert session.query(AnalysisResult).count() == 1
        assert session.query(DeadLetter).count() == 0
    write_fault_observation(
        {
            "fault": "duplicate-event",
            "scenario": "idempotency",
            "expected": "duplicate delivery does not duplicate correlation or analysis rows",
            "observed": {"correlations": 1, "analysis_results": 1, "dead_letters": 0},
            "detection": "processing-attempt count increased for the original message ID",
            "behavior": "deterministic IDs and database uniqueness absorbed redelivery",
            "data_loss": 0,
            "duplicates": 0,
            "recovery": "no recovery action required",
            "requirements": ["EVT-004", "RES-003"],
            "result": "passed",
        }
    )


def test_retry_exhaustion_is_visible_in_database_and_dlq_stream() -> None:
    message_id = str(uuid4())
    publish_missing_event(message_id)
    factory = live_session_factory()

    def dead_letter_recorded() -> bool:
        with factory() as session:
            return (
                session.execute(
                    select(DeadLetter).where(
                        DeadLetter.message_id == message_id,
                        DeadLetter.service == "correlation-worker",
                    )
                ).scalar_one_or_none()
                is not None
            )

    wait_until(
        dead_letter_recorded,
        description="exhausted correlation message to reach the dead-letter table",
        timeout=30,
        interval=0.5,
    )
    wait_until(
        lambda: stream_messages(DLQ_STREAM) == 1,
        description="one visible NATS dead-letter message",
        timeout=10,
    )
    with factory() as session:
        dead_letter = session.execute(
            select(DeadLetter).where(DeadLetter.message_id == message_id)
        ).scalar_one()
        attempts = (
            session.execute(
                select(ProcessingAttempt)
                .where(ProcessingAttempt.message_id == message_id)
                .order_by(ProcessingAttempt.attempt)
            )
            .scalars()
            .all()
        )
    assert dead_letter.attempts == 5
    assert dead_letter.subject == "terrawatch.dlq.correlation.v1"
    assert len(attempts) == 5
    assert [attempt.attempt for attempt in attempts] == [1, 2, 3, 4, 5]
    assert all(attempt.status == "failed" for attempt in attempts)
    write_fault_observation(
        {
            "fault": "retry-exhaustion",
            "scenario": "missing-event",
            "expected": "five bounded attempts end in visible database and NATS dead letters",
            "observed": {"attempts": 5, "database_dead_letters": 1, "nats_dead_letters": 1},
            "detection": "processing attempts and both dead-letter stores",
            "behavior": "message acknowledged only after dead-letter publication and persistence",
            "data_loss": 0,
            "duplicates": 0,
            "recovery": "poison message isolated from the primary consumer",
            "requirements": ["RES-002", "RES-004", "RES-005"],
            "result": "passed",
        }
    )


def test_worker_restart_resumes_processing() -> None:
    upload_canonical_scene()
    wait_for_scene("SCENE-SYN-0001", "accepted")
    before = container_started_at("correlation-worker")
    inject_fault("worker-restart")
    wait_until(
        lambda: container_started_at("correlation-worker") != before,
        description="correlation worker restart timestamp to change",
        timeout=30,
    )
    wait_for_green()
    submit_event(generated_events()[1])
    wait_for_analysis("EVENT-SYN-OUTSIDE", "spatial-non-match", timeout=30)
    write_fault_observation(
        {
            "fault": "worker-restart",
            "scenario": "resume-processing",
            "expected": "worker restarts and processes subsequently accepted telemetry",
            "observed": {"started_at_changed": True, "analysis_status": "spatial-non-match"},
            "detection": "container start timestamp",
            "behavior": "durable consumer resumed after restart",
            "data_loss": 0,
            "duplicates": 0,
            "recovery": "green baseline and completed analysis",
            "requirements": ["RES-001", "RES-003"],
            "result": "passed",
        }
    )


def test_malformed_object_and_stale_catalog_faults_are_exactly_reverted() -> None:
    upload_canonical_scene()
    wait_for_scene("SCENE-SYN-0001", "accepted")
    client = live_minio()
    bucket = live_settings().minio_bucket
    original_objects = {item.object_name for item in client.list_objects(bucket, recursive=True)}

    malformed = inject_fault("malformed-raster")
    malformed_name = str(malformed["object_name"])
    assert malformed_name in {
        item.object_name for item in client.list_objects(bucket, recursive=True)
    }
    clear_faults()
    assert {
        item.object_name for item in client.list_objects(bucket, recursive=True)
    } == original_objects

    stale = inject_fault("stale-catalog-metadata")
    factory = live_session_factory()
    with factory() as session:
        scene = session.get(Scene, "SCENE-SYN-0001")
        assert scene is not None
        assert scene.width == int(stale["original_width"]) + 1
    assert load_fault_state() is not None
    clear_faults()
    with factory() as session:
        scene = session.get(Scene, "SCENE-SYN-0001")
        assert scene is not None
        assert scene.width == int(stale["original_width"])
    write_fault_observation(
        {
            "fault": "malformed-raster-and-stale-catalog",
            "scenario": "exact-cleanup",
            "expected": "only generated fault state is changed and then exactly restored",
            "observed": {
                "malformed_object_removed": True,
                "original_objects_unchanged": True,
                "catalog_width_restored": True,
            },
            "detection": "independent MinIO listing and database read-back",
            "behavior": "fault state recorded the exact generated object and original width",
            "data_loss": 0,
            "duplicates": 0,
            "recovery": "object set and catalog width match the prefault baseline",
            "requirements": ["RES-003", "SEC-003"],
            "result": "passed",
        }
    )
