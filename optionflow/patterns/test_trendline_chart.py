from __future__ import annotations

from optionflow.patterns.chart import _visible_price_range, render_pattern_chart
from optionflow.patterns.trendline import evaluate_trendline_path
from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit


def test_visible_price_range_ignores_corrupt_global_start_i() -> None:
    """اگر start_i اشتباهی global شده باشد، Y خط نباید محور را منفجر کند."""
    from optionflow.patterns.types import PatternHit

    bars = _empty(150, 90_000)
    hit = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_high_confirmed",
        title_fa="x",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={
            "start_i": 90_000,
            "end_i": 90_050,
            "window_offset": 0,
            "upper_slope": -1.0,
            "upper_intercept": 180_000_000.0,
            "lower_slope": None,
            "lower_intercept": None,
            "touch_highs": [10, 30, 60],
            "touch_lows": [],
        },
    )
    lo, hi = _visible_price_range(bars, hit, 0, 120)
    assert lo > 80_000
    assert hi < 110_000


def test_trendline_chart_png_and_sane_bounds() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(110, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        from optionflow.patterns.ohlc import OhlcBar

        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, slope * 40 + intercept + 80)
    _set_close(bars, 92, 99_800)
    _set_close(bars, 93, 99_800)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    ok, _ = evaluate_trendline_path(bars, 70, hit, timeframe="15m")
    assert ok is True
    png = render_pattern_chart(
        bars,
        hit,
        signal_index=hit.meta["entry_index"],
        forward_bars=12,
        outcome_success=ok,
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    lo, hi = _visible_price_range(bars, hit, 0, len(bars))
    assert hi - lo < 20_000


def test_trendline_chart_xlim_when_start_i_stored_as_global() -> None:
    """بکتست/متای قدیمی: start_i گاهی اندیس سراسری بود — PNG نباید محور X را منفجر کند."""
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    from optionflow.patterns.chart import render_pattern_chart
    from optionflow.patterns.ohlc import OhlcBar

    bars = _empty(5000, 100_000)
    wo = 4880
    for i, b in enumerate(bars):
        y = 100_000 - 2 * i
        bars[i] = OhlcBar(b.ts, y + 100, y + 200, y - 50, y + 100, 1.0)
    hit = _support_hit(early=40, slope=-2.0, intercept=200_000.0)
    hit.meta["window_offset"] = wo
    hit.meta["start_i"] = wo + 8
    hit.meta["end_i"] = wo + 119
    hit.meta["early_index"] = wo + 58
    hit.meta["confirm_index"] = wo + 106
    ok, _ = evaluate_trendline_path(bars, wo + 110, hit, timeframe="5m")
    sig = hit.meta["entry_index"]
    xlims: dict[str, tuple[float, float]] = {}
    orig_save = plt.Figure.savefig

    def grab(self, *args, **kwargs):
        xlims["v"] = self.axes[0].get_xlim()
        return orig_save(self, *args, **kwargs)

    plt.Figure.savefig = grab  # type: ignore[method-assign]
    try:
        png = render_pattern_chart(
            bars, hit, signal_index=sig, forward_bars=36, outcome_success=ok
        )
    finally:
        plt.Figure.savefig = orig_save  # type: ignore[method-assign]
    assert png is not None
    xl0, xl1 = xlims["v"]
    assert xl1 - xl0 < 5.0
    t0 = mdates.num2date(xl0)
    t1 = mdates.num2date(xl1)
    assert abs((t1 - t0).total_seconds()) < 5 * 86400
