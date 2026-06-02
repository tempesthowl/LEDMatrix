#!/bin/bash

# Systemd safety-net installer for ledmatrix.service.
#
# Two belts-and-suspenders pieces so a future memory-leak regression can never
# OOM the Pi (historically OOM has corrupted SD cards):
#
#   1. /etc/systemd/system/ledmatrix.service.d/safety.conf
#        MemoryMax=1400M       systemd kills+respawns instead of kernel OOM
#        Restart=always        also respawns after a MemoryMax kill
#        RestartSec=10s        breathing room before respawn
#
#   2. /etc/systemd/system/ledmatrix-restart.{timer,service}
#        Daily 04:00 America/Chicago hot-restart so any slow residual creep
#        never gets a chance to build up.
#
# Idempotent: re-running rewrites the unit files (no-op if content matches),
# daemon-reloads, and re-enables the timer.

set -e

if [ "$EUID" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "Installing ledmatrix systemd safety net..."

# ---------------------------------------------------------------------------
# 1. Memory ceiling + restart policy drop-in.
# ---------------------------------------------------------------------------
DROPIN_DIR="/etc/systemd/system/ledmatrix.service.d"
SAFETY_FILE="$DROPIN_DIR/safety.conf"

$SUDO mkdir -p "$DROPIN_DIR"

SAFETY_CONTENT="# Installed by scripts/install/install_systemd_safety_net.sh
# Cap the display-controller process so a runaway leak can't OOM the kernel.
# Kernel OOM has historically corrupted the SD card; controlled systemd kill
# + respawn is the safe failure mode.
[Service]
MemoryMax=1400M
Restart=always
RestartSec=10s
"

if [ -f "$SAFETY_FILE" ] && [ "$($SUDO cat "$SAFETY_FILE")" = "$SAFETY_CONTENT" ]; then
    echo "✓ safety.conf already up to date"
else
    echo "Writing $SAFETY_FILE..."
    echo "$SAFETY_CONTENT" | $SUDO tee "$SAFETY_FILE" > /dev/null
    $SUDO chmod 644 "$SAFETY_FILE"
fi

# ---------------------------------------------------------------------------
# 2. Daily restart timer + oneshot service.
# ---------------------------------------------------------------------------
RESTART_SERVICE="/etc/systemd/system/ledmatrix-restart.service"
RESTART_TIMER="/etc/systemd/system/ledmatrix-restart.timer"

RESTART_SERVICE_CONTENT="[Unit]
Description=Daily restart of ledmatrix.service to prevent slow memory creep
After=ledmatrix.service

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart ledmatrix.service
"

RESTART_TIMER_CONTENT="[Unit]
Description=Fire ledmatrix-restart daily at 04:00 America/Chicago

[Timer]
OnCalendar=*-*-* 04:00:00 America/Chicago
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
"

if [ -f "$RESTART_SERVICE" ] && [ "$($SUDO cat "$RESTART_SERVICE")" = "$RESTART_SERVICE_CONTENT" ]; then
    echo "✓ ledmatrix-restart.service already up to date"
else
    echo "Writing $RESTART_SERVICE..."
    echo "$RESTART_SERVICE_CONTENT" | $SUDO tee "$RESTART_SERVICE" > /dev/null
    $SUDO chmod 644 "$RESTART_SERVICE"
fi

if [ -f "$RESTART_TIMER" ] && [ "$($SUDO cat "$RESTART_TIMER")" = "$RESTART_TIMER_CONTENT" ]; then
    echo "✓ ledmatrix-restart.timer already up to date"
else
    echo "Writing $RESTART_TIMER..."
    echo "$RESTART_TIMER_CONTENT" | $SUDO tee "$RESTART_TIMER" > /dev/null
    $SUDO chmod 644 "$RESTART_TIMER"
fi

# ---------------------------------------------------------------------------
# 3. Reload, enable+start timer. Do NOT restart ledmatrix here —
#    first_time_install.sh restarts in its dedicated step at the end.
# ---------------------------------------------------------------------------
$SUDO systemctl daemon-reload
$SUDO systemctl enable ledmatrix-restart.timer
$SUDO systemctl start ledmatrix-restart.timer || echo "⚠ Failed to start timer (will start on reboot)"

echo ""
echo "✓ Safety net installed"
echo ""
echo "Verification:"
echo "  systemctl show ledmatrix.service -p MemoryMax     # expect ≈1468006400 (1400M)"
echo "  systemctl list-timers ledmatrix-restart.timer    # expect next trigger 04:00 CT"
