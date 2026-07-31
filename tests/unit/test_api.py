from uuid import UUID

import pytest

from terrawatch.api import normalized_request_id

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
