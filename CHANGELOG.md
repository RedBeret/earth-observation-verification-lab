# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- Approved implementation plan, durable worklog, public-safe project boundary, data
  provenance policy, security policy, community files, and MIT license.
- Project-local Python 3.12 CLI foundation, exact direct dependency pins, validation and
  evidence primitives, formal requirements and procedures, deterministic synthetic
  GeoTIFF/event generators, canonical fixtures, and unit verification suite.
- Isolated Docker Compose environment with PostGIS, MinIO, NATS JetStream, five
  application containers, guarded lifecycle operations, migrations, readiness,
  metrics, and live integration verification.
- Verified imagery ingestion with bounded validation, digest-addressed object storage,
  transactional outbox delivery, durable worker processing, STAC/PostGIS cataloging,
  idempotent replay, conflict handling, structured diagnostics, and executable
  `TP-ING-002` coverage.
- Verified telemetry ingestion, canonical idempotency, deterministic PostGIS
  correlation, event-level analysis, spatial/time search, pagination, exact revision
  provenance, common error envelopes, and executable `TP-API-004`/`TP-SYS-001`
  coverage.
