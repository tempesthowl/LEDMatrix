"""End-to-end auto-verify for the stock-ticker per-tile Vegas cache.

Drives `/api/v3/plugins/toggle/batch` to cycle stock-ticker OFF/ON N times,
captures `/api/v3/diagnostics/trace` before and after, and reports the
stock-ticker fetch-stall delta using the same metric as parse_trace.py.

Usage:
    # Standard run against the Pi (default 2 cycles, 60s prefetch settle)
    python scripts/verify_stock_ticker_cache.py

    # Against the emulator
    python scripts/verify_stock_ticker_cache.py --host localhost

    # More cycles, shorter settle
    python scripts/verify_stock_ticker_cache.py --cycles 3 --settle 45

    # Reuse an existing pre-fix trace instead of re-capturing
    python scripts/verify_stock_ticker_cache.py --pre-trace C:/Users/ericv/pre-fix-trace.json

Notes:
- Does NOT touch the Pi via SSH. Eric runs the deploy himself
  (`ssh -t vallejofish@ledticker.local 'cd ~/LEDMatrix && git pull && sudo systemctl restart ledmatrix'`).
- Reuses parse_trace.measure() so the metric stays consistent.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
import parse_trace  # noqa: E402


def _http(host: str, port: int, path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    url = f"http://{host}:{port}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def capture_trace(host: str, port: int, out_path: Path, limit: int = 10) -> None:
    print(f"  -> GET /api/v3/diagnostics/trace?limit={limit}")
    d = _http(host, port, f"/api/v3/diagnostics/trace?limit={limit}", timeout=10)
    out_path.write_text(json.dumps(d, indent=2))
    print(f"  -> wrote {out_path} ({out_path.stat().st_size} bytes)")


def toggle(host: str, port: int, plugin_id: str, enabled: bool) -> None:
    body = {"changes": [{"plugin_id": plugin_id, "enabled": enabled}]}
    resp = _http(host, port, "/api/v3/plugins/toggle/batch", body=body, timeout=15)
    status = resp.get("status", "?")
    applied = resp.get("applied") or resp.get("data", {}).get("applied")
    print(f"  -> POST toggle/batch {plugin_id}={enabled} status={status} applied={applied}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="ledticker.local", help="Pi host (default ledticker.local)")
    p.add_argument("--port", type=int, default=5000, help="web UI port (default 5000)")
    p.add_argument("--plugin", default="stock-ticker", help="plugin to toggle")
    p.add_argument("--cycles", type=int, default=2, help="off/on cycles (default 2)")
    p.add_argument("--settle", type=float, default=60.0, help="seconds to wait after each ON for prefetch (default 60)")
    p.add_argument("--off-pause", type=float, default=5.0, help="seconds to pause after OFF before ON (default 5)")
    p.add_argument("--pre-trace", type=Path, default=None, help="reuse this file as pre-fix trace, skip pre-capture")
    p.add_argument("--out-dir", type=Path, default=Path.cwd(), help="where to write traces (default cwd)")
    p.add_argument("--limit", type=int, default=10, help="trace endpoint ?limit= (default 10)")
    args = p.parse_args(argv)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_path = args.pre_trace or (out_dir / "pre-fix-trace.json")
    post_path = out_dir / "post-fix-trace.json"

    print(f"Target: http://{args.host}:{args.port}  plugin={args.plugin}  cycles={args.cycles}  settle={args.settle}s")
    print()

    # --- Pre-capture (unless reusing) ---
    if args.pre_trace:
        if not args.pre_trace.exists():
            print(f"ERROR: --pre-trace {args.pre_trace} does not exist")
            return 1
        print(f"[1/3] Reusing pre-fix trace: {args.pre_trace}")
    else:
        print("[1/3] Capturing pre-fix trace (current Pi state)")
        capture_trace(args.host, args.port, pre_path, limit=args.limit)
    print()

    # --- Drive toggle cycles ---
    print(f"[2/3] Driving {args.cycles} toggle cycles")
    for i in range(args.cycles):
        print(f"  cycle {i + 1}/{args.cycles}")
        toggle(args.host, args.port, args.plugin, enabled=False)
        time.sleep(args.off_pause)
        toggle(args.host, args.port, args.plugin, enabled=True)
        print(f"  ... settling {args.settle}s for prefetch")
        time.sleep(args.settle)
    print()

    # --- Post-capture ---
    print("[3/3] Capturing post-fix trace")
    capture_trace(args.host, args.port, post_path, limit=args.limit)
    print()

    # --- Diff ---
    print("=" * 70)
    print("RESULT (stock-ticker fetch stall: gap between last frame_commit and fetch/ok)")
    print("=" * 70)
    parse_trace.measure(str(pre_path))
    parse_trace.measure(str(post_path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except urllib.error.URLError as e:
        print(f"\nERROR: HTTP request failed: {e}", file=sys.stderr)
        print("Is the Pi reachable? Try: curl.exe http://ledticker.local:5000/api/v3/health", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
