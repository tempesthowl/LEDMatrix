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


@pytest.mark.parametrize("mod_name,rel", [
    ("fb_sports_cap", "plugin-repos/football-scoreboard/sports.py"),
    ("bb_sports_cap", "plugin-repos/basketball-scoreboard/sports.py"),
    ("sc_sports_cap", "plugin-repos/soccer-scoreboard/sports.py"),
])
def test_cache_logo_evicts_over_cap(mod_name, rel):
    mod = _load(mod_name, rel)
    # Find the class that defines _cache_logo (the SportsCore-like base in the copy).
    cls = next(v for v in vars(mod).values()
               if isinstance(v, type) and hasattr(v, "_cache_logo"))
    # SportsCore is abstract — create a minimal concrete subclass so Python 3.13+
    # allows instantiation without invoking __init__ (which needs heavy deps).
    class _Concrete(cls):
        def _extract_game_details(self, *a, **kw): pass
        def _fetch_data(self, *a, **kw): pass

    inst = object.__new__(_Concrete)
    inst._logo_cache = {}
    inst._logo_cache_order = []
    inst._logo_cache_max = 4  # small for the test
    img = Image.new("RGBA", (4, 4))
    for i in range(10):
        inst._cache_logo(f"TEAM{i}", img)
    assert len(inst._logo_cache) <= 4
    assert len(inst._logo_cache_order) <= 4


def test_basketball_helpers_cache_logo_evicts_over_cap():
    """Test that BasketballHelpers._cache_logo caps at 256 entries."""
    mod = _load("bb_helpers", "plugin-repos/basketball-scoreboard/basketball_helpers.py")
    cls = mod.BasketballHelpers

    # Create an instance using __new__ to bypass __init__ heavy deps
    inst = object.__new__(cls)
    inst._logo_cache = {}
    inst._logo_cache_order = []
    inst._logo_cache_max = 4  # small for the test
    img = Image.new("RGBA", (4, 4))
    for i in range(10):
        inst._cache_logo(f"TEAM{i}", img)
    assert len(inst._logo_cache) <= 4
    assert len(inst._logo_cache_order) <= 4
