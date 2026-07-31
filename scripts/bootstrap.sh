#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

choose_python() {
  if command -v py >/dev/null 2>&1 && py -3.12 -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
    printf '%s\n' "py -3.12"
    return
  fi
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '%s\n' "Python 3.12 is required." >&2
  exit 2
}

PYTHON_COMMAND="$(choose_python)"
if [[ ! -d .venv ]]; then
  # shellcheck disable=SC2086
  $PYTHON_COMMAND -m venv .venv
fi

if [[ -x .venv/Scripts/python.exe ]]; then
  VENV_PYTHON=.venv/Scripts/python.exe
else
  VENV_PYTHON=.venv/bin/python
fi

"$VENV_PYTHON" -m pip install --disable-pip-version-check --upgrade "pip==25.1.1"
"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements/dev.txt

"$VENV_PYTHON" -m terractl.environment initialize

printf '%s\n' "Bootstrap complete: $("$VENV_PYTHON" --version)"
