"""Imagery ingest API entrypoint."""

from terrawatch.api import create_app
from terrawatch.ingest import register_ingest_routes

app = create_app("ingest-api", ("postgres", "minio", "nats"))
register_ingest_routes(app)
