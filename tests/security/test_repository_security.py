# secret-scan: synthetic-fixture
"""Repository security and public-boundary verification.

These checks are static so they can run before the environment exists and inside
any CI runner. Container runtime posture is checked against the rendered Compose
configuration, which is also available without starting the project.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from terractl.environment import project_root
from terractl.safety import redact_text
from terractl.security import (
    Finding,
    dockerfile_runs_unprivileged,
    generated_artifacts,
    inspect_container_security,
    scan_for_secrets,
    scan_public_boundary,
    tracked_files,
)

pytestmark = [pytest.mark.security, pytest.mark.static]


def _rendered_compose() -> dict[str, object]:
    """Approximate `docker compose config` without requiring a Docker daemon."""
    document = yaml.safe_load((project_root() / "compose.yml").read_text(encoding="utf-8"))
    services = {}
    for name, service in document["services"].items():
        ports = []
        for port in service.get("ports", []):
            host, _, _remainder = str(port).partition(":")
            ports.append({"host_ip": host})
        services[name] = {**service, "ports": ports}
    return {"services": services}


def test_tracked_files_contain_no_credential_shapes() -> None:
    findings = scan_for_secrets(tracked_files())
    assert [str(finding) for finding in findings] == []


def test_generated_artifacts_contain_no_credential_shapes() -> None:
    findings = scan_for_secrets(generated_artifacts())
    assert [str(finding) for finding in findings] == []


def test_repository_respects_the_public_boundary() -> None:
    findings = scan_public_boundary()
    assert [str(finding) for finding in findings] == []


def test_the_secret_scanner_reports_a_planted_credential(tmp_path: Path) -> None:
    planted = tmp_path / "planted.env"
    planted.write_text("api_key = AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    findings = scan_for_secrets([planted], root=tmp_path)
    rules = {finding.rule for finding in findings}
    assert "aws-access-key-id" in rules
    assert all(str(finding).count(":") >= 1 for finding in findings)


def test_findings_never_repeat_the_offending_value(tmp_path: Path) -> None:
    planted = tmp_path / "planted.txt"
    planted.write_text("token = ghp_abcdefghijklmnopqrstuvwxyz0123\n", encoding="utf-8")
    rendered = " ".join(str(finding) for finding in scan_for_secrets([planted], root=tmp_path))
    assert "ghp_" not in rendered
    assert rendered == redact_text(rendered)


def test_environment_placeholders_are_not_treated_as_secrets(tmp_path: Path) -> None:
    template = tmp_path / "compose.yml"
    template.write_text(
        'POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\npassword: "$POSTGRES_PASSWORD"\n',
        encoding="utf-8",
    )
    assert scan_for_secrets([template], root=tmp_path) == []


def test_documented_local_defaults_are_allowed_but_real_values_are_not(tmp_path: Path) -> None:
    allowed = tmp_path / "alembic.ini"
    allowed.write_text(
        "sqlalchemy.url = postgresql+psycopg://terrawatch:terrawatch@127.0.0.1:15432/terrawatch\n",
        encoding="utf-8",
    )
    rejected = tmp_path / "settings.ini"
    rejected.write_text(
        "sqlalchemy.url = postgresql+psycopg://terrawatch:s7Kd92LmQx41@127.0.0.1:15432/terrawatch\n",
        encoding="utf-8",
    )
    assert scan_for_secrets([allowed], root=tmp_path) == []
    assert [finding.rule for finding in scan_for_secrets([rejected], root=tmp_path)] == [
        "credential-in-url"
    ]


def test_only_the_scanner_source_may_exempt_itself_from_the_term_scan(tmp_path: Path) -> None:
    from terractl.security import declares_rule_definition_pragma

    pragma = ["# boundary-scan: rule-definitions"]
    assert declares_rule_definition_pragma(pragma, "terractl/security.py")
    assert not declares_rule_definition_pragma(pragma, "terractl/evidence.py")
    assert not declares_rule_definition_pragma(pragma, "tests/security/test_repository_security.py")


def test_the_fixture_pragma_is_honoured_only_under_tests(tmp_path: Path) -> None:
    body = "# secret-scan: synthetic-fixture\napi_key = ABCDEFGHIJKLMNOP\n"
    (tmp_path / "tests").mkdir()
    inside = tmp_path / "tests" / "test_fixture.py"
    inside.write_text(body, encoding="utf-8")
    outside = tmp_path / "shipped.py"
    outside.write_text(body, encoding="utf-8")
    assert scan_for_secrets([inside], root=tmp_path) == []
    assert [finding.rule for finding in scan_for_secrets([outside], root=tmp_path)] == [
        "assigned-credential"
    ]


def test_every_service_drops_privilege_escalation() -> None:
    assert inspect_container_security(_rendered_compose()) == []


def test_container_inspection_reports_a_public_bind() -> None:
    config = {"services": {"demo": {"security_opt": ["no-new-privileges:true"], "ports": []}}}
    services = config["services"]
    services["demo"]["ports"] = [{"host_ip": "0.0.0.0"}]
    assert inspect_container_security(config) == ["demo publishes a non-loopback port"]


def test_container_inspection_refuses_an_empty_configuration() -> None:
    with pytest.raises(ValueError, match="no services"):
        inspect_container_security({"services": {}})


def test_application_image_runs_as_an_unprivileged_user() -> None:
    assert dockerfile_runs_unprivileged()


def test_boundary_scanner_reports_a_missing_disclaimer(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Nothing here\n", encoding="utf-8")
    (tmp_path / "docs.md").write_text("clean\n", encoding="utf-8")
    findings = _boundary_findings_for(tmp_path)
    assert Finding("missing-public-disclaimer", "README.md", 1) in findings


def _boundary_findings_for(root: Path) -> list[Finding]:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return scan_public_boundary(root)
