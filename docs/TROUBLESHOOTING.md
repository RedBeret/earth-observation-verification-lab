# Troubleshooting

Start with `./scripts/terra.sh doctor` and `./scripts/terra.sh status`. Between them
they answer most questions about what is missing.

## The environment will not start

`./scripts/terra.sh up` builds, starts, and waits. If it fails it collects a diagnostic
bundle automatically and prints its path.

- Check that Docker is running and that the loopback ports 18001 to 18003, 15432, 19000,
  19001, 14222, and 18222 are free.
- `.env.local` is regenerated on every `up`, so a stale value is not the cause. If the
  file was deleted, credentials are regenerated and existing volumes will no longer
  match. Run `./scripts/terra.sh down` and start again.

## A service is running but not ready

Readiness reports each dependency separately. Fetch `/readyz` from the service and read
the `dependencies` object rather than guessing.

A 503 during a resilience drill is expected. A 503 outside a drill means a dependency is
genuinely unavailable.

## A controlled fault was left active

```bash
./scripts/terra.sh fault clear --apply
./scripts/terra.sh status
```

Clearing verifies the Compose project and the container identity before it acts, so it
refuses to touch anything created outside this checkout. If it refuses, inspect
`artifacts/state` before doing anything by hand.

## Two runs collided

System and resilience runs share an exclusive lock. If a run reports that another run
holds the project lock, wait for it to finish. If no run is active, the lock file in
`artifacts/state` is stale and can be removed.

## Evidence will not reconcile

Reconciliation fails loudly and names the reason.

| Message | Cause |
|---|---|
| `evidence package is missing` | A renderer did not run; regenerate the package |
| `zero checks cannot reconcile` | No results were collected; run a test level first |
| `unobserved checks cannot pass` | A record was edited; regenerate rather than patch |
| `evidence totals do not agree` | The formats came from different runs |
| `evidence redaction failed` | A credential shape reached a rendered file |
| `evidence manifest hash does not match` | A file was edited after rendering |

Regenerate with `./scripts/terra.sh evidence`. Never edit a package by hand.

## A test refers to a requirement that never ran

`./scripts/terra.sh evidence` records it as `not observed`, and `not observed` fails.
That is the intended behavior. Run the missing level, then regenerate.

## The security gate fails

Findings name the file, the line, and the rule, and never repeat the value. The two
documented exceptions are described in `SECURITY.md`. If a legitimate finding appears in
a test fixture, add the pragma described there rather than weakening a rule.

## Cleaning up

```bash
./scripts/terra.sh down
```

This removes only containers that carry the project label and the expected Compose
project name. Unrelated containers are left alone, and `./scripts/terra.sh clean-room`
proves it.
