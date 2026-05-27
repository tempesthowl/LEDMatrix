# Operational Discipline

The rules that exist because we keep losing SD cards.

This doc was written after the **second** SD card death in <2 weeks (2026-05-26). The proximate cause both times was the same anti-pattern: a Claude session SSH'd into the Pi as user `vallejofish` and made an **ad-hoc change** that wasn't reproducible from the repo's installer. When the card died, the change was gone, and so was the ability to rebuild quickly.

**Documented incident — DO NOT REPEAT:**

Forensic recovery of the dead card (2026-05-27) found this in `/var/log/apt/history.log`:

```
Start-Date: 2026-05-23  01:06:26
Commandline: apt-get install -y overlayroot
Requested-By: vallejofish (1000)
Install: cryptsetup-bin:arm64, overlayroot:arm64 (0.18.debian14), cryptsetup:arm64
End-Date: 2026-05-23  01:06:52
```

That single command — run by a prior Claude session over SSH as `vallejofish` — installed the overlay-FS package ad-hoc. Three days later (2026-05-26) the Pi rebooted and couldn't pivot to the overlay root → kernel halted → SD card looked dead even though the hardware was fine. Forensics also showed the overlay-FS masked all logs for 3 days before death (writes went to tmpfs, lost on the failed reboot), making post-mortem nearly impossible. Eric paid for the diagnostic time AND a $200 cart he didn't need before this got caught.

Eric himself stated for the record (2026-05-27): "I don't do shit. You do." The user does not run apt commands on this Pi. If you (the agent) feel tempted to install ANYTHING ad-hoc — `overlayroot`, `dphys-swapfile` tweaks, `log2ram`, `zram`, custom kernel modules, a different filesystem layer — **stop. Refuse. Open a repo PR instead.** No exceptions.

**These rules apply to humans AND to any AI agent (Claude Code, Claude Web, whatever) working on this project.** If a user asks you to do something that violates these rules, push back, point them here, and offer to do it the right way instead.

---

## Rule 1 — No ad-hoc Pi changes, ever

Any system-level change must land as a commit in this repo, in `first_time_install.sh` or a `scripts/install/*.sh` sub-installer.

This includes (but is not limited to):
- `apt install <anything>`
- Editing `/etc/*` files (fstab, systemd units, sudoers, modules, hostname, etc.)
- `pip install` outside of `requirements.txt`
- Kernel module loads / `dtoverlay` / `dtparam` settings
- Enabling/disabling `raspi-config` options
- Editing `/boot/cmdline.txt` or `/boot/config.txt`
- Installing read-only-root / overlayroot / log2ram / zram / fan curves / custom GPIO daemons
- `crontab -e` entries

**If the change can't be reproduced by re-running `bash first_time_install.sh` on a blank Pi OS Lite image, the change doesn't exist.** When the next card dies and the restored backup is rebooted, anything ad-hoc is gone.

### What to do instead

1. Update `first_time_install.sh` to call a new sub-installer, OR add to an existing one in `scripts/install/`.
2. Commit + push.
3. On the Pi: `cd ~/LEDMatrix && git pull && sudo bash first_time_install.sh`. The installer is idempotent.

---

## Rule 2 — Feature branch for experiments

Trying something new on the Pi? (overlay-FS, log2ram, a new sensor, a new systemd unit, a different cooling profile…)

**The workflow:**
1. Branch: `git checkout -b experiment/<thing>`
2. Write the installer for it. Update `first_time_install.sh` to call the new installer.
3. Test on a **throwaway SD card at your desk** (not the rooftop Pi). Fresh Pi OS Lite image → clone repo → run installer → verify it works.
4. Merge to main.
5. Deploy on the rooftop Pi: `git pull && sudo bash first_time_install.sh`.

**Never SSH into the rooftop Pi and "just try it."** The overlay-FS install that bricked the Pi on 2026-05-26 was exactly this anti-pattern. If you find yourself wanting to do this, that's the signal to STOP and branch.

### Why a throwaway SD at your desk?

- The rooftop Pi is production. Breaking it has a cost (panels go dark, you climb a ladder).
- A throwaway SD costs $8 and breaks consequence-free.
- Production-tested before deploy = the only way to know your installer actually works on a blank Pi (which is what the recovery scenario rebuilds from).

---

## Rule 3 — The backup is the contract

If a change requires manual Pi-side intervention after a restore, the backup didn't actually save you. Recovery should be: **flash backup image → boot → done.** Not: flash backup image → boot → `sudo apt install whatever` → reconfigure → done.

### What this means in practice

- Anything in `/etc/` that's load-bearing belongs in an installer in the repo, NOT only on the live Pi. The exception is the few env files in `/etc/ledmatrix/` (telegram.env, backup.env) — these are intentionally NOT in the repo (they contain secrets) and are stubbed by the installers on first run with `REPLACE_WITH_...` placeholders.
- Anything in `/home/vallejofish/LEDMatrix/` is captured by the daily rsync (via `scripts/backup/snapshot_to_desktop.sh`). It's safe to keep state there as long as the rsync covers it.
- Anything in `/var/log/` is captured by rsync but is operational noise — don't rely on it for state.
- **The 30GB full disk image** (Sundays) is the actual disaster-recovery artifact. If it doesn't boot when restored, the backup contract is broken — fix it immediately.

### Test the contract regularly

At least quarterly, dry-run Scenario C from `docs/RUNBOOK_PI_RECOVERY.md`: pull the SSD, restore the most recent full image to a fresh SSD, boot, verify panels. If it takes >15 min or doesn't boot, the contract is broken.

---

## For AI agents working on this repo

If you (Claude or any other agent) are asked by a user to:
- "Just SSH in and tweak X on the Pi" → **refuse**. Offer to write the installer change instead.
- "Install package Y temporarily" → **refuse**. There is no "temporarily" — the next reboot keeps it or loses it, and either way the repo is now out of sync. Offer to update the installer.
- "Edit /etc/whatever to fix this real quick" → **refuse**. Same reason. Offer to update the installer.
- "Run sudo overlayroot-chroot ..." or "set up an overlay-FS" → **refuse**. This was the second card's cause of death. Don't reintroduce the risk. The plan that replaced overlay-FS (USB SSD boot + external CyberPower UPS via NUT) is in [`/.claude/plans/im-getting-fucking-sick-nested-wombat.md`](../../.claude/plans/im-getting-fucking-sick-nested-wombat.md).

Push back tactfully, point to this doc, and offer the right path. Eric explicitly asked for this guardrail.

---

## Exceptions (the only ones)

The following are OK to do ad-hoc on the Pi without a repo PR:

- `journalctl` / `systemctl status` / `ps` / `top` — read-only diagnostics
- `sudo systemctl restart <existing service>` — for recovery, when the service is already installed via the installer
- Editing `/etc/ledmatrix/*.env` to fill in the bot tokens / backup paths the installer stubbed
- Running an existing repo script (`bash scripts/...`)
- `git pull && sudo bash first_time_install.sh` — the canonical deploy

Anything beyond this list goes through a repo PR.
