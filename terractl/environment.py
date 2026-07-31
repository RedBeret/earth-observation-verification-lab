"""Local environment identity and generated configuration."""

from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

from pydantic import BaseModel

from terrawatch.constants import ENVIRONMENT_NAME, PROJECT_SLUG


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def artifacts_root() -> Path:
    return project_root() / "artifacts"


def compose_project_name(root: Path | None = None) -> str:
    resolved = (root or project_root()).resolve()
    suffix = hashlib.sha256(str(resolved).lower().encode("utf-8")).hexdigest()[:8]
    return f"terrawatch-{ENVIRONMENT_NAME}-{suffix}"


class LocalEnvironment(BaseModel):
    project_slug: str = PROJECT_SLUG
    compose_project_name: str
    postgres_password: str
    minio_root_user: str
    minio_root_password: str
    nats_token: str

    def render(self) -> str:
        values = {
            "COMPOSE_PROJECT_NAME": self.compose_project_name,
            "POSTGRES_DB": "terrawatch",
            "POSTGRES_USER": "terrawatch",
            "POSTGRES_PASSWORD": self.postgres_password,
            "MINIO_ROOT_USER": self.minio_root_user,
            "MINIO_ROOT_PASSWORD": self.minio_root_password,
            "NATS_TOKEN": self.nats_token,
            "INGEST_API_PORT": "18001",
            "EVENT_API_PORT": "18002",
            "ANALYSIS_API_PORT": "18003",
            "POSTGRES_PORT": "15432",
            "MINIO_API_PORT": "19000",
            "MINIO_CONSOLE_PORT": "19001",
            "NATS_CLIENT_PORT": "14222",
            "NATS_MONITOR_PORT": "18222",
            "DATABASE_URL": (
                "postgresql+psycopg://terrawatch:"
                f"{self.postgres_password}@127.0.0.1:15432/terrawatch"
            ),
            "MINIO_ENDPOINT": "127.0.0.1:19000",
            "MINIO_ACCESS_KEY": self.minio_root_user,
            "MINIO_SECRET_KEY": self.minio_root_password,
            "MINIO_SECURE": "false",
            "MINIO_BUCKET": "scenes",
            "NATS_URL": "nats://127.0.0.1:14222",
        }
        return "".join(f"{key}={value}\n" for key, value in values.items())


def initialize_environment(path: Path | None = None) -> Path:
    target = path or project_root() / ".env.local"
    if target.exists():
        existing = {}
        for line in target.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                existing[key] = value
        environment = LocalEnvironment(
            compose_project_name=existing.get("COMPOSE_PROJECT_NAME", compose_project_name()),
            postgres_password=existing["POSTGRES_PASSWORD"],
            minio_root_user=existing["MINIO_ROOT_USER"],
            minio_root_password=existing["MINIO_ROOT_PASSWORD"],
            nats_token=existing["NATS_TOKEN"],
        )
    else:
        environment = LocalEnvironment(
            compose_project_name=compose_project_name(),
            postgres_password=secrets.token_urlsafe(32),
            minio_root_user=f"local-{secrets.token_hex(6)}",
            minio_root_password=secrets.token_urlsafe(32),
            nats_token=secrets.token_urlsafe(32),
        )
    target.write_text(environment.render(), encoding="utf-8")
    return target


def ensure_artifact_directories() -> None:
    for name in ("evidence", "junit", "diagnostics", "reports", "state"):
        (artifacts_root() / name).mkdir(parents=True, exist_ok=True)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "initialize":
        print("usage: python -m terractl.environment initialize", file=sys.stderr)
        return 2
    ensure_artifact_directories()
    path = initialize_environment()
    print(f"Initialized local configuration at {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
