"""Expired content-cache entries must be swept on read-miss, not only on write."""
import time
import threading
from src.vegas_mode.plugin_adapter import PluginAdapter


def test_expired_entries_swept_on_read_miss(monkeypatch):
    """
    A plugin whose cache entry has expired must be evicted even when a DIFFERENT
    plugin triggers a cache read-miss.  Before the fix, _get_cached only swept
    on write (in _cache_content), so the stale entry survived indefinitely if its
    own plugin was never re-fetched.
    """
    pa = PluginAdapter.__new__(PluginAdapter)   # bypass heavy __init__
    pa._content_cache = {}
    pa._cache_lock = threading.Lock()
    pa._cache_ttl = 0.01  # 10 ms TTL

    # Seed a stale entry (expired 1 second ago)
    pa._content_cache["old"] = (time.time() - 1.0, ["x"])

    # Read-miss on a DIFFERENT key — the sweep must run during this call
    result = pa._get_cached("other")

    assert result is None, "read-miss should return None"
    assert "old" not in pa._content_cache, (
        "stale 'old' entry should have been swept during read-miss on 'other'"
    )


def test_cache_hit_still_works_after_fix():
    """Cache hits must still return correct content after the sweep change."""
    pa = PluginAdapter.__new__(PluginAdapter)
    pa._content_cache = {}
    pa._cache_lock = threading.Lock()
    pa._cache_ttl = 60.0  # long TTL — won't expire

    from PIL import Image
    img = Image.new("RGB", (64, 32), (0, 0, 0))
    pa._content_cache["active"] = (time.time(), [img])

    result = pa._get_cached("active")

    assert result is not None
    assert result[0] is img, "cache hit must return the same image object"


def test_cache_content_stores_without_copy():
    """
    _cache_content must store images directly (no copy), so the PIL
    objects it holds are the same objects that were passed in.
    Mutation finding: ScrollHelper.create_scrolling_image only reads (paste FROM),
    never writes TO the source images — so no copy is needed.
    """
    pa = PluginAdapter.__new__(PluginAdapter)
    pa._content_cache = {}
    pa._cache_lock = threading.Lock()
    pa._cache_ttl = 60.0

    from PIL import Image
    img = Image.new("RGB", (64, 32), (0, 0, 0))
    original_id = id(img)

    pa._cache_content("plugin_a", [img])

    _, cached_images = pa._content_cache["plugin_a"]
    assert id(cached_images[0]) == original_id, (
        "_cache_content should store the original image, not a copy"
    )
