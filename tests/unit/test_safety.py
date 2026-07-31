# secret-scan: synthetic-fixture
# Every credential-shaped string below is invented for this test and exists only to
# prove that redaction works. Nothing here is a real or reachable credential.
from pathlib import Path

import pytest

from terractl.safety import assert_project_identity, redact_text, redact_value, safe_artifact_path
from terrawatch.constants import PROJECT_LABEL, PROJECT_LABEL_VALUE

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("password=local-example-value", id="password-assignment"),
        pytest.param("api_key: example-long-value", id="api-key-assignment"),
        pytest.param("token = example-token-value", id="token-assignment"),
        pytest.param(
            "postgresql://user:example-database-password@postgres:5432/database",
            id="credential-in-url",
        ),
        pytest.param("gho_abcdefghijklmnopqrstuvwxyz012345", id="provider-token"),
        pytest.param(
            "-----BEGIN PRIVATE KEY-----\nexample\n-----END PRIVATE KEY-----",
            id="private-key-block",
        ),
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
