import json
from copy import deepcopy
from uuid import UUID

import httpx
import jsonschema
import pytest

from terractl.environment import project_root
from terrawatch.constants import TELEMETRY_SUBJECT
from terrawatch.database import OutboxEvent, TelemetryEventRecord
from tests.support import live_session_factory, reset_live_state, wait_for_event

pytestmark = pytest.mark.contract
BASE_URL = "http://127.0.0.1:18002"


@pytest.fixture(autouse=True)
def clean_live_state():
    reset_live_state()
    yield
    reset_live_state()


def _inside_event() -> dict[str, object]:
    document = json.loads(
        (project_root() / "data" / "events" / "events.json").read_text(encoding="utf-8")
    )
    return document["events"][0]


def _submit(
    payload: dict[str, object],
    key: str | None = "event-contract-key",
) -> httpx.Response:
    headers = {"Idempotency-Key": key} if key is not None else {}
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        return client.post("/v1/events", json=payload, headers=headers)


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["details"] == {}
    UUID(body["error"]["request_id"])
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


def _assert_no_events() -> None:
    factory = live_session_factory()
    with factory() as session:
        assert session.query(TelemetryEventRecord).count() == 0
        assert session.query(OutboxEvent).count() == 0


def test_event_acceptance_envelope_and_exact_replay() -> None:
    payload = _inside_event()
    response = _submit(payload)
    assert response.status_code == 202, response.text
    assert response.json()["replayed"] is False
    assert len(response.json()["payload_hash"]) == 64
    wait_for_event("EVENT-SYN-INSIDE", "processed")

    replay = _submit(payload)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    factory = live_session_factory()
    with factory() as session:
        assert session.query(TelemetryEventRecord).count() == 1
        outbox = session.query(OutboxEvent).one()
        assert outbox.subject == TELEMETRY_SUBJECT
        assert outbox.published_at is not None
        schema = json.loads(
            (
                project_root() / "requirements" / "schemas" / "message-envelope.schema.json"
            ).read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
            outbox.payload
        )


def test_missing_idempotency_key_is_rejected() -> None:
    response = _submit(_inside_event(), key=None)
    _assert_error(response, 422, "invalid-idempotency-key")
    _assert_no_events()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 1.1),
        ("observed_at", "2026-07-29T11:35:00-07:00"),
        ("location", {"type": "Point", "coordinates": [-181.0, 37.2]}),
    ],
)
def test_invalid_events_are_rejected(field: str, value: object) -> None:
    payload = _inside_event()
    payload[field] = value
    response = _submit(payload)
    _assert_error(response, 422, "invalid-event")
    _assert_no_events()


def test_reused_key_with_changed_payload_conflicts() -> None:
    payload = _inside_event()
    assert _submit(payload).status_code == 202
    wait_for_event("EVENT-SYN-INSIDE", "processed")
    changed = deepcopy(payload)
    changed["event_id"] = "EVENT-SYN-CHANGED"
    changed["confidence"] = 0.5
    conflict = _submit(changed)
    _assert_error(conflict, 409, "idempotency-key-conflict")
    factory = live_session_factory()
    with factory() as session:
        assert session.query(TelemetryEventRecord).count() == 1


def test_reused_event_id_with_changed_key_or_payload_conflicts() -> None:
    payload = _inside_event()
    assert _submit(payload).status_code == 202
    wait_for_event("EVENT-SYN-INSIDE", "processed")
    changed = deepcopy(payload)
    changed["confidence"] = 0.5
    conflict = _submit(changed, key="different-key")
    _assert_error(conflict, 409, "event-id-conflict")
    factory = live_session_factory()
    with factory() as session:
        assert session.query(TelemetryEventRecord).count() == 1
