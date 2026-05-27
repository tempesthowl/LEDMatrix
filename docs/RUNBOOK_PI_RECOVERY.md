# Pi Recovery Runbook

The file you grab at 11pm when the panels go dark.

**Target: ≤15 min from "Pi is dead" to "Pi is back online" for scenarios A–C.** Scenario D (hardware fault) takes ~30 min unless a spare Pi is on hand.

---

## Before anything — what kind of dead?

Walk to the rooftop. Two LEDs to inspect on the Pi itself:

| Red PWR | Green ACT | Diagnosis | Go to |
|---|---|---|---|
| OFF | OFF | No power reaching the Pi | Scenario A |
| ON solid | OFF or briefly flashing then dark | Power OK, boot failed | Scenario B (then C) |
| ON solid | Flashing steadily | OS is alive, network/service is dead | Scenario A (SSH path) |
| Blinking | — | Undervoltage warning | Scenario A (check PSU/cable) |

Also check: are the LED panels (matrix) dark, or is the **emulator screen frozen on last content**? Frozen content = Pi was alive but the display loop hung. Fully dark panels = Pi or ALITOVE PSU is down.

---

## Scenario A — Pi offline, no Telegram alert / can't SSH

### Diagnose (2 min)

1. **From desktop:** `tailscale status | findstr ledticker` — is the tailnet node showing `active` or `offline, last seen Xm ago`?
2. **If active:** try SSH: `ssh vallejofish@ledticker-1` and `ssh ledpi@ledticker.local`. If both fail, network is up but sshd is hung.
3. **If offline:** walk to roof. Check:
   - Pi USB-C cable seated at both ends?
   - ALITOVE PSU LED on (matrix has power)?
   - Pi LEDs (red + green) — see table above
   - UPS HAT battery LED (if installed) — is it on AC or on battery?

### Fix (≤13 min)

| Symptom | Action |
|---|---|
| Pi LED off + CyberPower UPS on battery (front LCD shows "On Battery") | AC has been lost. The UPS should have kept the Pi alive — if Pi is off, the UPS battery ran out. Restore AC, UPS auto-recharges, Pi auto-boots when wall outlet has power. |
| Pi LED off + UPS on AC | Pi PSU may be unplugged from the UPS battery-backup outlets. Confirm Pi USB-C PSU is in a BATTERY-BACKUP outlet (not surge-only). |
| Pi LED on, no SSH, no Tailscale | `sudo shutdown -r now` over LAN if SSH partial works. Otherwise press + hold the CyberPower UPS power button to cycle the outlet (cleaner than yanking USB-C). **Last resort only:** yank USB-C, wait 10s, replug. ⚠ This is the corruption-causing op we're trying to eliminate. |
| Pi LED on, SSH works, ledmatrix down | `ssh vallejofish@ledticker-1 'sudo systemctl restart ledmatrix.service'`. If that fails, `sudo journalctl -u ledmatrix -n 100` to see why. |
| Undervoltage blink | Check USB-C cable quality. Replace PSU. Houston heat can stress old PSU caps — if PSU is >2 years, replace as preventive maintenance. |

If after 13 min the Pi still won't ping → escalate to **Scenario B** (treat as boot failure).

---

## Scenario B — Pi powers on but doesn't boot (no steady green ACT)

### Diagnose (2 min)

1. Plug HDMI into Pi (the micro-HDMI port; keep an adapter in the garage). Connect to any monitor or a small portable USB-C display.
2. Power-cycle. Watch boot output.

**Look for:**
- `kernel panic` — root filesystem corrupted (→ Scenario C)
- `Cannot find bootable device` — SSD not detected (reseat USB-C connection on the SSD enclosure)
- `fsck: ... UNEXPECTED INCONSISTENCY` — filesystem corruption, fsck may auto-repair (→ wait, then retry)
- Boot drops to an `(initramfs)` shell — initramfs failed (overlay-FS or driver issue → Scenario C)
- Endless `[FAILED]` lines for services — boot reached userspace but services crashing (SSH in once it stabilizes, fix specific service)

### Fix (≤13 min)

| HDMI shows | Action |
|---|---|
| `Cannot find bootable device` | Power off, reseat USB SSD enclosure cable, power on. If still missing → enclosure or SSD failure (→ Scenario C with restore to a fresh SSD). |
| `fsck UNEXPECTED INCONSISTENCY ... press RETURN` | Press Enter (or wait for non-interactive auto-recovery). If it loops or fails, go to Scenario C. |
| Kernel panic / drops to initramfs | Go directly to Scenario C — restore from backup. |
| Services failed but you got a login prompt | SSH in. `sudo journalctl -b -p err` shows the errors. Fix individually; do NOT make ad-hoc changes — write a fix in the repo's installer and `git pull && bash first_time_install.sh`. |
| No HDMI output at all (Pi is on, nothing on screen) | Hardware fault. → Scenario D. |

---

## Scenario C — SSD corruption / fsck won't recover

### Restore from the most recent full backup (12-15 min, target ≤15 min)

**Prep (on Windows desktop):**

1. Pull the USB SSD enclosure from the Pi.
2. Plug it into the desktop via USB 3.0.
3. Identify the disk number: `Get-Disk | Where-Object BusType -eq USB`. Note `Number` (probably 3 or higher).
4. Locate the most recent full backup:
   ```powershell
   Get-ChildItem D:\Pi-Backups\ledticker\full\ -Filter *.img.gz | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   ```

**Restore (one of two methods):**

**Option C1 — PowerShell + dd-for-windows (~12 min for 30GB image over USB 3.0):**
```powershell
# Replace N with the actual disk number from Get-Disk above
# WARNING: this OVERWRITES the SSD. Confirm the disk number twice.
& 'C:\Path\To\dd.exe' if=- of=\\.\PhysicalDriveN bs=4M --progress < (& 'C:\Program Files\7-Zip\7z.exe' x -so 'D:\Pi-Backups\ledticker\full\full-LATEST.img.gz')
```

**Option C2 — Win32DiskImager GUI (slower setup but more familiar):**
1. Decompress the .gz: `& 'C:\Program Files\7-Zip\7z.exe' x 'D:\Pi-Backups\ledticker\full\full-LATEST.img.gz' -o'D:\Pi-Backups\ledticker\restore\'`
2. Open Win32DiskImager, select the .img file, select the SSD's drive letter, click Write. Confirm overwrite.

**Boot test (3 min):**
1. Cleanly eject SSD from Windows.
2. Reinstall in Pi USB enclosure, plug into Pi USB 3.0 port (blue).
3. Power on Pi.
4. Watch for steady green ACT within 20s — boot in progress.
5. Wait 60s, try `ssh vallejofish@ledticker-1`.
6. Confirm `systemctl status ledmatrix` is active.
7. Walk to roof, confirm panels are glowing.

**If restored image won't boot:** the backup itself is corrupted (rare). Restore an older full image (`full-PREVIOUS.img.gz`) and re-apply incrementals manually from `D:\Pi-Backups\ledticker\incremental\`.

---

## Scenario D — Pi hardware fault (red LED dead, USB ports unresponsive)

### Diagnose (2 min)

1. Try a different USB-C cable.
2. Try a different PSU (must be ≥3A 5V).
3. If red LED still won't come on with known-good power → Pi 4 SoC, voltage regulator, or PMIC has died.

### Fix

**With a spare Pi 4 (BACKLOG: order one once 60 days clean):**
1. Move the USB SSD enclosure + UPS HAT + matrix cabling to the spare Pi.
2. Power on. ~3 min boot. Panels live.

**Without a spare Pi (current state — 30 min, exceeds 15-min target):**
1. Order a new Pi 4 (2-day delivery).
2. While waiting, the rooftop ticker is dark — there's no faster path.
3. When Pi arrives:
   - Move USB SSD enclosure + UPS HAT + cabling to new Pi.
   - Power on. EEPROM may need a fresh USB-boot flash — see `docs/RUNBOOK_PI_FRESH_INSTALL.md` (TODO: write this once first SSD install is complete).
   - Boot from existing SSD (~3 min). Panels live.

---

## After every recovery — verify before declaring done

1. `ssh vallejofish@ledticker-1` succeeds.
2. `systemctl status ledmatrix ledmatrix-web ledmatrix-wifi-monitor ledmatrix-ups-monitor ledmatrix-heartbeat.timer ledmatrix-backup.timer` — all green.
3. Walk to roof: panels are showing live ticker content.
4. Wait 15 min — receive Telegram heartbeat OK confirming Pi-side alerting is live.
5. Tail `journalctl -b -p err` — no new errors since boot.

**Only after all 5: announce "Pi is back" in the loud Telegram channel.**

---

## What you do NOT do during recovery

- **Don't SSH in and "fix" things ad-hoc.** Every fix goes into the repo's installer or this runbook gets updated. Read [docs/OPERATIONAL_DISCIPLINE.md](OPERATIONAL_DISCIPLINE.md).
- **Don't yank power as a first move.** That's what got us here. Use the UPS HAT shutdown button or `sudo shutdown -h now`.
- **Don't reinstall the overlay-FS.** It's the original sin. SSD + UPS eliminates the failure mode it was trying to prevent.
- **Don't trust "looks like it's working."** Run all 5 verification checks before walking away.

---

## Time budget reality check

If a recovery is taking >15 min in scenarios A–C, **stop and write down what's blocking you.** The runbook is wrong if it can't deliver the SLA. Update the runbook before the next failure.
