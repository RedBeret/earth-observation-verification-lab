#!/usr/bin/env bash
# Give the machine back: reset the project, then stop Docker itself.
#
# This is deliberately NOT a `terra.sh` subcommand. Every CI runner in this repository is
# allowed to call `./scripts/bootstrap.sh` and `./scripts/terra.sh` and nothing else, so a
# subcommand that stops the Docker daemon could be wired into a pipeline and would then
# kill the runner it was executing on. Project cleanup belongs in the CLI. Stopping the
# host's Docker does not.
#
#   ./scripts/shutdown-host.sh            # report what would happen
#   ./scripts/shutdown-host.sh --apply    # do it
#
# The project reset is cross platform. Stopping Docker Desktop and WSL only applies to
# Windows, and this script says so rather than pretending otherwise on other systems.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY="no"
if [[ "${1:-}" == "--apply" ]]; then
  APPLY="yes"
fi

case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) HOST="windows" ;;
  *) HOST="other" ;;
esac

if [[ "$APPLY" != "yes" ]]; then
  printf '%s\n' "Would reset the project:"
  ./scripts/terra.sh reset || true
  printf '%s\n' ""
  if [[ "$HOST" == "windows" ]]; then
    printf '%s\n' "Would then quit Docker Desktop and run: wsl --shutdown"
  else
    printf '%s\n' "Docker Desktop and WSL shutdown are Windows only. On this system, stop"
    printf '%s\n' "Docker with whatever your platform uses, for example: systemctl stop docker"
  fi
  printf '%s\n' ""
  printf '%s\n' "Nothing changed. Re-run with --apply."
  exit 0
fi

# 1. Project first, so nothing of ours is left holding a volume or a network.
./scripts/terra.sh reset --apply

if [[ "$HOST" != "windows" ]]; then
  printf '%s\n' "Project reset. Stopping the Docker daemon is left to you on this platform."
  exit 0
fi

# 2. Docker Desktop. Quitting the app also stops its own WSL distribution, which is where
#    most of the memory goes.
printf '%s\n' "Stopping Docker Desktop."
powershell.exe -NoProfile -NonInteractive -Command \
  "Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force" || true

# 3. WSL. This is what actually releases vmmem back to Windows.
printf '%s\n' "Shutting down WSL."
wsl.exe --shutdown || true

printf '%s\n' ""
printf '%s\n' "Remaining:"
wsl.exe --list --running 2>/dev/null | tr -d '\0' || true
printf '%s\n' "docker ps should now fail to connect, which is the point."
