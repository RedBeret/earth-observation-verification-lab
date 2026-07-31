from __future__ import annotations

from collections.abc import Iterator

import pytest

from terractl.faults import clear_faults, load_fault_state
from tests.resilience.helpers import purge_streams, wait_for_green
from tests.support import reset_live_state


@pytest.fixture(autouse=True)
def clean_resilience_baseline() -> Iterator[None]:
    wait_for_green()
    if load_fault_state() is not None:
        clear_faults()
        wait_for_green()
    purge_streams()
    reset_live_state()
    yield
    if load_fault_state() is not None:
        clear_faults()
        wait_for_green()
    purge_streams()
    reset_live_state()
    wait_for_green()
