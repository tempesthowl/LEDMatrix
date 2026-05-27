#!/bin/bash

# UPS Monitor Service Installation Script — NUT-based for CyberPower CP685AVRG
# (or any USB-HID UPS supported by NUT's usbhid-ups driver).
#
# Pattern mirrors install_wifi_monitor.sh.
#
# Replaces the previous INA219/Waveshare-HAT approach. Architectural reason:
# Eric's Pi already has a SEENGREAT matrix adapter on the GPIO header — a UPS
# HAT can't stack on top. External USB-data UPS sidesteps the conflict entirely.
# See plan: ~/.claude/plans/im-getting-fucking-sick-nested-wombat.md

set -e

if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
else
    ACTUAL_USER=$(whoami)
fi

PROJECT_ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
NOTIFY_SCRIPT="$PROJECT_ROOT_DIR/scripts/utils/ups_telegram_notify.sh"
NOTIFY_INSTALL_PATH="/usr/local/bin/ledmatrix-ups-notify"

echo "Installing LED Matrix UPS Monitor Service (NUT) for user: $ACTUAL_USER"
echo "Project root directory: $PROJECT_ROOT_DIR"

# ---------------------------------------------------------------------------
# Step 1 — Install NUT packages
# ---------------------------------------------------------------------------
echo ""
echo "Installing NUT packages (nut, nut-client, nut-server)..."
MISSING=()
for pkg in nut nut-client nut-server; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    if [ "$EUID" -eq 0 ]; then
        apt update || echo "⚠ apt update failed, continuing anyway..."
        apt install -y "${MISSING[@]}"
    else
        sudo apt update || echo "⚠ apt update failed, continuing anyway..."
        sudo apt install -y "${MISSING[@]}"
    fi
fi
echo "✓ NUT packages present"

# ---------------------------------------------------------------------------
# Step 2 — Detect UPS over USB
# ---------------------------------------------------------------------------
echo ""
echo "Probing for CyberPower UPS over USB..."
UPS_DETECTED=false
if command -v lsusb >/dev/null 2>&1; then
    # CyberPower vendor ID is 0764
    if lsusb 2>/dev/null | grep -qi '0764'; then
        UPS_DETECTED=true
        echo "✓ CyberPower UPS detected on USB (VID 0764)"
        lsusb | grep -i '0764' || true
    else
        echo "⚠ No CyberPower UPS detected on USB. The service will install but"
        echo "  won't function until the UPS data cable is connected. Run lsusb"
        echo "  after plugging in to verify VID 0764 appears."
    fi
fi

# ---------------------------------------------------------------------------
# Step 3 — Write NUT configs (idempotent — overwrite each install)
# ---------------------------------------------------------------------------
echo ""
echo "Writing NUT configuration files..."

# Generate a random password for upsmon if not already set (NUT internal, never leaves the Pi)
UPSMON_PASS_FILE="/etc/ledmatrix/upsmon.password"
if [ "$EUID" -eq 0 ]; then
    mkdir -p /etc/ledmatrix
    if [ ! -f "$UPSMON_PASS_FILE" ]; then
        head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24 > "$UPSMON_PASS_FILE"
        chmod 600 "$UPSMON_PASS_FILE"
    fi
    UPSMON_PASS=$(cat "$UPSMON_PASS_FILE")
else
    sudo mkdir -p /etc/ledmatrix
    if ! sudo test -f "$UPSMON_PASS_FILE"; then
        head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24 | sudo tee "$UPSMON_PASS_FILE" > /dev/null
        sudo chmod 600 "$UPSMON_PASS_FILE"
    fi
    UPSMON_PASS=$(sudo cat "$UPSMON_PASS_FILE")
fi

# /etc/nut/nut.conf — standalone mode (single Pi, single UPS)
NUT_CONF='MODE=standalone'

# /etc/nut/ups.conf — driver definition for CyberPower over USB-HID
UPS_CONF='[cyberpower]
    driver = usbhid-ups
    port = auto
    desc = "CyberPower CP685AVRG"
    pollinterval = 5'

# /etc/nut/upsd.conf — server bind to localhost only
UPSD_CONF='LISTEN 127.0.0.1 3493'

# /etc/nut/upsd.users — credentials (password from /etc/ledmatrix/upsmon.password)
UPSD_USERS="[monuser]
    password = ${UPSMON_PASS}
    upsmon master"

# /etc/nut/upsmon.conf — monitor + shutdown rules + Telegram NOTIFYCMD
UPSMON_CONF="MONITOR cyberpower@localhost 1 monuser ${UPSMON_PASS} master
MINSUPPLIES 1
SHUTDOWNCMD \"/sbin/shutdown -h +0 'UPS battery critical'\"
POWERDOWNFLAG /etc/killpower
NOTIFYCMD ${NOTIFY_INSTALL_PATH}
NOTIFYFLAG ONLINE   SYSLOG+EXEC
NOTIFYFLAG ONBATT   SYSLOG+WALL+EXEC
NOTIFYFLAG LOWBATT  SYSLOG+WALL+EXEC
NOTIFYFLAG SHUTDOWN SYSLOG+WALL+EXEC
NOTIFYFLAG REPLBATT SYSLOG+WALL+EXEC
NOTIFYFLAG NOCOMM   SYSLOG+WALL+EXEC
NOTIFYFLAG NOPARENT SYSLOG+EXEC
RBWARNTIME 43200
NOCOMMWARNTIME 300
FINALDELAY 5
POLLFREQ 5
POLLFREQALERT 5
HOSTSYNC 15
DEADTIME 15"

write_nut_file() {
    local path="$1"
    local content="$2"
    local mode="$3"
    if [ "$EUID" -eq 0 ]; then
        echo "$content" > "$path"
        chmod "$mode" "$path"
        chown root:nut "$path" 2>/dev/null || true
    else
        echo "$content" | sudo tee "$path" > /dev/null
        sudo chmod "$mode" "$path"
        sudo chown root:nut "$path" 2>/dev/null || true
    fi
}

write_nut_file /etc/nut/nut.conf       "$NUT_CONF"       644
write_nut_file /etc/nut/ups.conf       "$UPS_CONF"       640
write_nut_file /etc/nut/upsd.conf      "$UPSD_CONF"      640
write_nut_file /etc/nut/upsd.users     "$UPSD_USERS"     640
write_nut_file /etc/nut/upsmon.conf    "$UPSMON_CONF"    640

echo "✓ NUT config files written"

# ---------------------------------------------------------------------------
# Step 4 — Install Telegram notify hook
# ---------------------------------------------------------------------------
echo ""
echo "Installing Telegram notify hook..."
if [ ! -f "$NOTIFY_SCRIPT" ]; then
    echo "✗ Notify script not found at $NOTIFY_SCRIPT — install incomplete"
    exit 1
fi

if [ "$EUID" -eq 0 ]; then
    cp "$NOTIFY_SCRIPT" "$NOTIFY_INSTALL_PATH"
    chmod 755 "$NOTIFY_INSTALL_PATH"
    chown root:root "$NOTIFY_INSTALL_PATH"
else
    sudo cp "$NOTIFY_SCRIPT" "$NOTIFY_INSTALL_PATH"
    sudo chmod 755 "$NOTIFY_INSTALL_PATH"
    sudo chown root:root "$NOTIFY_INSTALL_PATH"
fi
echo "✓ Notify hook installed at $NOTIFY_INSTALL_PATH"

# ---------------------------------------------------------------------------
# Step 5 — Enable + start NUT services
# ---------------------------------------------------------------------------
echo ""
echo "Enabling + starting NUT services..."
if [ "$EUID" -eq 0 ]; then
    systemctl daemon-reload
    systemctl enable --now nut-server.service || echo "⚠ nut-server failed to start (UPS may not be connected yet)"
    systemctl enable --now nut-monitor.service || echo "⚠ nut-monitor failed to start"
else
    sudo systemctl daemon-reload
    sudo systemctl enable --now nut-server.service || echo "⚠ nut-server failed to start (UPS may not be connected yet)"
    sudo systemctl enable --now nut-monitor.service || echo "⚠ nut-monitor failed to start"
fi

# ---------------------------------------------------------------------------
# Step 6 — Verify
# ---------------------------------------------------------------------------
echo ""
echo "Checking service status..."
SYSTEMCTL_CMD=$([ "$EUID" -eq 0 ] && echo "systemctl" || echo "sudo systemctl")
if $SYSTEMCTL_CMD is-active --quiet nut-server.service 2>/dev/null; then
    echo "✓ nut-server is running"
else
    echo "⚠ nut-server not running — check: sudo journalctl -u nut-server -n 50"
fi
if $SYSTEMCTL_CMD is-active --quiet nut-monitor.service 2>/dev/null; then
    echo "✓ nut-monitor is running"
else
    echo "⚠ nut-monitor not running — check: sudo journalctl -u nut-monitor -n 50"
fi

# Try to talk to the UPS (will fail gracefully if not connected)
if command -v upsc >/dev/null 2>&1; then
    echo ""
    echo "Querying UPS state (will show 'No such ups' if cable not connected yet)..."
    upsc cyberpower@localhost 2>&1 | head -20 || true
fi

echo ""
echo "UPS Monitor (NUT) installation complete!"
echo ""
echo "Useful commands:"
echo "  upsc cyberpower@localhost              # Show UPS state (battery %, runtime, load)"
echo "  sudo systemctl status nut-server       # NUT driver/server status"
echo "  sudo systemctl status nut-monitor      # NUT shutdown-monitor status"
echo "  sudo journalctl -u nut-monitor -f      # Tail monitor log (sees ONBATT/LOWBATT/etc)"
echo "  sudo upsmon -c reload                  # Reload upsmon config without restart"
echo ""
echo "Manual test (with UPS plugged in):"
echo "  1. upsc cyberpower@localhost           # Should show battery.charge, ups.status=OL"
echo "  2. Unplug the UPS from the wall        # Should see ONBATT log + Telegram alert"
echo "  3. Plug it back in                     # Should see ONLINE log + Telegram alert"
echo ""
echo "⚠ NEXT STEPS (one-time):"
echo "  1. Plug the UPS USB cable into the Pi."
echo "  2. Plug the Pi's USB-C PSU into one of the UPS BATTERY-BACKUP outlets (not surge-only)."
echo "  3. Edit /etc/ledmatrix/telegram.env if you haven't already (install_heartbeat.sh stubs it)."
echo "  4. sudo systemctl restart nut-server nut-monitor"
echo "  5. Verify upsc shows live battery data."
echo ""
