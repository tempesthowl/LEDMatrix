#!/usr/bin/env bash
# Dev launcher: run the LEDMatrix display controller in emulator mode on Windows.
# Pins LEDMATRIX_CACHE_DIR so the Flask web UI and this process share the on-demand
# command cache. Without this, /remote button taps never reach the emulator.
#
# Respawn loop: when the controller exits with code 42, restart it. Any other
# exit code (including Ctrl+C's 130) terminates the wrapper. Code 42 is issued
# by the /api/v3/display/restart handler (display_controller.py) so the "Apply
# & Restart" button in /v3/remote triggers a real process respawn, clearing
# all in-memory state (loaded plugins, Vegas render buffers, available_modes).

set -euo pipefail

export LEDMATRIX_CACHE_DIR="C:/Users/ericv/AppData/Local/LEDMatrix/cache"
mkdir -p "$LEDMATRIX_CACHE_DIR"
export EMULATOR=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "[dev-emulator] LEDMATRIX_CACHE_DIR=$LEDMATRIX_CACHE_DIR"
echo "[dev-emulator] CWD=$(pwd)"
echo "[dev-emulator] Respawn loop: exit 42 restarts, any other exit stops."
echo ""

while true; do
  echo "[dev-emulator] starting python run.py -e..."
  if python run.py -e; then
    ec=0
  else
    ec=$?
  fi
  if [ "$ec" -eq 42 ]; then
    echo "[dev-emulator] exit 42 (restart requested) — respawning in 1s..."
    sleep 1
    continue
  fi
  echo "[dev-emulator] python exited $ec — not respawning, stopping."
  exit "$ec"
done
