#!/bin/bash

# jemalloc LD_PRELOAD installer for ledmatrix.service.
#
# Why: the display controller is a long-running Python+Pillow process. Every
# plugin tick allocates fresh PIL Image buffers; Python GCs them, but glibc's
# malloc rarely returns the freed pages to the OS. Result: monotonic RSS growth
# (~260 MB/hr observed on the live Pi at 2026-06-02). jemalloc returns freed
# pages aggressively and typically flattens the curve by 30-50%.
#
# What this does:
#   1. apt-install libjemalloc2 (if missing).
#   2. Auto-detect the libjemalloc.so.2 path (arch-portable).
#   3. Write /etc/systemd/system/ledmatrix.service.d/jemalloc.conf with
#      Environment=LD_PRELOAD=<path>.
#   4. systemctl daemon-reload (does NOT restart ledmatrix — caller decides).
#
# Idempotent: re-running is a no-op if the package is installed and the
# drop-in already contains the correct path.

set -e

if [ "$EUID" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "Installing jemalloc preload for ledmatrix.service..."

# ---------------------------------------------------------------------------
# 1. Install libjemalloc2 if missing.
# ---------------------------------------------------------------------------
if dpkg -s libjemalloc2 >/dev/null 2>&1; then
    echo "✓ libjemalloc2 already installed"
else
    echo "Installing libjemalloc2..."
    $SUDO apt update || true
    $SUDO apt install -y libjemalloc2
fi

# ---------------------------------------------------------------------------
# 2. Locate the shared object. Path differs by arch (aarch64 vs armhf vs amd64
#    vs the rare future Pi 5 64-bit variant), so dpkg -L is authoritative.
# ---------------------------------------------------------------------------
JEMALLOC_SO=$(dpkg -L libjemalloc2 2>/dev/null | grep -E 'libjemalloc\.so\.2$' | head -n 1)

if [ -z "$JEMALLOC_SO" ] || [ ! -f "$JEMALLOC_SO" ]; then
    echo "✗ Could not locate libjemalloc.so.2 even after install"
    echo "  dpkg -L libjemalloc2 output:"
    dpkg -L libjemalloc2 || true
    exit 1
fi

echo "✓ Found libjemalloc.so.2 at: $JEMALLOC_SO"

# ---------------------------------------------------------------------------
# 3. Write the systemd drop-in. Drop-ins compose with the base unit so we
#    don't touch systemd/ledmatrix.service in the repo — the drop-in is what
#    appears under /etc/systemd/system/ledmatrix.service.d/.
# ---------------------------------------------------------------------------
DROPIN_DIR="/etc/systemd/system/ledmatrix.service.d"
DROPIN_FILE="$DROPIN_DIR/jemalloc.conf"

$SUDO mkdir -p "$DROPIN_DIR"

DROPIN_CONTENT="# Installed by scripts/install/install_jemalloc.sh
# Replaces glibc malloc with jemalloc for the display-controller process.
# jemalloc returns freed pages to the OS far more aggressively than glibc;
# this prevents the slow RSS climb that long-running Python+PIL processes
# exhibit on Linux. Drop-in (not unit edit) so the repo unit stays clean.
[Service]
Environment=LD_PRELOAD=$JEMALLOC_SO
"

# Only rewrite if content differs — keeps daemon-reload idempotent.
if [ -f "$DROPIN_FILE" ] && [ "$($SUDO cat "$DROPIN_FILE")" = "$DROPIN_CONTENT" ]; then
    echo "✓ Drop-in already up to date at $DROPIN_FILE"
else
    echo "Writing drop-in to $DROPIN_FILE..."
    echo "$DROPIN_CONTENT" | $SUDO tee "$DROPIN_FILE" > /dev/null
    $SUDO chmod 644 "$DROPIN_FILE"
fi

# ---------------------------------------------------------------------------
# 4. Reload systemd so the next ledmatrix restart picks up the override.
#    Do NOT restart ledmatrix here — first_time_install.sh restarts the
#    service in its own dedicated step at the end of the run.
# ---------------------------------------------------------------------------
$SUDO systemctl daemon-reload

echo ""
echo "✓ jemalloc preload configured"
echo ""
echo "Verification (after ledmatrix restarts):"
echo "  sudo cat /proc/\$(pgrep -f run.py)/maps | grep jemalloc"
echo "Expected: at least one libjemalloc.so.2 mapped region."
