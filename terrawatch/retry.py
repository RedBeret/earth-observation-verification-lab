"""Bounded retry calculations used by message workers."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable

# A frozen dependency keeps acknowledging TCP while nothing inside it ever replies, so a
# call against it never returns. A worker that waits forever never naks, never retries,
# and never dead letters. It stops consuming while still looking alive, which is worse
# than crashing. Bounding the work turns that silence into an ordinary failed attempt,
# which the retry path already knows how to handle.
PROCESSING_TIMEOUT_SECONDS = 15.0


async def bounded[T](work: Awaitable[T], *, timeout: float | None = None) -> T:
    """Await dependency work, giving up rather than hanging forever."""
    return await asyncio.wait_for(work, timeout=timeout or PROCESSING_TIMEOUT_SECONDS)


def backoff_seconds(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 8.0,
    jitter_ratio: float = 0.2,
    random_value: float | None = None,
) -> float:
    if attempt < 1:
        raise ValueError("attempt starts at one")
    if base <= 0 or cap <= 0 or base > cap:
        raise ValueError("invalid backoff bounds")
    if not 0 <= jitter_ratio <= 1:
        raise ValueError("jitter ratio must be between zero and one")
    raw = min(cap, base * (2 ** (attempt - 1)))
    # Retry jitter spreads reconnect attempts. It is not a security decision.
    sample = random.random() if random_value is None else random_value  # nosec B311
    if not 0 <= sample <= 1:
        raise ValueError("random value must be between zero and one")
    jitter = raw * jitter_ratio * ((sample * 2) - 1)
    return float(max(0.0, min(cap, raw + jitter)))


def retry_exhausted(attempt: int, max_attempts: int) -> bool:
    if attempt < 1 or max_attempts < 1:
        raise ValueError("attempt counts start at one")
    return attempt >= max_attempts
