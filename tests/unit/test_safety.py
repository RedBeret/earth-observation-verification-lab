from pathlib import Path

import pytest

from terractl.safety import assert_project_identity, redact_text, redact_value, safe_artifact_path
from terrawatch.constants import PROJECT_LABEL, PROJECT_LABEL_VALUE

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "source",
    [
        "password=local-example-value",
        "api_key: example-long-value",
        "token = example-token-value",
        "gho_abcdefghijklmnopqrstuvwxyz012345",
        "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----",
    ],
)
def test_secret_redaction(source: str) -> None:
    result = redact_text(source)
    assert "example" not in result
    assert "REDACTED" in result


def test_structured_redaction_preserves_shape() -> None:
    source = {"nested": ["password=example-sensitive-value", {"safe": True}]}
    result = redact_value(source)
    assert result == {"nested": ["password=[REDACTED]", {"safe": True}]}


def test_project_identity() -> None:
    labels = {
        PROJECT_LABEL: PROJECT_LABEL_VALUE,
        "com.docker.compose.project": "terrawatch-demo-west-12345678",
    }
    assert_project_identity(labels, "terrawatch-demo-west-12345678")


def test_wrong_project_identity_fails() -> None:
    with pytest.raises(ValueError):
        assert_project_identity(
            {
                PROJECT_LABEL: PROJECT_LABEL_VALUE,
                "com.docker.compose.project": "other-project",
            },
            "terrawatch-demo-west-12345678",
        )


def test_artifact_path_escape_fails(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    assert safe_artifact_path(root / "evidence", root) == (root / "evidence").resolve()
    with pytest.raises(ValueError):
        safe_artifact_path(tmp_path / "outside", root)
