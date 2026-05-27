#!/bin/bash

# LED Matrix Pi Backup → Eric's Windows desktop
# Daily: rsync of config/code dirs.
# Sundays: full dd image of the boot disk.
# Validates non-zero result; on failure → Telegram alert.

set -u

PROJECT_ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)

# --- Configuration (override via /etc/ledmatrix/backup.env if present) ----
BACKUP_HOST="${BACKUP_HOST:-desktop.tailnet}"
BACKUP_USER="${BACKUP_USER:-eric}"
BACKUP_BASE="${BACKUP_BASE:-/mnt/d/Pi-Backups/ledticker}"
BOOT_DISK="${BOOT_DISK:-/dev/sda}"     # USB SSD (per the SSD-boot plan)
MIN_FULL_BYTES="${MIN_FULL_BYTES:-104857600}"   # 100 MB sanity floor
MIN_INCR_BYTES="${MIN_INCR_BYTES:-10240}"       # 10 KB sanity floor

if [ -f /etc/ledmatrix/backup.env ]; then
    # shellcheck source=/dev/null
    source /etc/ledmatrix/backup.env
fi

TELEGRAM_ENV="/etc/ledmatrix/telegram.env"

# --- Logging ---
log() { echo "[$(date -Iseconds)] $*"; }

alert() {
    local msg="$1"
    log "ALERT: $msg"
    if [ -f "$TELEGRAM_ENV" ]; then
        # shellcheck source=/dev/null
        source "$TELEGRAM_ENV"
        if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
            curl -s -m 10 -X POST \
                "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -d "chat_id=${TELEGRAM_CHAT_ID}" \
                -d "text=🚨 ledticker backup failed: ${msg}" >/dev/null || true
        fi
    fi
}

# --- SSH preflight ---
ssh_check() {
    if ! ssh -o BatchMode=yes -o ConnectTimeout=10 \
        "${BACKUP_USER}@${BACKUP_HOST}" 'echo ssh-ok' >/dev/null 2>&1; then
        alert "SSH to ${BACKUP_USER}@${BACKUP_HOST} failed"
        exit 2
    fi
    ssh "${BACKUP_USER}@${BACKUP_HOST}" "mkdir -p '${BACKUP_BASE}/full' '${BACKUP_BASE}/incremental'" || {
        alert "mkdir on backup host failed"
        exit 2
    }
}

# --- Full disk image (Sundays) ---
do_full() {
    local stamp dest remote_size
    stamp=$(date +%F)
    dest="${BACKUP_BASE}/full/full-${stamp}.img.gz"
    log "FULL backup → ${BACKUP_HOST}:${dest}"

    # Pause LED display during dd for filesystem consistency
    log "Stopping ledmatrix service for consistency"
    systemctl stop ledmatrix.service || log "⚠ ledmatrix service stop failed (continuing)"

    if ! dd if="${BOOT_DISK}" bs=4M status=progress 2>>/var/log/ledmatrix-backup.log \
        | gzip -1 \
        | ssh "${BACKUP_USER}@${BACKUP_HOST}" "cat > '${dest}'"; then
        systemctl start ledmatrix.service || true
        alert "dd|gzip|ssh pipeline returned non-zero for full backup"
        exit 3
    fi

    log "Restarting ledmatrix service"
    systemctl start ledmatrix.service || log "⚠ ledmatrix service start failed"

    remote_size=$(ssh "${BACKUP_USER}@${BACKUP_HOST}" "stat -c %s '${dest}' 2>/dev/null || echo 0")
    if [ "${remote_size:-0}" -lt "${MIN_FULL_BYTES}" ]; then
        alert "Full backup file size ${remote_size}B < ${MIN_FULL_BYTES}B minimum"
        exit 4
    fi

    log "Full backup OK — ${remote_size} bytes"
}

# --- Incremental rsync (Mon-Sat) ---
do_incremental() {
    local dest summary log_line
    dest="${BACKUP_BASE}/incremental"
    log "INCREMENTAL rsync → ${BACKUP_HOST}:${dest}"

    # rsync exits 0 on success; 24 on "some files vanished" which is benign.
    set +e
    rsync -aAXH --delete --stats \
        --exclude='/var/log/journal' \
        --exclude='/var/log/lastlog' \
        "${PROJECT_ROOT_DIR}" \
        /etc \
        /var/log \
        "${BACKUP_USER}@${BACKUP_HOST}:${dest}/" \
        > /tmp/ledmatrix-backup-rsync.log 2>&1
    local rc=$?
    set -e

    if [ "$rc" -ne 0 ] && [ "$rc" -ne 24 ]; then
        alert "rsync exit ${rc} during incremental backup"
        exit 5
    fi

    summary=$(grep -E 'Total transferred file size|Total file size' /tmp/ledmatrix-backup-rsync.log | head -2 || true)
    log "Incremental backup OK — ${summary//$'\n'/ | }"
}

# --- Main ---
mkdir -p /var/log
log "=== Backup run starting (host=${BACKUP_HOST} base=${BACKUP_BASE}) ==="
ssh_check

DOW=$(date +%u)   # 1=Mon, 7=Sun
if [ "$DOW" -eq 7 ]; then
    do_full
else
    do_incremental
fi

log "=== Backup run complete ==="
