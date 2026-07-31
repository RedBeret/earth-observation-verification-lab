"""Imagery ingest API entrypoint."""

from terrawatch.api import create_app

app = create_app("ingest-api", ("postgres", "minio", "nats"))
