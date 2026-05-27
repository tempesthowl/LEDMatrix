#!/bin/bash

# Heartbeat Service Installation Script
# Installs the 10-minute Telegram heartbeat systemd timer.
# Pattern mirrors install_wifi_monitor.sh.

set -e

if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
else
    ACTUAL_USER=$(whoami)
fi

USER_HOME=$(eval echo ~$ACTUAL_USER)
PROJECT_ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
HEARTBEAT_SCRIPT="$PROJECT_ROOT_DIR/scripts/utils/heartbeat.sh"

echo "Installing LED Matrix Heartbeat Service for user: $ACTUAL_USER"
echo "Project root directory: $PROJECT_ROOT_DIR"

if [ ! -f "$HEARTBEAT_SCRIPT" ]; then
    echo "✗ Heartbeat script not found at: $HEARTBEAT_SCRIPT"
    exit 1
fi

chmod 755 "$HEARTBEAT_SCRIPT"

# curl is required (used by heartbeat.sh)
if ! command -v curl >/dev/null 2>&1; then
    echo "Installing curl..."
    if [ "$EUID" -eq 0 ]; then
        apt update || true
        apt install -y curl
    else
        sudo apt update || true
        sudo apt install -y curl
    fi
fi

# Create /etc/ledmatrix/ for env files (shared with backup + ups monitor)
echo ""
echo "Ensuring /etc/ledmatrix/ exists..."
if [ "$EUID" -eq 0 ]; then
    mkdir -p /etc/ledmatrix
    chmod 755 /etc/ledmatrix
else
    sudo mkdir -p /etc/ledmatrix
    sudo chmod 755 /etc/ledmatrix
fi

# Create telegram.env stub if missing
if [ ! -f /etc/ledmatrix/telegram.env ]; then
    echo "Creating /etc/ledmatrix/telegram.env stub (EDIT THIS with your bot token + chat IDs)..."
    TELEGRAM_ENV_CONTENT='# LED Matrix Telegram bot credentials — keep this file readable only by root (chmod 600)
TELEGRAM_BOT_TOKEN="REPLACE_WITH_YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID="REPLACE_WITH_YOUR_CHAT_ID"
# Optional: separate chat (muted) for high-volume heartbeat noise.
# If unset, heartbeats post to TELEGRAM_CHAT_ID.
# TELEGRAM_HEARTBEAT_CHAT_ID=""
'
    if [ "$EUID" -eq 0 ]; then
        echo "$TELEGRAM_ENV_CONTENT" | tee /etc/ledmatrix/telegram.env > /dev/null
        chmod 600 /etc/ledmatrix/telegram.env
    else
        echo "$TELEGRAM_ENV_CONTENT" | sudo tee /etc/ledmatrix/telegram.env > /dev/null
        sudo chmod 600 /etc/ledmatrix/telegram.env
    fi
    echo "⚠  EDIT /etc/ledmatrix/telegram.env WITH YOUR BOT TOKEN + CHAT ID BEFORE THE TIMER FIRES."
else
    echo "✓ /etc/ledmatrix/telegram.env already exists; leaving in place."
fi

# Create systemd service + timer
echo ""
echo "Creating systemd service + timer files..."
SERVICE_FILE_CONTENT=$(cat <<EOF
[Unit]
Description=LED Matrix Telegram heartbeat (10-min dead-man)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$PROJECT_ROOT_DIR
ExecStart=$HEARTBEAT_SCRIPT
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ledmatrix-heartbeat
EOF
)

TIMER_FILE_CONTENT=$(cat <<EOF
[Unit]
Description=Fire LED Matrix heartbeat every 10 minutes
Requires=ledmatrix-heartbeat.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF
)

if [ "$EUID" -eq 0 ]; then
    echo "$SERVICE_FILE_CONTENT" | tee /etc/systemd/system/ledmatrix-heartbeat.service > /dev/null
    echo "$TIMER_FILE_CONTENT" | tee /etc/systemd/system/ledmatrix-heartbeat.timer > /dev/null
else
    echo "$SERVICE_FILE_CONTENT" | sudo tee /etc/systemd/system/ledmatrix-heartbeat.service > /dev/null
    echo "$TIMER_FILE_CONTENT" | sudo tee /etc/systemd/system/ledmatrix-heartbeat.timer > /dev/null
fi

# Reload + enable
echo ""
echo "Reloading systemd + enabling heartbeat timer..."
if [ "$EUID" -eq 0 ]; then
    systemctl daemon-reload
    systemctl enable ledmatrix-heartbeat.timer
    systemctl start ledmatrix-heartbeat.timer || echo "⚠ Failed to start timer (will start on reboot)"
else
    sudo systemctl daemon-reload
    sudo systemctl enable ledmatrix-heartbeat.timer
    sudo systemctl start ledmatrix-heartbeat.timer || echo "⚠ Failed to start timer (will start on reboot)"
fi

# Status
echo ""
echo "Checking timer status..."
SYSTEMCTL_CMD=$([ "$EUID" -eq 0 ] && echo "systemctl" || echo "sudo systemctl")
if $SYSTEMCTL_CMD is-active --quiet ledmatrix-heartbeat.timer 2>/dev/null; then
    echo "✓ Heartbeat timer is active"
    $SYSTEMCTL_CMD list-timers ledmatrix-heartbeat.timer --no-pager || true
else
    echo "⚠ Heartbeat timer failed to start. Check: sudo journalctl -u ledmatrix-heartbeat.timer -n 50"
fi

echo ""
echo "Heartbeat Service installation complete!"
echo ""
echo "⚠ NEXT STEPS (one-time):"
echo "  1. Edit /etc/ledmatrix/telegram.env — fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
echo "  2. Manually fire one: sudo systemctl start ledmatrix-heartbeat.service ; sudo journalctl -u ledmatrix-heartbeat -n 20"
echo "  3. Set up the Render-side dead-man checker that alerts on >25 min of silence."
echo ""
echo "Useful commands:"
echo "  sudo systemctl list-timers ledmatrix-heartbeat.timer  # When does it fire next?"
echo "  sudo systemctl start ledmatrix-heartbeat.service      # Fire one now"
echo "  sudo journalctl -u ledmatrix-heartbeat -f             # Tail logs"
echo ""
