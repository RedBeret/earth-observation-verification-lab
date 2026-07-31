# Test Plan

## Objective

Show that every requirement in `requirements/system-requirements.yaml` is verified by a
named, executable check, and that the resulting evidence cannot claim more than was
actually observed.

## Levels

| Level | Marker | Needs a live environment | What it proves |
|---|---|---|---|
| Unit | `unit` | No | Pure logic: validation, hashing, retry bounds, redaction, evidence rendering |
| Contract, static | `contract and static` | No | The Postman collection is complete and asserted |
| Security | `security` | No | Repository boundary, secret shapes, container posture |
| Pipeline | `pipeline` | No | The three CI definitions call the same gates in the same order |
| Integration | `integration` | Yes | Real PostGIS, MinIO, and NATS behavior |
| Contract, Postman | `contract` | Yes | The running interfaces match their documented responses |
| System | `system` | Yes | The end to end workflow and its replay behavior |
| Performance | k6 | Yes | Latency and error thresholds from `performance/thresholds.json` |
| Resilience | `resilience` | Yes | Controlled faults, bounded retry, lossless recovery |

## Formal procedures

| Procedure | Subject |
|---|---|
| `TP-ING-002` | Imagery ingestion, including every rejection case |
| `TP-API-004` | Interface contract and error envelope |
| `TP-SYS-001` | Nominal end to end workflow and duplicate replay |
| `TP-RES-003` | Database outage, bounded retry, recovery without loss |
| `TP-EVD-005` | Evidence consistency, redaction, and traceability |

Each procedure is a YAML document under `procedures` with preconditions, numbered steps,
expected observations, pass and fail criteria, cleanup, and troubleshooting. Running a
procedure executes exactly the tests bound to it and writes its own JUnit file.

## Evidence rules

- JSON is authoritative. Markdown, CSV, and JUnit are rendered from the same in memory
  model and then read back.
- A requirement whose test is absent from the raw runner output is recorded as
  `not observed`, and `not observed` always fails.
- A package with zero checks cannot be rendered.
- A manifest records a SHA-256 digest for every rendered file plus the environment
  identity, so an edited package fails reconciliation.
- Rendering redacts credential shapes, and reconciliation re-checks that redaction held.

## Acceptance sequence

```bash
./scripts/terra.sh test unit
./scripts/terra.sh test contract --mode static
./scripts/terra.sh test security
./scripts/terra.sh test pipeline
./scripts/terra.sh up
./scripts/terra.sh status
./scripts/terra.sh test integration
./scripts/terra.sh procedure run TP-ING-002
./scripts/terra.sh procedure run TP-API-004
./scripts/terra.sh procedure run TP-SYS-001
./scripts/terra.sh test contract --mode postman
./scripts/terra.sh test performance
./scripts/terra.sh procedure run TP-RES-003
./scripts/terra.sh test resilience
./scripts/terra.sh procedure run TP-EVD-005
./scripts/terra.sh evidence
./scripts/terra.sh clean-room
./scripts/terra.sh down
```

A run is reported as fully verified only when that entire sequence succeeds and the
generated evidence reconciles with the raw results. Otherwise the report names the exact
command, the failure, and the environmental limitation.
