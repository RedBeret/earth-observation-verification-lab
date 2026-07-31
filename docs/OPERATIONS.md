# Operator Guide

Every local and CI workflow goes through one entrypoint. Nothing in this repository
expects you to run `docker` or `pytest` by hand.

## First run

```bash
./scripts/bootstrap.sh
./scripts/terra.sh doctor
```

`./scripts/bootstrap.sh` creates the project virtual environment, installs pinned
dependencies, and generates `.env.local`. That file holds locally generated
credentials, is ignored by Git, and is never copied into evidence.

`./scripts/terra.sh doctor` inspects required tooling without changing anything. Fix
whatever it reports before continuing.

## Daily commands

| Command | Purpose |
|---|---|
| `./scripts/terra.sh validate` | Check schemas, procedures, and traceability |
| `./scripts/terra.sh traceability` | Fail on unmapped or stale requirements |
| `./scripts/terra.sh seed` | Regenerate the deterministic synthetic fixtures |
| `./scripts/terra.sh up` | Build and start the labeled Compose project |
| `./scripts/terra.sh status` | Report required services and their health |
| `./scripts/terra.sh down` | Remove only verified project containers |
| `./scripts/terra.sh diagnostics` | Write a redacted diagnostic bundle |
| `./scripts/terra.sh evidence` | Render and reconcile the evidence package |
| `./scripts/terra.sh clean-room` | Prove teardown touches nothing else |

## Test levels

```bash
./scripts/terra.sh test unit
./scripts/terra.sh test contract --mode static
./scripts/terra.sh test security
./scripts/terra.sh test pipeline
./scripts/terra.sh test integration
./scripts/terra.sh test system
./scripts/terra.sh test contract --mode postman
./scripts/terra.sh test performance
./scripts/terra.sh test resilience
```

The first four run without a live environment. The rest need `./scripts/terra.sh up`
to have succeeded first.

`./scripts/terra.sh test contract` with no mode runs the local contract tests and then
the Postman collection against the running system.

## Formal procedures

```bash
./scripts/terra.sh procedure run TP-ING-002
./scripts/terra.sh procedure run TP-API-004
./scripts/terra.sh procedure run TP-SYS-001
./scripts/terra.sh procedure run TP-RES-003
./scripts/terra.sh procedure run TP-EVD-005
```

Each identifier maps to a YAML definition in `procedures` and to the exact tests that
produce its result. System and resilience procedures take an exclusive lock so two runs
cannot fight over the same environment.

## Controlled faults

Fault commands refuse to act without `--apply`, verify the Compose project and container
identity first, and record their state in an ignored file.

```bash
./scripts/terra.sh fault list
./scripts/terra.sh fault inject postgres-unavailable --apply
./scripts/terra.sh fault clear --apply
```

Always clear a fault before leaving the environment. The resilience tests already do
this in a `finally` path; the manual commands exist for investigation.

## Where output goes

- `artifacts/junit` holds raw runner output.
- `artifacts/reports` holds Newman and k6 reports.
- `artifacts/evidence` holds rendered, reconciled evidence packages.
- `artifacts/diagnostics` holds redacted diagnostic bundles.
- `artifacts/state` holds lock files and controlled fault state.

All of it is ignored by Git. Evidence is redacted before it is written.
