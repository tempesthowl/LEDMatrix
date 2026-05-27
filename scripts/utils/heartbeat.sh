#!/bin/bash
#
# LED Matrix heartbeat — fires every 10 min via ledmatrix-heartbeat.timer.
# Posts a short OK message to Telegram. Silence = problem (dead-man pattern).
# A separate Render-side checker watches for missed heartbeats and fires a loud alert.

set -u

TELEGRAM_ENV="/etc/ledmatrix/telegram.env"

if [ ! -f "$TELEGRAM_ENV" ]; then
    echo "heartbeat: telegram env file missing at $TELEGRAM_ENV — skipping"
    exit 0
fi

# shellcheck source=/dev/null
source "$TELEGRAM_ENV"

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "heartbeat: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID empty — skipping"
    exit 0
fi

# Use heartbeat-specific chat if defined (quiet/muted channel)
CHAT_ID="${TELEGRAM_HEARTBEAT_CHAT_ID:-$TELEGRAM_CHAT_ID}"

STAMP=$(date -Iseconds)
TEMP=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 || echo "?")
LOAD=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo "?")
UPTIME=$(uptime -p 2>/dev/null || echo "?")

# Service health one-liner
SERVICES_OK=true
for svc in ledmatrix ledmatrix-web ledmatrix-wifi-monitor; do
    if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
        SERVICES_OK=false
        break
    fi
done

if [ "$SERVICES_OK" = true ]; then
    STATUS="✓"
else
    STATUS="⚠ service degraded"
fi

MSG="ledticker ${STATUS}
${STAMP}
temp=${TEMP}
load=${LOAD}
${UPTIME}"

curl -s -m 10 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MSG}" \
    >/dev/null || {
        echo "heartbeat: curl failed"
        exit 1
    }

exit 0
