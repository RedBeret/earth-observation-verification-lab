#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x .venv/Scripts/python.exe ]]; then
  PYTHON=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  printf '%s\n' "Local environment missing. Run ./scripts/bootstrap.sh first." >&2
  exit 2
fi

exec "$PYTHON" -m terractl.cli "$@"
