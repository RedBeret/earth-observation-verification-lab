#!/usr/bin/env bash
# The only supported path to a public repository.
#
# Nothing here pushes until the safety checks pass on the exact commit being published.
# Run it with no arguments to check only. Pass --push to publish after the checks pass.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTE_NAME="${REMOTE_NAME:-origin}"
REPOSITORY="${REPOSITORY:-RedBeret/earth-observation-verification-lab}"
VISIBILITY="${VISIBILITY:-public}"
PUSH="no"
if [[ "${1:-}" == "--push" ]]; then
  PUSH="yes"
fi

if [[ -n "$(git status --porcelain)" ]]; then
  printf '%s\n' "Refusing to publish a dirty working tree." >&2
  exit 2
fi

REVISION="$(git rev-parse HEAD)"
printf '%s\n' "Publish gate for $REVISION"

# 1. The repository must pass its own static gates on this exact commit.
./scripts/terra.sh validate
./scripts/terra.sh traceability
./scripts/terra.sh test unit
./scripts/terra.sh test contract --mode static
./scripts/terra.sh test security
./scripts/terra.sh test pipeline

# 2. The evidence package must exist and reconcile. Publishing an unverified commit is
#    the failure mode this whole project exists to prevent.
./scripts/terra.sh evidence

printf '%s\n' "Publish gate passed for $REVISION"

if [[ "$PUSH" != "yes" ]]; then
  printf '%s\n' "Checks only. Re-run with --push to publish."
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  printf '%s\n' "The GitHub CLI is required to publish." >&2
  exit 2
fi

if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  # Create the remote but do not let gh push. On a non-bare repository --push publishes
  # only the currently checked out branch, which is a stage branch. That would leave main
  # unpublished and make a stage branch the default, so every stage pull request would
  # have no base to open against.
  gh repo create "$REPOSITORY" "--${VISIBILITY}" --source=. --remote="$REMOTE_NAME"
fi

# main goes first so it becomes the default branch and every stage pull request has a base.
git push --set-upstream "$REMOTE_NAME" main
gh repo edit "$REPOSITORY" --default-branch main

for branch in \
  codex/stage-2-infrastructure \
  codex/stage-3-imagery \
  codex/stage-4-correlation \
  codex/stage-5-resilience \
  codex/stage-6-evidence \
  codex/stage-7-ci \
  codex/stage-8-release; do
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git push --set-upstream "$REMOTE_NAME" "$branch"
  fi
done

printf '%s\n' "Branches pushed. Open the stage pull requests in order."
