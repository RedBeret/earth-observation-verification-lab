from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from terrawatch.api import create_app, normalized_request_id

pytestmark = pytest.mark.unit


def test_valid_request_id_is_preserved() -> None:
    assert normalized_request_id("operator-run:scene_001") == "operator-run:scene_001"


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "contains spaces",
        "../unsafe",
        "x" * 129,
        "line\nbreak",
    ],
)
def test_invalid_request_id_is_replaced(candidate: str | None) -> None:
    generated = normalized_request_id(candidate)
    UUID(generated)
    assert generated != candidate


def test_unknown_route_uses_common_error_envelope() -> None:
    with TestClient(create_app("test-api", ())) as client:
        response = client.get("/not-a-route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource-not-found"
    UUID(response.json()["error"]["request_id"])
