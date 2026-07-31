# Interface Control Document

Version 1.0.0. All identifiers, coordinates, and times are synthetic.

## Conventions

- Every request may carry `X-Request-ID`. It is echoed on the response. An absent or
  malformed value is replaced with a generated identifier.
- Every failure uses one envelope:
  `{"error": {"code", "message", "details", "request_id"}}`.
- Schemas are versioned and live under `requirements/schemas`.

## Ingest API

Default local port 18001.

### `POST /v1/scenes`

Multipart request with a `file` part holding a GeoTIFF and a `metadata` part holding the
JSON described by `requirements/schemas/scene-metadata.schema.json`.

| Response | Meaning |
|---|---|
| 202 | Scene accepted and queued for cataloging |
| 409 | The scene identifier already refers to different content |
| 422 | The raster or metadata failed validation |

A rejected scene leaves no accepted record, no catalog item, and no retained object.

## Event API

Default local port 18002.

### `POST /v1/events`

JSON body described by `requirements/schemas/telemetry-event.schema.json`, plus a
required `Idempotency-Key` header of 1 to 128 safe characters.

| Response | Meaning |
|---|---|
| 202 | New event accepted |
| 200 | Identical replay, reported with `"replayed": true` |
| 409 | The key or the event identifier already refers to a different submission |
| 422 | Missing or malformed key, or an invalid event |

## Analysis API

Default local port 18003.

| Route | Purpose |
|---|---|
| `GET /v1/scenes/{scene_id}` | One accepted scene |
| `GET /v1/scenes/{scene_id}/stac` | The STAC item for an accepted scene |
| `GET /v1/scenes` | Scene search by `bbox`, `start`, `end`, `page`, `page_size` |
| `GET /v1/events/{event_id}` | One telemetry event |
| `GET /v1/events` | Event search with the same filters |
| `GET /v1/correlations/{correlation_id}` | One correlation |
| `GET /v1/analysis-results/{event_id}` | The analysis result for an event |
| `GET /v1/provenance/{resource_type}/{resource_id}` | Provenance for a scene, event, correlation, or analysis result |

Search responses use the page envelope `{"items", "page", "page_size", "total"}`.
A malformed `bbox` or pagination value returns 422 with the shared envelope. An unknown
identifier returns 404.

## Messaging

| Subject | Producer | Consumer |
|---|---|---|
| Imagery accepted | Ingest API outbox | Imagery worker |
| Telemetry accepted | Event API outbox | Correlation worker |
| Dead letter | Either worker after retry exhaustion | Operator inspection |

Every message uses the envelope in `requirements/schemas/message-envelope.schema.json`
with `schema_version`, `message_id`, `event_type`, `occurred_at`, `aggregate_id`, and a
typed `payload`. Publishers set `Nats-Msg-Id` so JetStream can deduplicate.

## Operational endpoints

Every service exposes `/healthz`, `/readyz`, `/metrics`, and `/openapi.json`. Readiness
returns 200 when all declared dependencies are reachable and 503 otherwise, with a
per-dependency breakdown in the body.
