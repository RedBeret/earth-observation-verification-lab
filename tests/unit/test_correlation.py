import pytest

from terrawatch.correlation import (
    _correlation_status,
    _event_analysis_status,
    deterministic_correlation_id,
)
from terrawatch.validation import validate_identifier

pytestmark = pytest.mark.unit


def test_correlation_identifier_is_deterministic_and_structured() -> None:
    first = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-INSIDE")
    second = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-INSIDE")
    assert first == second
    assert validate_identifier(first) == first


def test_correlation_identifier_changes_by_input() -> None:
    baseline = deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-INSIDE")
    assert baseline != deterministic_correlation_id("SCENE-SYN-0002", "EVENT-SYN-INSIDE")
    assert baseline != deterministic_correlation_id("SCENE-SYN-0001", "EVENT-SYN-OUTSIDE")
    assert baseline != deterministic_correlation_id(
        "SCENE-SYN-0001",
        "EVENT-SYN-INSIDE",
        "correlator-2.0.0",
    )


@pytest.mark.parametrize(
    ("spatial", "temporal", "expected"),
    [
        (True, True, "matched"),
        (False, True, "spatial-non-match"),
        (False, False, "spatial-non-match"),
        (True, False, "temporal-non-match"),
    ],
)
def test_correlation_status_precedence(
    spatial: bool,
    temporal: bool,
    expected: str,
) -> None:
    assert _correlation_status(spatial, temporal) == expected


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["matched", "spatial-non-match"], "matched"),
        (["temporal-non-match"], "temporal-non-match"),
        (["spatial-non-match"], "spatial-non-match"),
        ([], "no-scenes"),
    ],
)
def test_event_analysis_status(statuses: list[str], expected: str) -> None:
    assert _event_analysis_status(statuses) == expected
