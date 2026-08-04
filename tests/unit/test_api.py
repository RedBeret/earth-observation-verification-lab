import asyncio
from unittest import mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from terrawatch import api as api_module
from terrawatch.api import _bounded_check, create_app, normalized_request_id

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


def test_a_dependency_that_never_answers_reads_as_not_ready() -> None:
    """A frozen container keeps acknowledging TCP while nothing in it replies, so a probe
    against it can hang forever. Readiness that hangs reports nothing at all, so the check
    is bounded and a timeout has to read as not ready."""

    async def never_answers() -> tuple[bool, str]:
        await asyncio.sleep(3600)
        return True, "unreachable"

    async def exercise() -> tuple[bool, str]:
        return await _bounded_check(never_answers())

    with mock.patch.object(api_module, "READINESS_CHECK_TIMEOUT_SECONDS", 0.05):
        ready, detail = asyncio.run(exercise())
    assert ready is False
    assert detail == "TimeoutError"


def test_a_dependency_that_answers_is_passed_through() -> None:
    async def answers() -> tuple[bool, str]:
        return True, "3.5 USE_GEOS=1"

    assert asyncio.run(_bounded_check(answers())) == (True, "3.5 USE_GEOS=1")


def test_a_dependency_that_reports_failure_is_preserved() -> None:
    async def fails() -> tuple[bool, str]:
        return False, "OperationalError"

    assert asyncio.run(_bounded_check(fails())) == (False, "OperationalError")
