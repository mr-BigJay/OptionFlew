from datetime import datetime, timezone

from optionflow.patterns.chart import CHART_AFTER_RATIO, chart_window_end
from optionflow.patterns.types import PatternHit


def test_chart_window_end_triple_before() -> None:
    assert CHART_AFTER_RATIO == 3
    n, sig, start = 500, 200, 176
    end = chart_window_end(n, sig, start)
    before = sig - start
    assert end - 1 - sig == 3 * before


def test_slice_range_flag_uses_triple() -> None:
    from optionflow.patterns.chart import _slice_range
    from optionflow.patterns.ohlc import OhlcBar

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OhlcBar(t0, 100, 101, 99, 100, 1.0) for _ in range(500)
    ]
    hit = PatternHit(
        category="flag",
        timeframe="15m",
        pattern_id="x",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"pole_start": 100, "direction": "up"},
    )
    sig = 180
    start, end, _ = _slice_range(bars, hit, sig, forward_bars=0)
    before = sig - start
    assert end - 1 - sig == 3 * before
