#!/bin/bash

# Backup Service Installation Script
# Installs the nightly backup systemd timer.
# Pattern mirrors install_wifi_monitor.sh.

set -e

if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
else
    ACTUAL_USER=$(whoami)
fi

USER_HOME=$(eval echo ~$ACTUAL_USER)
PROJECT_ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
BACKUP_SCRIPT="$PROJECT_ROOT_DIR/scripts/backup/snapshot_to_desktop.sh"

echo "Installing LED Matrix Backup Service for user: $ACTUAL_USER"
echo "Project root directory: $PROJECT_ROOT_DIR"

if [ ! -f "$BACKUP_SCRIPT" ]; then
    echo "✗ Backup script not found at: $BACKUP_SCRIPT"
    exit 1
fi

# Make sure the backup script is executable
chmod 755 "$BACKUP_SCRIPT"

# Required packages: rsync, openssh-client, gzip (gzip is base, but check)
echo ""
echo "Checking for required packages..."
MISSING_PACKAGES=()

if ! command -v rsync >/dev/null 2>&1; then
    MISSING_PACKAGES+=("rsync")
fi
if ! command -v ssh >/dev/null 2>&1; then
    MISSING_PACKAGES+=("openssh-client")
fi

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo "Installing required packages: ${MISSING_PACKAGES[*]}"
    if [ "$EUID" -eq 0 ]; then
        apt update || true
        apt install -y "${MISSING_PACKAGES[@]}"
    else
        sudo apt update || true
        sudo apt install -y "${MISSING_PACKAGES[@]}"
    fi
fi

# Create /etc/ledmatrix dir for env files (telegram.env shared with heartbeat + ups)
echo ""
echo "Ensuring /etc/ledmatrix/ exists..."
if [ "$EUID" -eq 0 ]; then
    mkdir -p /etc/ledmatrix
    chmod 755 /etc/ledmatrix
else
    sudo mkdir -p /etc/ledmatrix
    sudo chmod 755 /etc/ledmatrix
fi

# Drop a default backup.env stub if missing (Eric edits paths to match his desktop)
if [ ! -f /etc/ledmatrix/backup.env ]; then
    echo "Creating /etc/ledmatrix/backup.env stub (EDIT THIS to match your desktop)..."
    BACKUP_ENV_CONTENT='# LED Matrix backup configuration — edit to match your desktop
BACKUP_HOST="desktop.tailnet"        # Tailscale MagicDNS name OR IP of Eric'"'"'s desktop
BACKUP_USER="eric"                   # SSH user on the desktop
BACKUP_BASE="/mnt/d/Pi-Backups/ledticker"   # WSL path (Win D:\\Pi-Backups\\ledticker)
BOOT_DISK="/dev/sda"                 # USB SSD — confirm with `lsblk` first run
MIN_FULL_BYTES="104857600"           # 100 MB minimum for a full image
MIN_INCR_BYTES="10240"               # 10 KB minimum for an incremental
'
    if [ "$EUID" -eq 0 ]; then
        echo "$BACKUP_ENV_CONTENT" | tee /etc/ledmatrix/backup.env > /dev/null
        chmod 644 /etc/ledmatrix/backup.env
    else
        echo "$BACKUP_ENV_CONTENT" | sudo tee /etc/ledmatrix/backup.env > /dev/null
        sudo chmod 644 /etc/ledmatrix/backup.env
    fi
    echo "⚠  EDIT /etc/ledmatrix/backup.env BEFORE FIRST BACKUP RUN."
fi

# Create systemd service + timer
echo ""
echo "Creating systemd service + timer files..."
SERVICE_FILE_CONTENT=$(cat <<EOF
[Unit]
Description=LED Matrix Pi backup → desktop
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$PROJECT_ROOT_DIR
ExecStart=$BACKUP_SCRIPT
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ledmatrix-backup
EOF
)

TIMER_FILE_CONTENT=$(cat <<EOF
[Unit]
Description=Run LED Matrix Pi backup daily at 03:00
Requires=ledmatrix-backup.service

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF
)

if [ "$EUID" -eq 0 ]; then
    echo "$SERVICE_FILE_CONTENT" | tee /etc/systemd/system/ledmatrix-backup.service > /dev/null
    echo "$TIMER_FILE_CONTENT" | tee /etc/systemd/system/ledmatrix-backup.timer > /dev/null
else
    echo "$SERVICE_FILE_CONTENT" | sudo tee /etc/systemd/system/ledmatrix-backup.service > /dev/null
    echo "$TIMER_FILE_CONTENT" | sudo tee /etc/systemd/system/ledmatrix-backup.timer > /dev/null
fi

# Reload + enable timer (NOT the service — only the timer is recurring)
echo ""
echo "Reloading systemd + enabling backup timer..."
if [ "$EUID" -eq 0 ]; then
    systemctl daemon-reload
    systemctl enable ledmatrix-backup.timer
    systemctl start ledmatrix-backup.timer || echo "⚠ Failed to start timer (will start on reboot)"
else
    sudo systemctl daemon-reload
    sudo systemctl enable ledmatrix-backup.timer
    sudo systemctl start ledmatrix-backup.timer || echo "⚠ Failed to start timer (will start on reboot)"
fi

echo ""
echo "Checking timer status..."
SYSTEMCTL_CMD=$([ "$EUID" -eq 0 ] && echo "systemctl" || echo "sudo systemctl")
if $SYSTEMCTL_CMD is-active --quiet ledmatrix-backup.timer 2>/dev/null; then
    echo "✓ Backup timer is active"
    $SYSTEMCTL_CMD list-timers ledmatrix-backup.timer --no-pager || true
else
    echo "⚠ Backup timer failed to start. Check: sudo journalctl -u ledmatrix-backup.timer -n 50"
fi

echo ""
echo "Backup Service installation complete!"
echo ""
echo "⚠ NEXT STEPS (one-time):"
echo "  1. Edit /etc/ledmatrix/backup.env to match your desktop's Tailscale hostname + user + path."
echo "  2. SSH key auth from THIS PI to your desktop: ssh-keygen -t ed25519 ; ssh-copy-id eric@desktop.tailnet"
echo "  3. Manually test once: sudo systemctl start ledmatrix-backup.service ; sudo journalctl -u ledmatrix-backup -f"
echo ""
echo "Useful commands:"
echo "  sudo systemctl list-timers ledmatrix-backup.timer    # When does it run next?"
echo "  sudo systemctl start ledmatrix-backup.service        # Run a backup NOW"
echo "  sudo journalctl -u ledmatrix-backup -n 100           # See last run log"
echo ""
