# Absorb Custom Golf Plugin Into Fork Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. This is a structural/deploy task, not TDD — each step has exact commands + expected output. The local steps (Tasks 1–4, 7) are the agent's; the Pi steps (Task 5) are Eric's hands (sudo + Pi git); Task 6 is agent verification via the Pi web API.

**Goal:** Replace the stock off-the-shelf golf plugin on the Pi with Eric's custom Kalshi Game-Mode build by committing it into the fork as plain tracked files, so it deploys via normal `git pull` and survives future Pi rebuilds.

**Architecture:** `plugin-repos/pga-tour-leaderboard` is currently a bare gitlink (submodule with no `.gitmodules` entry) pointing at `60e84a6`; the working tree has Eric's custom `611f4ba` checked out, but that commit lives only on this laptop. On the Pi, the path is a fresh shallow clone of `sarjent/main` (`45640bd`, stock). We de-submodule the plugin locally (preserve its history in a bundle first), commit its files into `feature/soccer-worldcup-game-mode`, push, then transition the Pi from submodule → plain files and restart.

**Tech Stack:** git (submodule absorption), the LEDMatrix display controller + plugin system, Pi web API for verification.

**Root cause being fixed:** Eric's custom golf plugin (get_live_games surfacing + Kalshi top-N leaderboard + game_focus renderer) was never in his fork — it's a clone of `sarjent/ledmatrix-golf` with local-only commits. Every Pi rebuild clones sarjent's stock `main`, silently reverting to a plugin with no `get_live_games` (no Live-Games card) and none of the Kalshi view. The `display_controller` routing fix (`e960db81`) is already deployed and correct, but has nothing to route to until the real plugin is on the Pi.

---

### Task 1: Preserve the custom golf plugin history (safety bundle)

**Files:**
- Create: `C:\Users\ericv\OneDrive\golf-plugin-611f4ba.bundle` (OneDrive = cloud-synced backup)

- [ ] **Step 1: Bundle the submodule's full history before we delete its `.git`**

```bash
cd "C:/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix/plugin-repos/pga-tour-leaderboard"
git bundle create "C:/Users/ericv/OneDrive/golf-plugin-611f4ba.bundle" --all
```

- [ ] **Step 2: Verify the bundle is valid and contains 611f4ba**

```bash
git bundle verify "C:/Users/ericv/OneDrive/golf-plugin-611f4ba.bundle"
git bundle list-heads "C:/Users/ericv/OneDrive/golf-plugin-611f4ba.bundle" | grep -i 611f4ba || echo "MISSING 611f4ba"
```
Expected: "The bundle is okay" and a line showing `611f4ba ... refs/heads/main` (or HEAD). If 611f4ba is missing, STOP — do not delete the submodule `.git`.

---

### Task 2: Absorb the plugin into the parent repo (de-submodule)

**Files:**
- Modify: parent index — remove gitlink `plugin-repos/pga-tour-leaderboard`, add its files as plain tracked files.
- Delete: `plugin-repos/pga-tour-leaderboard/.git` (and any `.git/modules/...` leftover)

- [ ] **Step 1: Confirm working tree is at the custom commit before touching anything**

```bash
cd "C:/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix"
git -C plugin-repos/pga-tour-leaderboard log --oneline -1
git -C plugin-repos/pga-tour-leaderboard grep -c "def get_live_games" -- manager.py
```
Expected: `611f4ba ...` and `1`. If not 611f4ba, STOP.

- [ ] **Step 2: Remove the gitlink from the parent index (keeps working-tree files)**

```bash
git rm --cached plugin-repos/pga-tour-leaderboard
```
Expected: `rm 'plugin-repos/pga-tour-leaderboard'` (one line — it's a single gitlink entry).

- [ ] **Step 3: Convert the submodule into a plain directory (delete its git metadata)**

```bash
rm -rf plugin-repos/pga-tour-leaderboard/.git
rm -rf .git/modules/plugin-repos/pga-tour-leaderboard
```
Expected: no output. (`.git/modules/...` may not exist — harmless.)

- [ ] **Step 4: Stage the plugin as plain files (nested `.gitignore` excludes `__pycache__`, `.dependencies_installed`)**

```bash
git add plugin-repos/pga-tour-leaderboard
git status --short plugin-repos/pga-tour-leaderboard | head -40
```
Expected: a list of `A  plugin-repos/pga-tour-leaderboard/<file>` for manager.py, manifest.json, config_schema.json, requirements.txt, pga-logo.png, masters-logo.png, README.md, etc. **Verify NO `__pycache__`, no `.pyc`, no `.dependencies_installed`, no `.git`** in the staged list.

---

### Task 3: Local verification (the absorbed plugin is correct + complete)

- [ ] **Step 1: Confirm the staged manager.py is the custom build with get_live_games**

```bash
cd "C:/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix"
git show ":plugin-repos/pga-tour-leaderboard/manager.py" | grep -c "def get_live_games"
git show ":plugin-repos/pga-tour-leaderboard/manager.py" | grep -cE "PGA_GRACE_SEC|kalshi_match_tournament_winners|_display_game_focus|GolfLeaderboardRenderer"
```
Expected: `1` and `21` (matches the custom build; the stock plugin would be `0` and `0`).

- [ ] **Step 2: Confirm the manifest declares game_focus (so the card + routing work)**

```bash
git show ":plugin-repos/pga-tour-leaderboard/manifest.json" | grep -A3 display_modes
```
Expected: `display_modes` array containing both `pga_leaderboard` and `game_focus`.

- [ ] **Step 3: Confirm the parent-side renderer/matcher imports exist on the branch (already on Pi)**

```bash
git ls-tree -r --name-only HEAD -- src/game_mode | grep -E "golf_renderer|kalshi_matcher"
```
Expected: both `src/game_mode/golf_renderer.py` and `src/game_mode/kalshi_matcher.py` listed.

---

### Task 4: Commit + push

- [ ] **Step 1: Commit the absorption**

```bash
cd "C:/Users/ericv/OneDrive/Desktop/Claude Projects/Outdoor Ticker/LEDMatrix"
git commit -m "$(cat <<'EOF'
feat(pga): absorb custom Kalshi golf plugin into the fork

The Pi cloned sarjent/ledmatrix-golf stock `main` on rebuild, reverting
the golf plugin to the off-the-shelf version with no get_live_games (no
Live-Games card) and none of Eric's Kalshi top-N leaderboard / game_focus
renderer. The custom build (611f4ba) lived only on this laptop + a OneDrive
bundle, on no remote, so the Pi could never pull it.

De-submodule plugin-repos/pga-tour-leaderboard and track its files
directly in the fork so it deploys via the normal parent `git pull` and
survives future rebuilds. No new Python deps (requests/Pillow are core);
the renderer/matcher it imports already live in src/game_mode/.

History preserved in C:\Users\ericv\OneDrive\golf-plugin-611f4ba.bundle.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
git log --oneline -1
```
Expected: a new commit referencing the absorbed plugin.

- [ ] **Step 2: Push to origin**

```bash
git push origin HEAD:feature/soccer-worldcup-game-mode 2>&1 | tail -5
```
Expected: `... -> feature/soccer-worldcup-game-mode`. If the push hangs (large pack — the plugin adds ~2 small PNGs + text), retry once; if it still hangs, chunk per the WIKI git-chunked-push workaround.

---

### Task 5: Pi-side transition (Eric runs — submodule → plain files + restart)

**Eric pastes these at the Pi shell. SSH in FIRST (do not paste the ssh line if already on the Pi).**

- [ ] **Step 1: Fetch + remove the stock submodule completely**

```bash
cd ~/LEDMatrix
git fetch origin
git submodule deinit -f plugin-repos/pga-tour-leaderboard 2>/dev/null || true
rm -rf plugin-repos/pga-tour-leaderboard
rm -rf .git/modules/plugin-repos/pga-tour-leaderboard 2>/dev/null || true
```

- [ ] **Step 2: Fast-forward (writes the plugin as plain files)**

```bash
git merge --ff-only origin/feature/soccer-worldcup-game-mode
```
Expected: `Fast-forward` updating to the absorb commit. **If it errors** (gitlink/index conflict), run the safe fallback (config.json is gitignored and survives; only installer chmod is lost and re-applies):
```bash
git reset --hard origin/feature/soccer-worldcup-game-mode
```

- [ ] **Step 3: Verify the custom plugin landed**

```bash
grep -c "def get_live_games" plugin-repos/pga-tour-leaderboard/manager.py
grep -c "PGA_GRACE_SEC" plugin-repos/pga-tour-leaderboard/manager.py
```
Expected: `1` and `1` (stock would be `0` and `0`).

- [ ] **Step 4: Hard restart (Python change — needs the service restart)**

```bash
sudo systemctl restart ledmatrix.service && systemctl is-active ledmatrix.service
```
Expected: `active`. Tell the agent when you see `active`.

---

### Task 6: Verify on the Pi via web API (agent)

- [ ] **Step 1: Golf now surfaces as a Live-Games card**

```bash
curl -s --max-time 10 "http://10.0.0.24:5000/api/v3/games/live" | python -c "import sys,json; d=json.load(sys.stdin)['data']; print('pga present:', any('pga' in str(g.get('plugin_id','')) for g in d['games'])); print([g for g in d['games'] if 'pga' in str(g.get('plugin_id',''))])"
```
Expected: `pga present: True` with a golf row (league `pga`).

- [ ] **Step 2: Focus golf → renders the custom top-N Kalshi leaderboard**

```bash
curl -s -X POST "http://10.0.0.24:5000/api/v3/display/on-demand/start" -H "Content-Type: application/json" -d '{"plugin_id":"pga-tour-leaderboard","mode":"game_focus","pinned":true}'
# poll status -> expect plugin_id pga-tour-leaderboard, mode game_focus
# capture display/current PNG -> expect Eric's leaderboard (top-N players + Kalshi odds)
```
Expected: status `plugin_id: pga-tour-leaderboard`, and the PNG shows the custom Kalshi leaderboard. Then clear the pin (`display/on-demand/stop`, or `display/restart`) to restore rotation.

- [ ] **Step 3: Capture pixel proof** — read the `display/current` PNG and confirm it is the custom view (player rows + Kalshi probability column), not the stock scroll.

---

### Task 7: Update project memory + LOG

- [ ] **Step 1: Update memory** — amend `project_golf_focus_fix.md` (and its MEMORY.md pointer) to record that the Pi was running stock sarjent pga, the absorb fixed it, and the submodule is now plain files in the fork (rebuild-safe).

- [ ] **Step 2: Append a dated LOG.md entry** at the project root summarizing the stock-plugin discovery + the absorb, per the WIKI update protocol.

---

## Self-Review

- **Spec coverage:** Eric's ask = clickable golf FOCUS card + custom top-N Kalshi leaderboard on the remote. Task 6 verifies both (card surfacing via get_live_games + focus render). Routing was already fixed (`e960db81`). ✓
- **No new deps:** requirements = requests/Pillow (core); renderer/matcher in `src/game_mode/` already tracked → on Pi. ✓
- **Junk exclusion:** nested `.gitignore` + explicit Task 2 Step 4 check prevent committing `__pycache__`/`.dependencies_installed`/`.git`. ✓
- **Reversibility:** history bundled (Task 1) before any `rm`; Pi fallback is `git reset --hard` (config.json gitignored, survives). ✓
- **Rebuild durability:** plugin now tracked in the fork → future `git clone` of the fork includes it; no external submodule to revert to stock. ✓
