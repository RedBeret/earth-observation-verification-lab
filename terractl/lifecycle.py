"""Docker lifecycle operations are implemented in Stage 2."""

from __future__ import annotations


def unavailable(command: str) -> int:
    print(f"{command} requires the Stage 2 Compose environment.")
    return 2
