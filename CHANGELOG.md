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

### Security

- Upgraded `fastapi` to 0.141.1, `python-multipart` to 0.0.31, and `filelock` to 3.20.3,
  which clears fourteen advisories that the dependency audit reported against the pinned
  set. Six of them were in `starlette`, reachable only by moving `fastapi` off its
  `starlette<0.48.0` ceiling, so the framework bump was the fix rather than a bystander.

### Changed

- The publish gate now blocks on a check that ran and failed, and reports rather than
  blocks on a requirement that was never observed. `terra.sh evidence` gained
  `--allow-unobserved` for exactly that distinction, `classify_failures` enforces the
  split, and the default command is unchanged, so every CI runner still fails while
  anything is unobserved. Recorded as decision 11.
- The documentation command checker no longer reads an option flag as a subcommand, which
  previously made any documented command with a flag look invented.

### Fixed

- The contract and performance gates printed captured subprocess output directly, so the
  box drawing and arrow characters that Newman and k6 emit raised `UnicodeEncodeError` on
  a Windows console. Both gates had already run and written their reports by then, so a
  finished, passing step reported a crash. Compose output was already protected against
  this; the same protection now covers every path that echoes subprocess output, and the
  writer lives in one module rather than being private to the lifecycle code.
- The Newman service pinned `postman/newman:6.2.1-alpine`, which has never existed on
  Docker Hub. The contract run failed to pull it and then reported only that no JSON
  report was produced. The pin is now `6.1.3-alpine`, the newest published Alpine tag.
  Every other pinned image was checked at the same time and all of them resolve.
- `terra.sh up` capped the whole build and start at ten minutes, which a first run on a
  clean machine cannot meet. It pulls three service images and builds five of its own
  before anything is healthy, so the command reported a timeout while the build was still
  making progress, and the environment finished coming up healthy afterwards. The ceiling
  is now generous by default and `TERRA_UP_TIMEOUT_SECONDS` overrides it. Found by running
  the clean checkout verification on a machine with no images cached, which is the same
  path anyone cloning the repository takes.
- The publish gate never pushed `main` when it created the repository. `gh repo create
  --push` publishes only the checked-out branch, which is a stage branch, so `main` would
  have been absent and a stage branch would have become the default. Every stage pull
  request would then have had no base to open against. The gate now creates the remote
  without pushing, pushes `main` first, and sets it as the default branch.
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
