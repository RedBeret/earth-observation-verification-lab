# Architecture

TerraWatch is a synthetic Earth-observation platform for the fictional Pine Valley
Wildfire Exercise. It exists to demonstrate systems integration and verification, not to
reproduce any real system.

## Components

| Component | Responsibility |
|---|---|
| `services/ingest-api` | Accept and validate GeoTIFF scenes, store objects, write the outbox |
| `services/event-api` | Accept and validate telemetry events with idempotency keys |
| `services/analysis-api` | Serve scenes, events, correlations, analysis results, provenance |
| `terrawatch/imagery_worker.py` | Revalidate stored rasters and build STAC items |
| `terrawatch/correlation.py` | Correlate events against scene footprints and time windows |
| PostGIS | Metadata, geometries, outbox, dead letters, processing attempts |
| MinIO | Original scene objects |
| NATS JetStream | Versioned imagery and telemetry event streams |

## Data flow

1. A client posts a scene to the ingest API. The raster is validated synchronously.
   Only a valid scene is retained in object storage.
2. Acceptance writes a database record and an outbox row in one transaction.
3. The outbox publisher moves the row onto the imagery stream.
4. The imagery worker reads the stored object, revalidates it, and writes a
   STAC-compatible catalog item plus a PostGIS footprint.
5. A client posts a telemetry event with an `Idempotency-Key`. The same transactional
   outbox pattern applies.
6. The correlation worker consumes telemetry, correlates spatially with `ST_Covers` and
   temporally within an inclusive fifteen minute window, and writes analysis results.
7. The analysis API serves the resulting records and their provenance.

## Delivery guarantees

- Writes use a transactional outbox, so a database commit and an event publication
  cannot disagree.
- Workers acknowledge explicitly, retry with bounded exponential backoff and jitter, and
  write a visible dead letter when retries are exhausted.
- Duplicate delivery is idempotent by content digest and idempotency key.
- Boundary points match, because `ST_Covers` includes the boundary.

## Operational surface

Every API exposes `/healthz`, `/readyz`, `/metrics`, an OpenAPI document, an
`X-Request-ID` header, and one machine-readable error envelope:

```json
{"error": {"code": "", "message": "", "details": {}, "request_id": ""}}
```

Readiness reports each dependency separately and returns 503 while any dependency is
unavailable. That is what the resilience drills observe.

## Safety boundaries

- Published ports bind to loopback only.
- Application containers run unprivileged, read only, with `no-new-privileges`.
- Destructive lifecycle actions verify the Compose project name and the project label on
  every container before acting.
- Local credentials are generated into `.env.local` and never appear in evidence.

See `PROJECT_BOUNDARY.md` for the content boundary and `SECURITY.md` for the scanner
rules and their two documented exceptions.
