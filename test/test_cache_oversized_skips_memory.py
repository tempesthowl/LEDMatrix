"""Oversized disk values must not be re-deposited into the in-memory cache."""
import os
import pytest
from src.cache_manager import CacheManager


def test_oversized_value_not_held_in_memory(tmp_path, monkeypatch):
    # Point cache at tmp_path so the test doesn't pollute the real cache dir.
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    cm = CacheManager()
    # Stop the background cleanup thread so it doesn't interfere.
    cm.stop_cleanup_thread()

    # Force a known small threshold for the test (1 KiB).
    monkeypatch.setattr(cm, "_MAX_MEMORY_VALUE_BYTES", 1024, raising=False)

    # Build a value that exceeds 1 KiB when serialised to JSON on disk.
    big = {"events": ["x" * 100 for _ in range(1000)]}  # ~100 KB on disk
    cm.save_cache("huge_key", big)

    # Fix 1 guard: save_cache itself must NOT pin the oversized value.
    assert "huge_key" not in cm._memory_cache, (
        "save_cache must NOT pin an oversized value in memory at write time"
    )

    # Evict from memory so the next read must come from disk.
    cm._memory_cache.clear()
    cm._memory_cache_timestamps.clear()

    got = cm.get_cached_data("huge_key", max_age=3600)
    assert got is not None, "oversized value must still be served (from disk)"
    assert "huge_key" not in cm._memory_cache, (
        "oversized value must NOT be pinned in the in-memory cache"
    )


def test_small_value_is_still_memory_cached(tmp_path, monkeypatch):
    """Regression: values under the threshold must still be cached in memory."""
    monkeypatch.setenv("LEDMATRIX_CACHE_DIR", str(tmp_path))
    cm = CacheManager()
    cm.stop_cleanup_thread()

    # Default 5 MiB threshold; a tiny value should always qualify.
    small = {"score": 42}
    cm.save_cache("small_key", small)

    # Evict from memory to force a disk read.
    cm._memory_cache.clear()
    cm._memory_cache_timestamps.clear()

    got = cm.get_cached_data("small_key", max_age=3600)
    assert got is not None, "small value must be served"
    assert "small_key" in cm._memory_cache, (
        "small value MUST be re-deposited into the in-memory cache"
    )
