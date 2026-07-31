import pytest

from terractl.environment import LocalEnvironment

pytestmark = pytest.mark.unit


def test_generated_database_url_has_bounded_outage_timeouts() -> None:
    rendered = LocalEnvironment(
        compose_project_name="unit-project",
        postgres_password="unit-password",
        minio_root_user="unit-user",
        minio_root_password="unit-minio-password",
        nats_token="unit-token",
    ).render()

    database_line = next(line for line in rendered.splitlines() if line.startswith("DATABASE_URL="))
    assert "connect_timeout=3" in database_line
    assert "tcp_user_timeout=3000" in database_line
