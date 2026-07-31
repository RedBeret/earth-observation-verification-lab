"""Static checks on the executable Postman contract.

These run before the environment exists, so a broken or unasserted collection is
caught without spending a full Newman run.
"""

from __future__ import annotations

import json

import pytest

from terractl.contract import (
    ENVIRONMENT_RELATIVE,
    REQUIRED_ENVIRONMENT_KEYS,
    collection_path,
    environment_path,
    iter_requests,
    load_collection,
    load_environment,
    request_assertions,
    request_test_script,
    request_url,
)
from terractl.safety import redact_text

pytestmark = [pytest.mark.contract, pytest.mark.static]

REQUIRED_PATHS = (
    "/healthz",
    "/readyz",
    "/metrics",
    "/openapi.json",
    "/v1/events",
    "/v1/correlations/",
    "/v1/provenance/",
)


def _all_test_scripts() -> str:
    return "\n".join(request_test_script(item) for item in iter_requests(load_collection()))


def test_collection_declares_the_supported_schema() -> None:
    collection = load_collection()
    assert collection["info"]["schema"].endswith("collection/v2.1.0/collection.json")
    assert collection["info"]["name"] == "TerraWatch verification contract"


def test_every_request_asserts_something() -> None:
    unasserted = [
        item["name"] for item in iter_requests(load_collection()) if not request_assertions(item)
    ]
    assert unasserted == []


def test_no_request_hard_codes_a_host() -> None:
    hard_coded = [
        item["name"]
        for item in iter_requests(load_collection())
        if not request_url(item).startswith("{{")
    ]
    assert hard_coded == []


def test_collection_covers_the_documented_interfaces() -> None:
    urls = [request_url(item) for item in iter_requests(load_collection())]
    missing = [path for path in REQUIRED_PATHS if not any(path in url for url in urls)]
    assert missing == []


def test_collection_asserts_the_shared_error_envelope() -> None:
    scripts = _all_test_scripts()
    assert "request_id" in scripts
    assert "'code', 'message', 'details', 'request_id'" in scripts


def test_collection_covers_both_rejection_and_not_found_paths() -> None:
    scripts = _all_test_scripts()
    assert "status(422)" in scripts
    assert "status(404)" in scripts


def test_environments_agree_and_declare_every_url() -> None:
    local = load_environment("local")
    compose = load_environment("compose")
    assert set(local) == set(compose) == set(REQUIRED_ENVIRONMENT_KEYS)
    assert all(value.startswith("http://127.0.0.1:") for value in local.values())
    assert all(value.startswith("http://") for value in compose.values())


def test_contract_files_carry_no_credential_shaped_values() -> None:
    paths = [collection_path(), *(environment_path(name) for name in ENVIRONMENT_RELATIVE)]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert redact_text(text) == text, f"{path.name} contains a credential-shaped value"


def test_collection_and_environments_are_valid_json_documents() -> None:
    for path in [collection_path(), *(environment_path(name) for name in ENVIRONMENT_RELATIVE)]:
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
