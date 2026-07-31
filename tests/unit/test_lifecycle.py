import json

import pytest

from terractl.lifecycle import _parse_ps

pytestmark = pytest.mark.unit


def test_parse_compose_ps_array() -> None:
    assert _parse_ps(json.dumps([{"Service": "postgres", "State": "running"}])) == [
        {"Service": "postgres", "State": "running"}
    ]


def test_parse_compose_ps_json_lines() -> None:
    output = "\n".join(
        [
            json.dumps({"Service": "postgres", "State": "running"}),
            json.dumps({"Service": "minio", "State": "running"}),
        ]
    )
    assert _parse_ps(output) == [
        {"Service": "postgres", "State": "running"},
        {"Service": "minio", "State": "running"},
    ]
