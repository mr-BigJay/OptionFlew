from optionflow.patterns.chart import _global_bar_idx, render_pattern_chart
from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit
from optionflow.patterns.trendline import evaluate_trendline_path


def test_global_bar_idx_after_backtest_shift() -> None:
    meta = {"window_offset": 680}
    assert _global_bar_idx(meta, 20, 900) == 700
    meta_shifted = {"window_offset": 680}
    assert _global_bar_idx(meta_shifted, 700, 900) == 700


def test_trendline_chart_png_after_shifted_meta() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(200, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        from optionflow.patterns.ohlc import OhlcBar

        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 150, slope * 150 + intercept + 80)
    hit = _support_hit(early=130, slope=slope, intercept=intercept)
    hit.meta["window_offset"] = 80
    hit.meta["start_i"] = 100
    hit.meta["end_i"] = 150
    hit.meta["confirm_index"] = 150
    hit.meta["touch_lows"] = [100, 120, 150]
    evaluate_trendline_path(bars, 150, hit)
    png = render_pattern_chart(bars, hit, signal_index=150, forward_bars=24)
    assert png is not None
    assert len(png) > 5000
