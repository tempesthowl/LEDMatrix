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
