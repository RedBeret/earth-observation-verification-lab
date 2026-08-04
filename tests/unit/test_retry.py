import asyncio

import pytest

from terrawatch.retry import backoff_seconds, bounded, retry_exhausted

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


def test_bounded_work_that_never_answers_raises_a_timeout() -> None:
    """A frozen dependency acknowledges TCP without replying, so the call never returns.
    The worker has to give up, because only a raised error reaches the nak and retry path
    that the whole delivery guarantee depends on."""

    async def never_answers() -> str:
        await asyncio.sleep(3600)
        return "unreachable"

    async def exercise() -> str:
        return await bounded(never_answers(), timeout=0.05)

    with pytest.raises(TimeoutError):
        asyncio.run(exercise())


def test_bounded_work_that_answers_returns_its_value() -> None:
    async def answers() -> str:
        return "done"

    assert asyncio.run(bounded(answers(), timeout=5)) == "done"


def test_bounded_work_preserves_a_real_failure() -> None:
    """A genuine error must not be reported as a timeout, or the dead letter record would
    name the wrong cause."""

    async def fails() -> str:
        raise ValueError("stored object digest does not match the scene record")

    with pytest.raises(ValueError, match="digest"):
        asyncio.run(bounded(fails(), timeout=5))
