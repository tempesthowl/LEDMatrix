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
