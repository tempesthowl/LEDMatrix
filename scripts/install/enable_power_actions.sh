#!/bin/bash

# Enable the /v3/remote Power section (Reboot + Shutdown buttons).
#
# Sets LEDMATRIX_POWER_ACTIONS=true on the ledmatrix-web.service via a
# systemd drop-in (does NOT touch the unit file directly, so this is
# safe to re-run and easy to revert). After this runs, /v3/remote will
# render the Power section and POST /api/v3/system/action will accept
# reboot_system / shutdown_system requests.
#
# Prereqs:
#   - ledmatrix-web.service already installed (scripts/install/install_web_service.sh)
#   - sudoers grant for reboot/poweroff already in place
#     (scripts/install/configure_web_sudo.sh — typically done at first-install time)
#
# Usage:
#   sudo bash scripts/install/enable_power_actions.sh
#
# To disable later:
#   sudo rm /etc/systemd/system/ledmatrix-web.service.d/power-actions.conf
#   sudo systemctl daemon-reload && sudo systemctl restart ledmatrix-web

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: must run with sudo (writes to /etc/systemd)."
    echo "Try: sudo bash scripts/install/enable_power_actions.sh"
    exit 1
fi

SERVICE_NAME="ledmatrix-web.service"
DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.d"
DROPIN_FILE="${DROPIN_DIR}/power-actions.conf"

# Sanity check: the service must already exist.
if ! systemctl list-unit-files "$SERVICE_NAME" --no-legend | grep -q .; then
    echo "Error: $SERVICE_NAME not installed."
    echo "Run scripts/install/install_web_service.sh first."
    exit 1
fi

# Soft sanity check on sudoers — warn but don't refuse.
if ! sudo -u "$(stat -c %U /etc/sudoers.d/ledmatrix_web 2>/dev/null || echo nobody)" \
        sudo -n /usr/sbin/reboot --help > /dev/null 2>&1; then
    if [ ! -f /etc/sudoers.d/ledmatrix_web ]; then
        echo "WARNING: /etc/sudoers.d/ledmatrix_web not found."
        echo "         Run scripts/install/configure_web_sudo.sh first or"
        echo "         the Reboot/Shutdown buttons will 403/fail at exec time."
        echo ""
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 0
        fi
    fi
fi

echo "Creating drop-in directory: $DROPIN_DIR"
mkdir -p "$DROPIN_DIR"

echo "Writing $DROPIN_FILE"
cat > "$DROPIN_FILE" <<'EOF'
# LED Matrix — enable /v3/remote Reboot/Shutdown buttons.
# Read by web_interface/blueprints/pages_v3.py (template gate) and
# web_interface/blueprints/api_v3.py (POST /api/v3/system/action gate).
[Service]
Environment=LEDMATRIX_POWER_ACTIONS=true
EOF

echo "Reloading systemd..."
systemctl daemon-reload

echo "Restarting $SERVICE_NAME..."
systemctl restart "$SERVICE_NAME"

# Give the service ~3 seconds to actually come up.
sleep 3

echo ""
echo "Verifying environment..."
if systemctl show "$SERVICE_NAME" -p Environment --value | grep -q 'LEDMATRIX_POWER_ACTIONS=true'; then
    echo "OK: LEDMATRIX_POWER_ACTIONS=true is set on $SERVICE_NAME"
else
    echo "FAIL: env var not visible to systemd. Check $DROPIN_FILE syntax."
    exit 1
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "OK: $SERVICE_NAME is active"
else
    echo "FAIL: $SERVICE_NAME is not active. Check 'systemctl status $SERVICE_NAME'."
    exit 1
fi

echo ""
echo "Done. Open http://ledticker.local:5000/v3/remote — Power section should now render."
echo "Tap a button once -> 5s red countdown. Tap again within 5s to fire."
