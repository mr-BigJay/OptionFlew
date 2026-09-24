from datetime import datetime, timezone

from optionflow.patterns.chart import CHART_AFTER_RATIO, chart_window_end
from optionflow.patterns.types import PatternHit


def test_chart_window_end_triple_before() -> None:
    assert CHART_AFTER_RATIO == 3
    n, sig, start = 500, 200, 176
    end = chart_window_end(n, sig, start)
    before = sig - start
    assert end - 1 - sig == 3 * before


def test_visible_price_range_uses_slice_not_outliers() -> None:
    from optionflow.patterns.chart import _visible_price_range
    from optionflow.patterns.ohlc import OhlcBar

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OhlcBar(t0, 84_000, 84_050, 83_950, 84_010, 1.0) for _ in range(80)
    ]
    bars[40] = OhlcBar(t0, 84_000, 84_100, 83_900, 84_050, 1.0)
    hit = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_confirmed",
        title_fa="ترندلاین حمایت",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={
            "window_offset": 0,
            "start_i": 10,
            "end_i": 70,
            "lower_slope": 2.0,
            "lower_intercept": 83_800.0,
            "upper_slope": None,
            "upper_intercept": None,
            "touch_lows": [10, 30, 50],
            "touch_highs": [],
        },
    )
    lo, hi = _visible_price_range(bars, hit, 0, 80)
    assert lo < 84_200
    assert hi < 84_500
    assert hi - lo < 500


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
