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
- Identity-guarded controlled faults, redacted failure diagnostics, an exclusive run
  lock for system and resilience runs, operator fault commands, the clean-room
  isolation proof, and the resilience drills.
- An asserted Postman interface contract with static completeness checks, and pinned
  Newman and k6 services that write machine-readable reports.
- Versioned performance thresholds that both the k6 script and the Python gate read
  from one file.
- A repository security gate covering credential shapes, the public boundary, container
  posture, and the two documented scanner exceptions.
- Reconciled multi-format evidence built from raw runner output, with a digest manifest,
  redaction re-checks, and `not observed` results that cannot pass.
- Jenkins, GitHub Actions, and GitLab definitions sharing one gate sequence, with
  structural tests for parity, strict artifact failure, and unconditional teardown.
- Operator, architecture, test plan, interface control, and troubleshooting documents,
  with tests that verify every documented command, path, and link.
- Clean-checkout verification and publish-gate scripts.

### Fixed

- Clearing a pause fault could fail to resolve the container it had just paused, because
  the service lookup did not list paused containers. The lookup now considers every
  container, filters to the single live candidate, and refuses an ambiguous result. Fault
  injection records its intent before acting, and clearing only unpauses a container that
  is actually paused.
- Test collection failed when two test modules shared a basename. The suite now uses the
  `importlib` import mode.
- Compose output containing characters outside the console code page no longer breaks
  lifecycle commands on Windows.
- A personal directory path was removed from the worklog.
