#!/usr/bin/env bash
# Dev launcher: run the LEDMatrix Flask web UI on Windows.
# Pins LEDMATRIX_CACHE_DIR to the same path as dev-emulator.sh so /remote
# button taps actually reach the running emulator process.
# See plan: ~/.claude/plans/recursive-orbiting-kahn.md

set -euo pipefail

export LEDMATRIX_CACHE_DIR="C:/Users/ericv/AppData/Local/LEDMatrix/cache"
mkdir -p "$LEDMATRIX_CACHE_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "[dev-webui] LEDMATRIX_CACHE_DIR=$LEDMATRIX_CACHE_DIR"
echo "[dev-webui] CWD=$(pwd)"
echo "[dev-webui] Starting web UI at http://localhost:5050 (Ctrl+C to stop)..."
echo ""

exec python web_interface/start.py
