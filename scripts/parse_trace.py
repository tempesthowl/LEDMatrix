"""Measure stock-ticker fetch-stall duration from a /api/v3/diagnostics/trace dump.

The trace endpoint emits frame_commit/snapshot events every ~1s while a plugin is
displaying. When the vegas prefetch goes off to rebuild stock-ticker's tile list,
frame_commit stops firing for the duration of that rebuild — then a fetch/ok event
fires when the rebuild finishes. The stall duration = gap between the last
frame_commit before fetch/ok and the fetch/ok itself.

Usage:
    python scripts/parse_trace.py pre-fix-trace.json post-fix-trace.json
"""

import json
import sys
from typing import Iterable


def measure(path: str) -> None:
    with open(path) as f:
        d = json.load(f)
    traces = d.get("data", {}).get("traces", [])
    if not traces:
        print(f"{path}: no traces")
        return

    found = 0
    for trace_i, t in enumerate(traces):
        evs = t.get("events", [])
        for i, e in enumerate(evs):
            if not (
                e.get("layer") == "fetch"
                and e.get("event") == "ok"
                and e.get("plugin_id") == "stock-ticker"
            ):
                continue
            # Walk backwards for the most recent frame_commit
            last_commit_ts = None
            for j in range(i - 1, -1, -1):
                prev = evs[j]
                if prev.get("layer") == "frame_commit" and prev.get("event") == "snapshot":
                    last_commit_ts = prev.get("ts")
                    break
            if last_commit_ts is None:
                print(f"{path}: trace[{trace_i}] fetch/ok found but no preceding frame_commit")
                continue
            stall_ms = (e["ts"] - last_commit_ts) * 1000
            images = e.get("images", "?")
            width = e.get("total_width", "?")
            print(f"{path}: trace[{trace_i}] stock-ticker fetch stall = {stall_ms:7.0f}ms  ({images} images, {width}px)")
            found += 1
    if not found:
        print(f"{path}: no stock-ticker fetch/ok events found")


def main(argv: Iterable[str]) -> int:
    paths = list(argv)
    if not paths:
        print(__doc__)
        return 1
    for p in paths:
        measure(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
