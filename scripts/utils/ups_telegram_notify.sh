#!/bin/bash
#
# NUT NOTIFYCMD hook — fires on UPS state changes (ONBATT, LOWBATT, SHUTDOWN, etc.)
# Called by upsmon. Posts a Telegram alert.
#
# NUT passes the notification message as $1 and sets NOTIFYTYPE env var.
# See upsmon.conf NOTIFYMSG entries for what messages look like.

set -u

TELEGRAM_ENV="/etc/ledmatrix/telegram.env"
LOG_TAG="ledmatrix-ups-notify"

logger -t "$LOG_TAG" "NUT event: NOTIFYTYPE=${NOTIFYTYPE:-?} UPSNAME=${UPSNAME:-?} msg=${1:-}"

if [ ! -f "$TELEGRAM_ENV" ]; then
    logger -t "$LOG_TAG" "telegram.env missing; alert suppressed"
    exit 0
fi

# shellcheck source=/dev/null
source "$TELEGRAM_ENV"

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    logger -t "$LOG_TAG" "Telegram creds empty; alert suppressed"
    exit 0
fi

# Pick the right emoji + chat per event type for signal-to-noise
case "${NOTIFYTYPE:-}" in
    ONBATT)
        EMOJI="🔋"
        SEVERITY="ON BATTERY — AC lost"
        ;;
    LOWBATT)
        EMOJI="🚨"
        SEVERITY="LOW BATTERY — shutdown imminent"
        ;;
    SHUTDOWN)
        EMOJI="⛔"
        SEVERITY="SHUTDOWN initiated by UPS"
        ;;
    ONLINE)
        EMOJI="✅"
        SEVERITY="AC restored — back online"
        ;;
    REPLBATT)
        EMOJI="⚠️"
        SEVERITY="REPLACE BATTERY — UPS cell aged out"
        ;;
    NOCOMM)
        EMOJI="❌"
        SEVERITY="NO COMM — Pi can't reach UPS over USB"
        ;;
    *)
        EMOJI="ℹ️"
        SEVERITY="${NOTIFYTYPE:-event}"
        ;;
esac

MSG="${EMOJI} ledticker UPS: ${SEVERITY}
$(date -Iseconds)
${1:-(no message body)}"

curl -s -m 10 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${MSG}" \
    >/dev/null || logger -t "$LOG_TAG" "curl to Telegram failed"

exit 0
