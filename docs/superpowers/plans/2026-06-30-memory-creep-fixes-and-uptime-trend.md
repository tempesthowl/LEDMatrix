# Memory Creep Fixes + Uptime Trend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Pi's monotonic RAM creep by capping every unbounded in-memory structure found in the audit, and extend the `/v3/remote` memory-trend chart from a browser-local 1h window to a server-side uptime-scale history with a per-process / cache breakdown so the creep is visible and the fixes are verifiable.

**Architecture:** Two parts. (A) Bound each unbounded structure at its source — FontManager text-metrics cache, per-plugin logo caches, error-aggregator pattern list, soccer fetch-request dict, operation-queue index, oversized values in the central memory cache, and the Vegas content-cache — plus convert O(n) hot-path lists to deques. (B) Add a small bounded server-side memory sampler + `/api/v3/system/memory-history` endpoint, enrich `/api/v3/system/status` with per-process RSS and cache stats (controller publishes its own stats to the shared cache), and repoint the remote chart at the server history.

**Tech Stack:** Python 3.13, psutil, Flask, PIL, vanilla JS. Tests: pytest (`test/`).

## Global Constraints

- **No ad-hoc Pi changes.** Every fix ships through the repo; Eric deploys via `git pull` + service restart. Do NOT SSH the Pi.
- **pytest invocation:** `python -m pytest <path> -v -p no:cacheprovider --override-ini="addopts="`. The `--override-ini="addopts="` is REQUIRED (pytest.ini bakes in `--cov`; pytest-cov isn't installed; `--no-cov` does NOT work). Controller/display tests also need `EMULATOR=true`.
- **Plugins are plain tracked files** in `plugin-repos/*` (rebuild-safe to edit); no registry version bump needed.
- **Bound, don't break:** every cap must preserve correctness — a cache that evicts re-fetches/re-measures on miss; never drop data a caller still needs in-cycle.
- **Stage explicit paths only** — NEVER `git add -A`/`git add .`.
- **Cache-bust rule:** bump the `?v=N` on `remote.js` in `remote.html` whenever `remote.js` changes. (Trend code lives inline in `remote.html`, which is re-rendered per request — no bust needed for HTML-only edits, but bump if `remote.js` is touched.)
- **Deploy targets:** Python changes (controller/plugins/cache/font/error) → `sudo systemctl restart ledmatrix`. Web/endpoint/JS/HTML → `sudo systemctl restart ledmatrix-web`. This sweep touches both.
- Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Root-cause summary (from the audit)

| # | Structure | File | Growth | Task |
|---|---|---|---|---|
| 1 | `FontManager.metrics_cache` | `src/font_manager.py:35` | 1 entry per unique rendered string (scores/clocks/odds), no cap | 1 |
| 2 | Per-plugin `_logo_cache` | `plugin-repos/{football,basketball,soccer}-scoreboard/sports.py` | 1 PIL image per unique team, no cap (canonical base HAS a cap) | 2 |
| 3 | `ErrorPattern.affected_plugins` | `src/error_aggregator.py:236` | `.extend()` per error once a pattern is active | 3 |
| 4 | soccer `background_fetch_requests` | `plugin-repos/soccer-scoreboard/soccer_managers.py:160` | 1 entry/day/instance, missing `del` | 4 |
| 5 | `OperationQueue._operations` | `src/plugin_system/operation_queue.py:56` | 1 entry per op, never evicted | 5 |
| 6 | oversized values in `MemoryCache` | `src/cache_manager.py` / `src/cache/memory_cache.py` | 73MB schedule → ~300-500MB live, pinned by hot access | 6 |
| 7 | `PluginAdapter._content_cache` | `src/vegas_mode/plugin_adapter.py:564` | redundant `img.copy()` per plugin; cleanup only on write | 7 |
| 8 | O(n) hot-path lists | `scroll_helper.py:107`, `logo_helper.py:82`, `error_aggregator.py:156` | GC churn (bounded size, O(n) ops) | 8 |

## File Structure

- **Modify** `src/font_manager.py` — bound `metrics_cache` (Task 1).
- **Modify** `plugin-repos/football-scoreboard/sports.py`, `plugin-repos/basketball-scoreboard/sports.py`, `plugin-repos/basketball-scoreboard/basketball_helpers.py`, `plugin-repos/soccer-scoreboard/sports.py` — backport logo cap (Task 2).
- **Modify** `src/error_aggregator.py` — cap `affected_plugins`; `_records` → deque (Tasks 3, 8).
- **Modify** `plugin-repos/soccer-scoreboard/soccer_managers.py` — evict `background_fetch_requests` (Task 4).
- **Modify** `src/plugin_system/operation_queue.py` — evict completed ops (Task 5).
- **Modify** `src/cache_manager.py` — skip memory cache for oversized disk values (Task 6).
- **Modify** `src/vegas_mode/plugin_adapter.py` — content-cache cap + drop redundant copy (Task 7).
- **Modify** `src/common/scroll_helper.py`, `src/common/logo_helper.py` — deque/OrderedDict (Task 8).
- **Create** `src/system/memory_history.py` — bounded memory sampler (Task 9).
- **Modify** `web_interface/blueprints/api_v3.py` — `/system/memory-history` endpoint + RSS/cache fields on `/system/status` (Tasks 9, 10).
- **Modify** `src/display_controller.py` — publish cache/RSS stats to shared cache (Task 10).
- **Modify** `web_interface/templates/v3/partials/remote.html` — chart consumes server history, relabel to uptime (Task 11).
- **Create** tests under `test/` per task.

---

## Task 1: Bound `FontManager.metrics_cache`

**Files:**
- Modify: `src/font_manager.py:35` (declaration), `src/font_manager.py:520-521` (insertion site)
- Test: `test/test_font_manager_metrics_cap.py`

**Interfaces:**
- Produces: `FontManager.metrics_cache` stays ≤ `FontManager._METRICS_CACHE_MAX` (2048) entries; oldest evicted FIFO.

- [ ] **Step 1: Write the failing test**

```python
# test/test_font_manager_metrics_cap.py
"""metrics_cache must not grow unbounded — it keys on dynamic text."""
from PIL import ImageFont
from src.font_manager import FontManager


def _fm():
    # Bypass heavy __init__/font discovery — measure_text only touches metrics_cache.
    fm = FontManager.__new__(FontManager)
    fm.metrics_cache = {}
    return fm


def test_metrics_cache_is_capped():
    fm = _fm()
    font = ImageFont.load_default()
    # Feed far more unique strings than the cap.
    for i in range(FontManager._METRICS_CACHE_MAX + 500):
        fm.measure_text(f"score-{i}", font)
    assert len(fm.metrics_cache) <= FontManager._METRICS_CACHE_MAX
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_font_manager_metrics_cap.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `AttributeError: _METRICS_CACHE_MAX` (or assertion: cache grows past cap).

- [ ] **Step 3: Implement the cap**

Add a class constant near the top of the `FontManager` class (just before `__init__`):

```python
    _METRICS_CACHE_MAX = 2048
```

Replace the insertion at `src/font_manager.py:520-521`:

```python
        result = (width, height, baseline)
        # Bound the cache: it keys on (hash(text), id(font)); dynamic strings
        # (scores, clocks, Kalshi %) would otherwise grow it without limit.
        if len(self.metrics_cache) >= self._METRICS_CACHE_MAX:
            # FIFO drop of the oldest inserted key (dict preserves insertion order).
            self.metrics_cache.pop(next(iter(self.metrics_cache)), None)
        self.metrics_cache[cache_key] = result
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_font_manager_metrics_cap.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/font_manager.py test/test_font_manager_metrics_cap.py
git commit -m "fix(mem): cap FontManager.metrics_cache (FIFO, 2048) — primary creep source"
```

---

## Task 2: Backport logo-cache cap to plugin `sports.py` copies

**Files:**
- Modify: `plugin-repos/football-scoreboard/sports.py`, `plugin-repos/basketball-scoreboard/sports.py`, `plugin-repos/soccer-scoreboard/sports.py`, `plugin-repos/basketball-scoreboard/basketball_helpers.py`
- Test: `test/plugins/test_logo_cache_cap.py`

**Interfaces:**
- Consumes: the canonical pattern at `src/base_classes/sports.py:89-95` (decls) and `:355-363` (`_cache_logo`).
- Produces: each plugin class gains `_logo_cache_order: List[str]`, `_logo_cache_max: int = 256`, and a `_cache_logo(self, key, value)` method; every raw `self._logo_cache[...] = ...` write is replaced by `self._cache_logo(...)`.

- [ ] **Step 1: Locate every uncapped write**

Run: `grep -rnE "self\._logo_cache\[" plugin-repos/football-scoreboard/sports.py plugin-repos/basketball-scoreboard/sports.py plugin-repos/basketball-scoreboard/basketball_helpers.py plugin-repos/soccer-scoreboard/sports.py`
Expected sites (verify current line numbers): football `sports.py:529`, basketball `sports.py:557`, basketball_helpers `:82`, soccer `sports.py:621`. Also grep each file for where `self._logo_cache` is initialized (`self._logo_cache: Dict... = {}` / `self._logo_cache = {}`) to place the new attrs beside it.

- [ ] **Step 2: Write the failing test**

```python
# test/plugins/test_logo_cache_cap.py
"""Plugin-local logo caches must cap like the canonical base (was unbounded)."""
import importlib.util, sys
from pathlib import Path
from PIL import Image

_REPO = Path(__file__).resolve().parents[2]


def _load(mod_name, rel):
    p = _REPO / rel
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    # plugin sports.py imports sibling modules — put its dir on sys.path
    d = str(p.parent)
    added = d not in sys.path
    if added:
        sys.path.insert(0, d)
    try:
        spec.loader.exec_module(mod)
    finally:
        if added and d in sys.path:
            sys.path.remove(d)
    return mod


import pytest


@pytest.mark.parametrize("mod_name,rel,cls_suffix", [
    ("fb_sports_cap", "plugin-repos/football-scoreboard/sports.py", None),
    ("bb_sports_cap", "plugin-repos/basketball-scoreboard/sports.py", None),
    ("sc_sports_cap", "plugin-repos/soccer-scoreboard/sports.py", None),
])
def test_cache_logo_evicts_over_cap(mod_name, rel, cls_suffix):
    mod = _load(mod_name, rel)
    # Find the class that defines _cache_logo (the SportsCore-like base in the copy).
    cls = next(v for v in vars(mod).values()
               if isinstance(v, type) and hasattr(v, "_cache_logo"))
    inst = cls.__new__(cls)
    inst._logo_cache = {}
    inst._logo_cache_order = []
    inst._logo_cache_max = 4  # small for the test
    img = Image.new("RGBA", (4, 4))
    for i in range(10):
        inst._cache_logo(f"TEAM{i}", img)
    assert len(inst._logo_cache) <= 4
    assert len(inst._logo_cache_order) <= 4
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest test/plugins/test_logo_cache_cap.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — `StopIteration` (no class has `_cache_logo`).

- [ ] **Step 4: Add the cap to each plugin file**

In each of the three `sports.py` copies, beside the `self._logo_cache = {}` init, add:

```python
        self._logo_cache_order: List[str] = []
        self._logo_cache_max: int = 256
```

(Ensure `from typing import List` is imported — it almost certainly already is; if not, add it.)

Add this method to the same class (copy verbatim from `src/base_classes/sports.py:355-363`):

```python
    def _cache_logo(self, key: str, value: "Image.Image") -> None:
        """Insert into _logo_cache, evicting the oldest entry if at cap."""
        if key in self._logo_cache:
            return
        if len(self._logo_cache) >= self._logo_cache_max and self._logo_cache_order:
            oldest = self._logo_cache_order.pop(0)
            self._logo_cache.pop(oldest, None)
        self._logo_cache[key] = value
        self._logo_cache_order.append(key)
```

Replace each raw write found in Step 1 — e.g. football `sports.py:529`:

```python
            self._cache_logo(team_abbrev, logo)
```

For `basketball_helpers.py:82`: that write may be in a free function or a different class. If it writes to a manager's `self._logo_cache`, route it through that object's `_cache_logo` if available; if the helper has no access to the capped object, give it its own module-level cap OR (preferred) have it call back into the owning manager's `_cache_logo`. Inspect the surrounding code and pick the route that reuses the cap — do NOT leave an uncapped write.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest test/plugins/test_logo_cache_cap.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (3 params).

- [ ] **Step 6: Commit**

```bash
git add plugin-repos/football-scoreboard/sports.py plugin-repos/basketball-scoreboard/sports.py plugin-repos/basketball-scoreboard/basketball_helpers.py plugin-repos/soccer-scoreboard/sports.py test/plugins/test_logo_cache_cap.py
git commit -m "fix(mem): backport 256-entry logo-cache cap to plugin sports.py copies"
```

---

## Task 3: Cap `ErrorPattern.affected_plugins`

**Files:**
- Modify: `src/error_aggregator.py:236`
- Test: `test/test_error_aggregator_caps.py`

**Interfaces:**
- Produces: after a pattern update, `affected_plugins` is deduped and capped at 50 entries.

- [ ] **Step 1: Write the failing test**

```python
# test/test_error_aggregator_caps.py
"""ErrorPattern.affected_plugins must not grow without bound on repeated errors."""
from src.error_aggregator import ErrorAggregator


def test_affected_plugins_capped():
    agg = ErrorAggregator()
    # Generate many same-type errors from many distinct plugins to grow a pattern.
    for i in range(500):
        try:
            raise ValueError("boom")
        except ValueError as e:
            agg.record_error(e, plugin_id=f"plugin-{i}")
    for pat in agg._patterns.values():
        assert len(pat.affected_plugins) <= 50
```

> Confirm the constructor signature: if `ErrorAggregator()` needs args, inspect `__init__` and pass minimal/defaults. If pattern detection needs a recurrence threshold, 500 identical errors will exceed any sane threshold.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_error_aggregator_caps.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (affected_plugins grows past 50).

- [ ] **Step 3: Implement the cap**

Replace `src/error_aggregator.py:236`:

```python
                # Dedupe + cap: this fires on every error once a pattern is active,
                # so an unbounded extend() leaks proportional to error volume.
                merged = self._patterns[pattern_key].affected_plugins + affected_plugins
                self._patterns[pattern_key].affected_plugins = list(dict.fromkeys(merged))[-50:]
```

(`dict.fromkeys` preserves order while deduping; `[-50:]` keeps the most recent 50.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_error_aggregator_caps.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/error_aggregator.py test/test_error_aggregator_caps.py
git commit -m "fix(mem): dedupe+cap ErrorPattern.affected_plugins at 50"
```

---

## Task 4: Evict soccer `background_fetch_requests`

**Files:**
- Modify: `plugin-repos/soccer-scoreboard/soccer_managers.py:126-160`
- Test: covered by inspection + Task 12 (closure-local; unit-testing the manager requires heavy construction). Add a focused test only if the manager is cheaply constructible.

- [ ] **Step 1: Add the cleanup inside `fetch_callback`**

In `_fetch_soccer_api_data` (or whichever method owns the closure at line 126), the callback closes over `self` and `date_str`. Add eviction so the completed request's key doesn't linger (mirroring baseball/football which `del` by season_year):

```python
            def fetch_callback(result):
                """Callback when background fetch completes."""
                if result.success:
                    self.logger.info(
                        f"Background fetch completed for {self.league_name}: {len(result.data.get('events', []))} events"
                    )
                else:
                    self.logger.error(
                        f"Background fetch failed for {self.league_name}: {result.error}"
                    )
                # The key is a daily-rotating date range ("20260616-20260630") — without
                # this, one entry accumulates per day per league-manager instance forever.
                try:
                    self.background_fetch_requests.pop(date_str, None)
                except AttributeError:
                    pass
```

- [ ] **Step 2: Verify no syntax error**

Run: `python -c "import ast; ast.parse(open(r'plugin-repos/soccer-scoreboard/soccer_managers.py', encoding='utf-8').read())" && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add plugin-repos/soccer-scoreboard/soccer_managers.py
git commit -m "fix(mem): evict completed date key from soccer background_fetch_requests"
```

---

## Task 5: Evict completed ops from `OperationQueue._operations`

**Files:**
- Modify: `src/plugin_system/operation_queue.py:319` (inside the `finally` of `_execute_operation`)
- Test: `test/test_operation_queue_evict.py`

**Interfaces:**
- Consumes: `self._operations: Dict[str, PluginOperation]` (declared ~line 56); `self._operation_history` (capped at `max_history`).
- Produces: after an op completes, its `operation_id` is removed from `_operations` (it lives on only in `_operation_history`).

- [ ] **Step 1: Write the failing test**

```python
# test/test_operation_queue_evict.py
"""Completed operations must not accumulate in _operations (only in history)."""
from src.plugin_system.operation_queue import OperationQueue


def test_completed_ops_evicted_from_index():
    q = OperationQueue()  # inspect __init__; pass minimal args if required
    # Enqueue + execute several ops; exact API may differ — drive the public
    # enqueue/execute path used in production. After each completes, the op
    # should not remain in q._operations.
    ids = []
    for i in range(20):
        op_id = q.enqueue_operation(plugin_id=f"p{i}", operation_type="noop", parameters={})
        ids.append(op_id)
    # Execute the queue synchronously (use whatever drains it; if execution is
    # threaded, call the internal _execute_operation per op or the worker drain).
    q.process_all() if hasattr(q, "process_all") else None
    assert all(op_id not in q._operations for op_id in ids if op_id)
```

> This task REQUIRES reading `operation_queue.py` to learn the real enqueue/execute API (the names above are placeholders for whatever exists). If ops execute on a worker thread, the test should enqueue, wait for completion via the queue's own completion signal, then assert. If the queue is not cheaply drivable in a unit test, replace this with a direct `_add_to_history` + eviction unit test on a hand-built `PluginOperation`, asserting the post-condition of the new line.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/test_operation_queue_evict.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (ids remain in `_operations`).

- [ ] **Step 3: Implement the eviction**

In `_execute_operation`'s `finally` block, immediately after `self._add_to_history(operation)` (line 319):

```python
                # Completed ops live in _operation_history (capped). Drop them from
                # the primary index so it doesn't grow one UUID per op forever.
                self._operations.pop(operation.operation_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/test_operation_queue_evict.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/plugin_system/operation_queue.py test/test_operation_queue_evict.py
git commit -m "fix(mem): evict completed operations from OperationQueue._operations index"
```

---

## Task 6: Keep oversized values out of the memory cache

**Files:**
- Modify: `src/cache_manager.py` (the disk-hit re-population sites, ~line 296-299 and ~336) + `src/cache/disk_cache.py` (expose file size)
- Test: `test/test_cache_oversized_skips_memory.py`

**Interfaces:**
- Produces: `CacheManager` only re-populates the in-memory cache from a disk hit when the on-disk payload is `< CacheManager._MAX_MEMORY_VALUE_BYTES` (default 5 MiB). Huge values (e.g. the 73 MB MLB schedule) are served from disk and never pinned in RAM.

**Why this design:** deep-sizing arbitrary nested dicts at every `set()` is expensive and error-prone. The disk file size is a cheap, accurate proxy (`os.path.getsize`), available exactly where the large value is about to be loaded into RAM.

- [ ] **Step 1: Add a size helper to DiskCache**

In `src/cache/disk_cache.py`, add a method (place near `get`):

```python
    def get_file_size(self, key: str) -> int:
        """Bytes of the on-disk cache file for key, or 0 if absent."""
        try:
            path = self._get_cache_path(key)  # use the existing path builder
            return os.path.getsize(path) if path and os.path.exists(path) else 0
        except OSError:
            return 0
```

(Confirm the internal path-builder name in `disk_cache.py`; reuse it. Ensure `import os` is present.)

- [ ] **Step 2: Write the failing test**

```python
# test/test_cache_oversized_skips_memory.py
"""Oversized disk values must not be re-deposited into the in-memory cache."""
from src.cache_manager import CacheManager


def test_oversized_value_not_held_in_memory(tmp_path, monkeypatch):
    cm = CacheManager()
    # Force a known small threshold for the test.
    monkeypatch.setattr(cm, "_MAX_MEMORY_VALUE_BYTES", 1024, raising=False)
    big = {"events": ["x" * 100 for _ in range(1000)]}  # >1KB on disk
    cm.save_cache("huge_key", big)
    # Clear memory so the next read comes from disk and tries to re-populate.
    cm._memory_cache.clear()
    cm._memory_cache_timestamps.clear()
    got = cm.get_cached_data("huge_key", max_age=3600)
    assert got is not None                      # still served (from disk)
    assert "huge_key" not in cm._memory_cache   # but NOT pinned in RAM
```

> If `CacheManager()` requires a cache dir, it self-resolves one; the test relies on that. If save/get key naming differs, align to the real API.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest test/test_cache_oversized_skips_memory.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (`huge_key` present in `_memory_cache`).

- [ ] **Step 4: Implement the guard**

Add the constant in `CacheManager.__init__` (near the other cache config):

```python
        self._MAX_MEMORY_VALUE_BYTES = 5 * 1024 * 1024  # don't pin >5MiB values in RAM
```

At each site where a disk hit re-populates the memory cache (`get_cached_data`, ~line 299; and the parallel path ~line 336), guard the `self._memory_cache_component.set(key, record)` call:

```python
            if self._disk_cache_component.get_file_size(key) < self._MAX_MEMORY_VALUE_BYTES:
                self._memory_cache_component.set(key, record)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest test/test_cache_oversized_skips_memory.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS. Also run the existing cache tests:
Run: `python -m pytest test/ -k cache -v -p no:cacheprovider --override-ini="addopts="`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/cache_manager.py src/cache/disk_cache.py test/test_cache_oversized_skips_memory.py
git commit -m "fix(mem): serve oversized cache values from disk, don't pin them in RAM"
```

---

## Task 7: Cap the Vegas content cache + drop the redundant copy

**Files:**
- Modify: `src/vegas_mode/plugin_adapter.py:48` (decl), `:564-572` (`_cache_content`), and `_get_cached` (eviction-on-miss)
- Test: `test/test_plugin_adapter_content_cache.py`

**Interfaces:**
- Produces: `_content_cache` holds at most one entry per plugin and sweeps expired entries on read-miss too (not only on write).

- [ ] **Step 1: Read the current cache code**

Run: `grep -nE "_content_cache|_cache_content|_get_cached|_cleanup_expired_cache_locked|img\.copy" src/vegas_mode/plugin_adapter.py`
Understand the read/write/cleanup paths before changing them.

- [ ] **Step 2: Write the failing test**

```python
# test/test_plugin_adapter_content_cache.py
"""Expired content-cache entries must be swept on read-miss, not only on write."""
import time
from src.vegas_mode.plugin_adapter import PluginAdapter


def test_expired_entries_swept_on_read(monkeypatch):
    pa = PluginAdapter.__new__(PluginAdapter)   # bypass heavy __init__
    import threading
    pa._content_cache = {}
    pa._cache_lock = threading.Lock()
    pa._cache_ttl = 0.01
    # Seed an entry, let it expire, then read a DIFFERENT key — the stale one
    # must be gone after the read path runs its sweep.
    pa._content_cache["old"] = (time.time() - 1.0, ["x"])
    pa._get_cached("other")   # read-miss
    assert "old" not in pa._content_cache
```

> Align attribute names (`_cache_ttl`, tuple shape) to the real class after Step 1. If `_get_cached` doesn't currently sweep, that's the bug under test.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest test/test_plugin_adapter_content_cache.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (`old` still present).

- [ ] **Step 4: Implement**

(a) In `_get_cached`, call `self._cleanup_expired_cache_locked()` on the miss path (under the lock) so stale entries are swept even when their plugin is never re-fetched.

(b) In `_cache_content`, drop the redundant deep copy unless mutation is actually required — change `[img.copy() for img in content]` to store `content` directly (the adapter is the producer; if a consumer mutates, document it). If a copy is genuinely needed, keep it but ensure the OLD list's images are released: before reassigning `self._content_cache[plugin_id]`, `del` the previous entry.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest test/test_plugin_adapter_content_cache.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS. Then run the vegas tests:
Run: `EMULATOR=true python -m pytest test/ -k "vegas or adapter" -v -p no:cacheprovider --override-ini="addopts="`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/vegas_mode/plugin_adapter.py test/test_plugin_adapter_content_cache.py
git commit -m "fix(mem): sweep Vegas content-cache on read-miss; drop redundant image copy"
```

---

## Task 8: O(n) hot-path lists → deque/OrderedDict

**Files:**
- Modify: `src/common/scroll_helper.py:107,814-818`; `src/common/logo_helper.py:82-85`; `src/error_aggregator.py:156-158`
- Test: `test/test_hotpath_structures.py`

**Interfaces:**
- Produces: `ScrollHelper.frame_times` and `ErrorAggregator._records` become `collections.deque(maxlen=...)`; `LogoHelper` LRU uses `OrderedDict.move_to_end`.

- [ ] **Step 1: Write the failing test**

```python
# test/test_hotpath_structures.py
from collections import deque
from src.common.scroll_helper import ScrollHelper


def test_frame_times_is_bounded_deque():
    sh = ScrollHelper.__new__(ScrollHelper)
    sh.frame_times = deque(maxlen=100)
    sh.last_frame_time = 0.0
    for _ in range(500):
        sh.log_frame_rate()
    assert len(sh.frame_times) <= 100
    assert isinstance(sh.frame_times, deque)
```

> `log_frame_rate` reads `self.last_frame_time` and appends to `self.frame_times`; the `__new__` shim provides both. If it touches more state, add the minimal attrs.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/test_hotpath_structures.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (current code resets `frame_times` to a list, or the `pop(0)` logic conflicts with deque).

- [ ] **Step 3: Implement**

- `scroll_helper.py:107`: `self.frame_times = deque(maxlen=100)` (add `from collections import deque`). In `log_frame_rate` (814-818), replace the manual `append`+`if len>100: pop(0)` with a plain `self.frame_times.append(frame_time)` (deque auto-evicts).
- `error_aggregator.py`: change `_records` to `deque(maxlen=self.max_records)` and drop the manual `pop(0)` at 156-158 (keep `.append`).
- `logo_helper.py:82-85`: replace the `list.remove()`/`append` LRU with an `OrderedDict` + `move_to_end(key)`; evict via `popitem(last=False)` when over `cache_size`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest test/test_hotpath_structures.py test/test_error_aggregator_caps.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS (and Task 3's test still green).

- [ ] **Step 5: Commit**

```bash
git add src/common/scroll_helper.py src/common/logo_helper.py src/error_aggregator.py test/test_hotpath_structures.py
git commit -m "perf(mem): O(1) deque/OrderedDict for frame_times, _records, logo LRU"
```

---

## Task 9: Server-side memory-history sampler + endpoint

**Files:**
- Create: `src/system/memory_history.py`
- Modify: `web_interface/blueprints/api_v3.py` (new route + start the sampler)
- Test: `test/test_memory_history.py`

**Interfaces:**
- Produces: `MemoryHistory(max_samples=2880, min_interval_s=30)` with `.sample()` (records `{t, mem}` if `min_interval` elapsed) and `.snapshot()` → `{"samples": [{"t": float, "mem": float}, ...], "started_at": float}`. Singleton `get_memory_history()`. New route `GET /api/v3/system/memory-history` → `{"status":"success","data": <snapshot>}`.

- [ ] **Step 1: Write the failing test**

```python
# test/test_memory_history.py
from src.system.memory_history import MemoryHistory


def test_min_interval_dedup_and_cap():
    h = MemoryHistory(max_samples=5, min_interval_s=1000)
    t0 = 1000.0
    h.sample(now=t0, mem_percent=50.0)
    h.sample(now=t0 + 1, mem_percent=51.0)   # within min_interval → skipped
    snap = h.snapshot()
    assert len(snap["samples"]) == 1
    assert snap["samples"][0]["mem"] == 50.0
    # Cap: push past max_samples with spaced timestamps.
    for i in range(20):
        h.sample(now=t0 + 2000 * (i + 1), mem_percent=float(i))
    assert len(h.snapshot()["samples"]) <= 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/test_memory_history.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the sampler**

```python
# src/system/memory_history.py
"""Bounded in-process memory-usage history for the uptime trend chart.

Tiny by construction (max_samples * ~24 bytes), so it cannot itself leak.
"""
from __future__ import annotations
import threading
from collections import deque
from typing import Optional

_singleton: Optional["MemoryHistory"] = None
_singleton_lock = threading.Lock()


class MemoryHistory:
    def __init__(self, max_samples: int = 2880, min_interval_s: float = 30.0) -> None:
        self._samples = deque(maxlen=max_samples)  # of (t, mem)
        self._min_interval = min_interval_s
        self._lock = threading.Lock()
        self._started_at: Optional[float] = None
        self._last_t: float = 0.0

    def sample(self, now: float, mem_percent: float) -> None:
        with self._lock:
            if self._started_at is None:
                self._started_at = now
            if self._samples and (now - self._last_t) < self._min_interval:
                return
            self._samples.append((now, round(float(mem_percent), 1)))
            self._last_t = now

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self._started_at,
                "samples": [{"t": t, "mem": m} for (t, m) in self._samples],
            }


def get_memory_history() -> MemoryHistory:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = MemoryHistory()
    return _singleton
```

- [ ] **Step 4: Wire the endpoint + sample on each status read**

In `api_v3.py`, add near the other system routes:

```python
@api_v3.route('/system/memory-history', methods=['GET'])
def get_memory_history_endpoint():
    try:
        from src.system.memory_history import get_memory_history
        return jsonify({'status': 'success', 'data': get_memory_history().snapshot()})
    except Exception:
        logger.exception("[System] memory-history failed")
        return jsonify({'status': 'error', 'message': 'Failed to get memory history'}), 500
```

And in `get_system_status` (the psutil route), right after `memory_percent` is computed (~line 1191), record a sample:

```python
        try:
            from src.system.memory_history import get_memory_history
            get_memory_history().sample(now=time.time(), mem_percent=memory_percent)
        except Exception:
            pass
```

(The `/v3/remote` health poll hits `/system/status` every 10s, which drives sampling; the 30s `min_interval` throttles to 1 sample/30s → 2880 = 24h.)

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest test/test_memory_history.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/system/memory_history.py web_interface/blueprints/api_v3.py test/test_memory_history.py
git commit -m "feat(trend): server-side bounded memory-history sampler + endpoint"
```

---

## Task 10: Per-process RSS + cache-size breakdown on `/system/status`

**Files:**
- Modify: `web_interface/blueprints/api_v3.py` (`get_system_status`), `src/display_controller.py` (publish stats)
- Test: `test/test_system_status_breakdown.py`

**Interfaces:**
- Produces: `/system/status` `data` gains `processes` (list of `{name, rss_mb}` for the controller + web, best-effort via `psutil.process_iter`) and `controller_cache` (`{entries, approx_mb, rss_mb}` read from a shared-cache key the controller publishes). Missing data → omitted/empty, never an error.

- [ ] **Step 1: Controller publishes its own stats**

In `display_controller.py`, in the same place it publishes other shared-cache keys (near `_publish_live_games_cache`), add a throttled (~30s) publish of `display_controller_stats`:

```python
        try:
            import psutil, os
            rss_mb = round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
            mem_entries = len(self.cache_manager._memory_cache) if self.cache_manager else 0
            self.cache_manager.set("display_controller_stats", {
                "rss_mb": rss_mb,
                "mem_cache_entries": mem_entries,
            })
        except Exception:
            pass
```

(Wrap in the existing throttle so it runs ~once per 30s, not every tick.)

- [ ] **Step 2: Write the failing test (web side)**

```python
# test/test_system_status_breakdown.py
from unittest.mock import MagicMock
import pytest
from flask import Flask


@pytest.fixture
def client(monkeypatch):
    from web_interface.blueprints import api_v3
    cache = MagicMock()
    cache.get_cached_data.side_effect = lambda key, **kw: (
        {"rss_mb": 120.0, "mem_cache_entries": 42} if key == "display_controller_stats" else None
    )
    monkeypatch.setattr(api_v3, "_ensure_cache_manager", lambda: cache)
    app = Flask(__name__)
    app.register_blueprint(api_v3.api_v3, url_prefix='/api/v3')
    return app.test_client()


def test_status_includes_controller_cache(client):
    resp = client.get('/api/v3/system/status')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['controller_cache']['entries'] == 42
    assert data['controller_cache']['rss_mb'] == 120.0
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest test/test_system_status_breakdown.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: FAIL (`KeyError: controller_cache`).

- [ ] **Step 4: Implement on `/system/status`**

In `get_system_status`, before building/returning `status`, read the controller stats and add fields:

```python
        controller_cache = {}
        try:
            cache = _ensure_cache_manager()
            rec = cache.get_cached_data('display_controller_stats', max_age=120, memory_ttl=2)
            d = rec.get('data') if isinstance(rec, dict) and 'data' in rec else rec
            if isinstance(d, dict):
                controller_cache = {
                    'entries': d.get('mem_cache_entries', 0),
                    'rss_mb': d.get('rss_mb', 0),
                }
        except Exception:
            pass

        processes = []
        try:
            for p in psutil.process_iter(['name', 'cmdline', 'memory_info']):
                cmd = ' '.join(p.info.get('cmdline') or [])
                if 'run.py' in cmd:
                    processes.append({'name': 'controller', 'rss_mb': round(p.info['memory_info'].rss / (1024*1024), 1)})
                elif 'web_interface' in cmd or 'start.py' in cmd:
                    processes.append({'name': 'web', 'rss_mb': round(p.info['memory_info'].rss / (1024*1024), 1)})
        except Exception:
            pass
```

Add `'controller_cache': controller_cache,` and `'processes': processes,` to the `status` dict.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest test/test_system_status_breakdown.py -v -p no:cacheprovider --override-ini="addopts="`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web_interface/blueprints/api_v3.py src/display_controller.py test/test_system_status_breakdown.py
git commit -m "feat(trend): per-process RSS + controller cache stats on /system/status"
```

---

## Task 11: Repoint the remote trend chart at server history (uptime span)

**Files:**
- Modify: `web_interface/templates/v3/partials/remote.html` (the trend IIFE, lines ~241-377; the label at line ~153)

**Interfaces:**
- Consumes: `GET /api/v3/system/memory-history` (Task 9), `data.processes` / `data.controller_cache` (Task 10).

This is display-only; verified in Task 12 (browser screenshot).

- [ ] **Step 1: Fetch server history on init and seed the buffer**

In the trend IIFE, raise the cap and add a server fetch. Change `MAX_SAMPLES`:

```javascript
        const MAX_SAMPLES = 2880;           // 24h at the 30s server cadence
```

In `init()`, before the MutationObserver wiring, fetch server history and merge (server samples are authoritative for the long window; client samples fill the live tail):

```javascript
            try {
                const r = await fetch('/api/v3/system/memory-history');
                const j = await r.json();
                const s = (j && j.data && j.data.samples) || [];
                if (s.length) {
                    buffer = s.map(p => ({ t: p.t * 1000, v: p.mem }))
                               .filter(p => p.v >= 0 && p.v <= 100)
                               .slice(-MAX_SAMPLES);
                }
            } catch (_) { /* fall back to client-local buffer */ }
```

(Make `init` `async`, or wrap the fetch in an IIFE that calls `render()` on completion. Server `t` is epoch seconds → ×1000 for JS ms.)

- [ ] **Step 2: Relabel the title to the actual span**

Replace the static `Memory trend (1h)` (`remote.html:153`) — set it dynamically in `render()` from the buffer's time span:

```javascript
            const titleEl = document.querySelector('.health-trend-title');
            if (titleEl && buffer.length > 1) {
                const spanH = (buffer[buffer.length - 1].t - buffer[0].t) / 3600000;
                titleEl.textContent = spanH >= 1
                    ? `Memory trend (${spanH.toFixed(0)}h)`
                    : `Memory trend (${Math.round(spanH * 60)}m)`;
            }
```

- [ ] **Step 3: (Optional, same task) show the breakdown**

If `data.processes` / `controller_cache` are present on the health response, render a one-line caption under the trend (controller vs web RSS, controller cache entries) so the creep's owner is visible. Keep it text-only; no new polling.

- [ ] **Step 4: Verify JS is valid**

Extract the IIFE to a temp file and `node --check` it (node at `/c/Program Files/nodejs/node`), or visually confirm brace balance. Delete the temp file; do not commit it.

- [ ] **Step 5: Commit**

```bash
git add web_interface/templates/v3/partials/remote.html
git commit -m "feat(trend): remote chart consumes server memory-history; label shows uptime span"
```

---

## Task 12: Integration verification + test log

**Files:**
- Create: `docs/superpowers/test-logs/2026-06-30-memory-creep-and-trend.md`

- [ ] **Step 1: Full new-test suite**

Run: `EMULATOR=true python -m pytest test/test_font_manager_metrics_cap.py test/plugins/test_logo_cache_cap.py test/test_error_aggregator_caps.py test/test_operation_queue_evict.py test/test_cache_oversized_skips_memory.py test/test_plugin_adapter_content_cache.py test/test_hotpath_structures.py test/test_memory_history.py test/test_system_status_breakdown.py -p no:cacheprovider --override-ini="addopts="`
Expected: all PASS.

- [ ] **Step 2: Regression sweep**

Run: `EMULATOR=true python -m pytest test/ -p no:cacheprovider --override-ini="addopts=" -q 2>&1 | tail -20`
Compare failures against the known pre-existing set (`test_remote_route_contains_zones`, 2× `save_plugin_config` in `test_web_api.py`). No NEW failures allowed.

- [ ] **Step 3: Dev-loop verification of the trend**

Launch `bash scripts/dev-emulator.sh` + `bash scripts/dev-webui.sh`. Then:
- `curl -s localhost:5000/api/v3/system/memory-history | python -m json.tool` → samples array present.
- `curl -s localhost:5000/api/v3/system/status | python -m json.tool` → `controller_cache` + `processes` present.
- Headless Playwright screenshot of `/v3/remote` showing the trend cell with the uptime label (Preview/Chrome MCP are incompatible with this app — use Playwright, `wait_until="domcontentloaded"`).

- [ ] **Step 4: Write the test log**

Document per-fix status, the test output, the trend screenshot + API JSON, file:line of each cap, and an honest "not proven" section (the real RAM-flattening is only confirmable on the Pi over a day post-deploy — note that the instrumentation is the verification instrument). Follow `docs/superpowers/test-logs/2026-06-29-upcoming-games-cell.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/test-logs/2026-06-30-memory-creep-and-trend.md
git commit -m "docs(mem): integration test log for creep fixes + uptime trend"
```

---

## Self-Review

**Spec coverage:** Each audit root cause maps to a task (1→FontManager, 2→logo caps, 3→error pattern, 4→soccer dict, 5→op queue, 6→byte-blind cache, 7→Vegas copy, 8→O(n) hot paths). Trend-to-uptime + instrumentation → Tasks 9-11. Verification → Task 12. ✓

**Placeholder scan:** Tasks 5 and 7 explicitly flag that the implementer must read the real API (op-queue enqueue/execute; adapter cache attr names) before finalizing the test — these are directed verifications, not vague placeholders. Task 2's `basketball_helpers.py` write site is called out for inspection rather than assumed. All code steps show concrete code or cite exact in-repo source to copy.

**Type consistency:** `_cache_logo(key, value)` signature matches the canonical source copied. `MemoryHistory.sample(now, mem_percent)` / `.snapshot()` keys (`samples`, `t`, `mem`, `started_at`) are consistent across Task 9 producer, Task 11 consumer. `display_controller_stats` keys (`rss_mb`, `mem_cache_entries`) match between Task 10 publisher and reader. `_MAX_MEMORY_VALUE_BYTES` consistent across Task 6.

**Risk notes:** Task 6 (cache) is the highest-risk — it changes what gets held in memory; the existing cache tests must stay green (Step 5 runs them). Tasks 1-5, 8 are low-risk source-local caps. Task 7 changes a hot Vegas path — run the vegas tests. The trend tasks (9-11) are additive.
