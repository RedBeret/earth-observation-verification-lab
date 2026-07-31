"""Stable project-wide constants."""

PROJECT_SLUG = "earth-observation-verification-lab"
PROJECT_LABEL = "org.northstar.project"
PROJECT_LABEL_VALUE = PROJECT_SLUG
ENVIRONMENT_NAME = "demo-west"
REQUIREMENTS_VERSION = "1.0.0"
ALGORITHM_VERSION = "correlator-1.0.0"
TEMPORAL_WINDOW_SECONDS = 900
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

IMAGERY_SUBJECT = "terrawatch.imagery.ingested.v1"
TELEMETRY_SUBJECT = "terrawatch.telemetry.accepted.v1"
IMAGERY_DLQ_SUBJECT = "terrawatch.dlq.imagery.v1"
CORRELATION_DLQ_SUBJECT = "terrawatch.dlq.correlation.v1"
