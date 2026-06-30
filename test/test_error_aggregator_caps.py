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
