from pathlib import Path

import pytest

from terractl.locking import exclusive_run_lock

pytestmark = pytest.mark.unit


def test_lock_acquisition_and_release(tmp_path: Path) -> None:
    path = tmp_path / "system.lock"
    with (
        exclusive_run_lock(path),
        pytest.raises(RuntimeError, match="another protected test run"),
        exclusive_run_lock(path),
    ):
        pass
    with exclusive_run_lock(path):
        assert path.exists()
