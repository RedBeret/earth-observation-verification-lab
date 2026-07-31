from typing import Any

import pytest

from terrawatch.config import Settings
from terrawatch.storage import minio_client

pytestmark = pytest.mark.unit


def test_minio_client_uses_bounded_connect_and_read_timeouts(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, **kwargs: Any) -> None:
            observed.update(endpoint=endpoint, **kwargs)

    monkeypatch.setattr("terrawatch.storage.Minio", FakeMinio)
    client = minio_client(Settings())

    assert isinstance(client, FakeMinio)
    timeout = observed["http_client"].connection_pool_kw["timeout"]
    assert timeout.connect_timeout == 2.0
    assert timeout.read_timeout == 2.0
    retries = observed["http_client"].connection_pool_kw["retries"]
    assert retries.total is False
    assert retries.redirect == 0
