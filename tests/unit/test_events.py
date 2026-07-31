import json
from copy import deepcopy

import pytest

from terrawatch.events import IDEMPOTENCY_KEY_PATTERN, event_payload_hash
from terrawatch.models import TelemetryEvent

pytestmark = pytest.mark.unit


def _event() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "event_id": "EVENT-SYN-INSIDE",
        "event_type": "temperature-anomaly",
        "observed_at": "2026-07-29T18:35:00Z",
        "location": {"type": "Point", "coordinates": [-120.0, 37.2]},
        "confidence": 0.91,
        "source": "field-sensor-simulator",
        "attributes": {"temperature_c": 47.2},
    }


def test_event_hash_is_canonical_across_key_order() -> None:
    payload = _event()
    reordered = json.loads(json.dumps(payload, sort_keys=True))
    assert event_payload_hash(TelemetryEvent.model_validate(payload)) == event_payload_hash(
        TelemetryEvent.model_validate(reordered)
    )


def test_event_hash_changes_with_payload() -> None:
    original = _event()
    changed = deepcopy(original)
    changed["confidence"] = 0.92
    assert event_payload_hash(TelemetryEvent.model_validate(original)) != event_payload_hash(
        TelemetryEvent.model_validate(changed)
    )


@pytest.mark.parametrize("key", ["EVENT-SYN-INSIDE:1", "replay_001", "a" * 128])
def test_valid_idempotency_keys(key: str) -> None:
    assert IDEMPOTENCY_KEY_PATTERN.fullmatch(key)


@pytest.mark.parametrize("key", ["", "contains spaces", "../unsafe", "a" * 129])
def test_invalid_idempotency_keys(key: str) -> None:
    assert IDEMPOTENCY_KEY_PATTERN.fullmatch(key) is None
