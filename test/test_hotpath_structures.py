"""
Tests for O(1) hot-path data structures:
- ScrollHelper.frame_times → deque(maxlen=100)
- ErrorAggregator._records → deque(maxlen=max_records)
- LogoHelper LRU → OrderedDict with move_to_end-on-hit semantics
"""
import time
from collections import OrderedDict, deque

from src.common.scroll_helper import ScrollHelper
from src.error_aggregator import ErrorAggregator


# ---------------------------------------------------------------------------
# ScrollHelper: frame_times must be a bounded deque
# ---------------------------------------------------------------------------

def test_frame_times_is_bounded_deque():
    sh = ScrollHelper.__new__(ScrollHelper)
    sh.frame_times = deque(maxlen=100)
    sh.last_frame_time = time.time() - 1.0  # ensure positive frame_time
    sh.last_fps_log_time = time.time()
    sh.frame_count = 0
    sh.logger = _make_silent_logger()
    for _ in range(500):
        sh.log_frame_rate()
    assert isinstance(sh.frame_times, deque)
    assert len(sh.frame_times) <= 100


def test_frame_times_auto_initialised_as_deque():
    """ScrollHelper.__init__ must set frame_times to a deque, not a list."""
    sh = _make_scroll_helper_with_mock_deps()
    assert isinstance(sh.frame_times, deque)
    assert sh.frame_times.maxlen == 100


# ---------------------------------------------------------------------------
# ErrorAggregator: _records must be a bounded deque
# ---------------------------------------------------------------------------

def test_records_is_deque():
    agg = ErrorAggregator(max_records=10)
    assert isinstance(agg._records, deque)
    assert agg._records.maxlen == 10


def test_records_bounded_by_max_records():
    agg = ErrorAggregator(max_records=10)
    for i in range(50):
        try:
            raise ValueError(f"err {i}")
        except ValueError as e:
            agg.record_error(e)
    assert len(agg._records) <= 10
    assert isinstance(agg._records, deque)


# ---------------------------------------------------------------------------
# LogoHelper: LRU uses OrderedDict with move_to_end-on-hit semantics
# ---------------------------------------------------------------------------

def test_logo_lru_evicts_lru_key():
    """Fill cache to capacity, then access one key — the OTHER should be evicted next."""
    from src.common.logo_helper import LogoHelper
    from PIL import Image

    helper = LogoHelper(display_width=64, display_height=32, cache_size=2)

    # Inject two fake logos directly into the OrderedDict cache (insert order = a, b)
    img_a = Image.new("RGBA", (10, 10))
    img_b = Image.new("RGBA", (10, 10))
    helper._logo_cache["key_a"] = img_a
    helper._logo_cache["key_b"] = img_b

    # Hit key_a — move to MRU end; now LRU is key_b
    helper._logo_cache.move_to_end("key_a")

    # Add a third entry which must evict the LRU (key_b)
    img_c = Image.new("RGBA", (10, 10))
    helper._cache_logo("key_c", img_c)

    assert "key_b" not in helper._logo_cache, "key_b (LRU) should have been evicted"
    assert "key_a" in helper._logo_cache, "key_a (recently used) must survive"
    assert "key_c" in helper._logo_cache, "key_c (just added) must be present"


def test_logo_cache_uses_ordered_dict():
    """After conversion _logo_cache must be an OrderedDict."""
    from src.common.logo_helper import LogoHelper
    helper = LogoHelper(display_width=64, display_height=32, cache_size=5)
    assert isinstance(helper._logo_cache, OrderedDict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent_logger():
    import logging
    logger = logging.getLogger("test_hotpath_silent")
    logger.addHandler(logging.NullHandler())
    return logger


def _make_scroll_helper_with_mock_deps():
    """Build a ScrollHelper via __init__ to verify it sets frame_times correctly."""
    sh = ScrollHelper(display_width=64, display_height=32)
    return sh
