from optionflow.patterns.chart import _structure_global, render_pattern_chart
from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit
from optionflow.patterns.trendline import evaluate_trendline_path


def test_structure_idx_is_window_plus_offset() -> None:
    meta = {"window_offset": 680}
    assert _structure_global(meta, 20, 900) == 700


def test_trendline_chart_png_keeps_price_scale() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(200, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        from optionflow.patterns.ohlc import OhlcBar

        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 150, slope * 70 + intercept + 80)
    hit = _support_hit(early=130, slope=slope, intercept=intercept)
    hit.meta["window_offset"] = 80
    hit.meta["start_i"] = 20
    hit.meta["end_i"] = 70
    hit.meta["confirm_index"] = 150
    hit.meta["early_index"] = 130
    hit.meta["touch_lows"] = [20, 40, 70]
    evaluate_trendline_path(bars, 150, hit)
    png = render_pattern_chart(bars, hit, signal_index=150, forward_bars=24)
    assert png is not None
    assert len(png) > 5000
