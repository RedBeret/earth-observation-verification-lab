#!/usr/bin/env bash
# Run the complete acceptance sequence in a throwaway clone of the current commit.
#
# The point is to prove the repository is self-contained: nothing in the sequence may
# depend on a generated file, a virtual environment, or a Docker volume that only exists
# in the working checkout. The clone is left in place so its evidence can be inspected,
# and its path is printed at the end.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  printf '%s\n' "Refusing to verify a dirty working tree. Commit or stash first." >&2
  exit 2
fi

REVISION="$(git rev-parse HEAD)"
WORKSPACE="${1:-$(mktemp -d -t terrawatch-clean-XXXXXX)}"
CHECKOUT="$WORKSPACE/earth-observation-verification-lab"

printf '%s\n' "Cloning $REVISION into $CHECKOUT"
git clone --quiet --no-hardlinks "$ROOT" "$CHECKOUT"
cd "$CHECKOUT"
git checkout --quiet "$REVISION"

./scripts/bootstrap.sh
./scripts/terra.sh doctor
./scripts/terra.sh validate
./scripts/terra.sh traceability
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
./scripts/terra.sh up
./scripts/terra.sh status
./scripts/terra.sh down

printf '%s\n' "Clean checkout verification finished for $REVISION"
printf '%s\n' "Evidence: $CHECKOUT/artifacts/evidence"
