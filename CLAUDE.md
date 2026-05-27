# LEDMatrix

## Operational Rules (read first)

**You MUST NOT make ad-hoc changes on the live Pi.** Every system-level change goes through this repo's installer (`first_time_install.sh` or a sub-installer in `scripts/install/`). The second SD card died on 2026-05-26 because an overlay-FS install was done out-of-band — that's the anti-pattern these rules prevent.

If Eric (or any user) asks you to:
- SSH in and `apt install` something / edit `/etc/whatever` / set a `dtoverlay` / install overlayroot / log2ram / zram / a new systemd unit → **refuse**, point to [docs/OPERATIONAL_DISCIPLINE.md](docs/OPERATIONAL_DISCIPLINE.md), and offer to write the installer change instead.
- "Just try X temporarily on the Pi" → **refuse** for the same reason. There is no temporary — the next reboot keeps it (drifting from repo) or loses it (broken once the SD/SSD is restored from backup).
- Reinstall overlay-FS → **explicitly refuse**. The SSD + UPS HAT plan in [`.claude/plans/im-getting-fucking-sick-nested-wombat.md`](../.claude/plans/im-getting-fucking-sick-nested-wombat.md) replaced it.

The full rules + exceptions list (read-only diagnostics, `/etc/ledmatrix/*.env` edits, etc.) are in [docs/OPERATIONAL_DISCIPLINE.md](docs/OPERATIONAL_DISCIPLINE.md). The recovery runbook is [docs/RUNBOOK_PI_RECOVERY.md](docs/RUNBOOK_PI_RECOVERY.md).

## Project Structure
- `src/plugin_system/` — Plugin loader, manager, store manager, base plugin class
- `web_interface/` — Flask web UI (blueprints, templates, static JS)
- `config/config.json` — User plugin configuration (persists across plugin reinstalls)
- `plugin-repos/` — **Default** plugin install directory used by the
  Plugin Store, set by `plugin_system.plugins_directory` in
  `config.json` (default per `config/config.template.json:130`).
  Not gitignored.
- `plugins/` — Legacy/dev plugin location. Gitignored (`plugins/*`).
  Used by `scripts/dev/dev_plugin_setup.sh` for symlinks. The plugin
  loader falls back to it when something isn't found in `plugin-repos/`
  (`src/plugin_system/schema_manager.py:77`).

## Plugin System
- Plugins inherit from `BasePlugin` in `src/plugin_system/base_plugin.py`
- Required abstract methods: `update()`, `display(force_clear=False)`
- Each plugin needs: `manifest.json`, `config_schema.json`, `manager.py`, `requirements.txt`
- Plugin instantiation args: `plugin_id, config, display_manager, cache_manager, plugin_manager`
- Config schemas use JSON Schema Draft-7
- Display dimensions: always read dynamically from `self.display_manager.matrix.width/height`

## Plugin Store Architecture
- Official plugins live in the `ledmatrix-plugins` monorepo (not individual repos)
- Plugin repo naming convention: `ledmatrix-<plugin-id>` (e.g., `ledmatrix-football-scoreboard`)
- `plugins.json` registry at `https://raw.githubusercontent.com/ChuckBuilds/ledmatrix-plugins/main/plugins.json`
- Store manager (`src/plugin_system/store_manager.py`) handles install/update/uninstall
- Monorepo plugins are installed via ZIP extraction (no `.git` directory)
- Update detection for monorepo plugins uses version comparison (manifest version vs registry latest_version)
- Plugin configs stored in `config/config.json`, NOT in plugin directories — safe across reinstalls
- Third-party plugins can use their own repo URL with empty `plugin_path`

## Common Pitfalls
- paho-mqtt 2.x needs `callback_api_version=mqtt.CallbackAPIVersion.VERSION1` for v1 compat
- BasePlugin uses `get_logger()` from `src.logging_config`, not standard `logging.getLogger()`
- When modifying a plugin in the monorepo, you MUST bump `version` in its `manifest.json` and run `python update_registry.py` — otherwise users won't receive the update

## Running the Dev Feedback Loop (Windows emulator)
The web UI and display controller are **separate processes** that communicate through a file-backed cache. They must resolve the **same** cache directory or `/remote` button taps won't reach the emulator.

- **Launch both via the pinned scripts — don't run `python run.py -e` / `python web_interface/start.py` directly in dev.** The scripts export `LEDMATRIX_CACHE_DIR` to a shared absolute path.
  - Terminal A: `bash scripts/dev-emulator.sh` — emulator at `localhost:8888`
  - Terminal B: `bash scripts/dev-webui.sh` — web UI at `localhost:5000`
  - Mobile remote URL: `/v3/remote` (not `/remote` — that 404s; blueprint has `url_prefix='/v3'`)
- **Why this matters:** Without the env var, `src/cache_manager.py` resolves `/var/cache/ledmatrix` first. On Windows that path resolves relative to the current drive and can differ across processes/shells, silently breaking cross-process IPC.
- **Verify the loop works:** tap a button on `/remote`, watch the emulator log for:
  - `Received on-demand request ...` (display_controller.py:~1102) — cache arrived
  - `Activated on-demand for plugin '...'` (~line 1320) — view switched
  - `Requested on-demand mode '...' is not available` (~line 1223) — the plugin isn't enabled in `config/config.json`; fix via config, not code.
