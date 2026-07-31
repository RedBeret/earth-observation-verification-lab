import pytest

from terrawatch.retry import backoff_seconds, retry_exhausted

pytestmark = pytest.mark.unit


def test_backoff_bounds() -> None:
    assert backoff_seconds(1, random_value=0.5) == 0.5
    assert backoff_seconds(2, random_value=0.5) == 1.0
    assert backoff_seconds(20, random_value=0.5) == 8.0
    assert 0.4 <= backoff_seconds(1, random_value=0.0) <= 0.5
    assert 0.5 <= backoff_seconds(1, random_value=1.0) <= 0.6


def test_retry_exhaustion() -> None:
    assert not retry_exhausted(4, 5)
    assert retry_exhausted(5, 5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attempt": 0},
        {"attempt": 1, "base": 0},
        {"attempt": 1, "base": 2, "cap": 1},
        {"attempt": 1, "jitter_ratio": 2},
        {"attempt": 1, "random_value": -1},
    ],
)
def test_invalid_backoff_configuration(kwargs) -> None:
    with pytest.raises(ValueError):
        backoff_seconds(**kwargs)
