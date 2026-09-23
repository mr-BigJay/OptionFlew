from __future__ import annotations

from optionflow.patterns.dedupe import backtest_dedupe_key
from optionflow.patterns.ema50 import detect_ema50
from optionflow.patterns.types import PatternHit


def _trendline_hit(**meta) -> PatternHit:
    base = {
        "kind": "trendline",
        "stage": "confirmed",
        "side": "high",
        "window_offset": 1000,
        "touch_highs": [12, 40, 88],
        "touch_lows": [],
        "y_now": 91_854.0,
    }
    base.update(meta)
    return PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_high_confirmed",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=base,
    )


def test_same_line_same_key_despite_stage() -> None:
    a = _trendline_hit(stage="early", pattern_id="trendline_high_early")
    b = _trendline_hit(stage="confirmed", pattern_id="trendline_high_confirmed")
    assert backtest_dedupe_key(a) == backtest_dedupe_key(b)


def test_sliding_window_quantizes_touch_buckets() -> None:
    a = _trendline_hit(window_offset=1000, touch_highs=[12, 40, 88])
    b = _trendline_hit(window_offset=1006, touch_highs=[6, 34, 82])
    assert backtest_dedupe_key(a) == backtest_dedupe_key(b)


def test_different_lines_different_keys() -> None:
    a = _trendline_hit(touch_highs=[12, 40, 88])
    b = _trendline_hit(touch_highs=[12, 40, 200])
    assert backtest_dedupe_key(a) != backtest_dedupe_key(b)


def test_ema50_same_key_despite_stage_and_entry_px() -> None:
    from optionflow.patterns.test_ema50 import _flat_away_above

    early = detect_ema50(_flat_away_above(wick=False), "15m")
    confirmed = detect_ema50(_flat_away_above(wick=True), "15m")
    assert early and confirmed
    assert backtest_dedupe_key(early) == backtest_dedupe_key(confirmed)
    confirmed.meta["entry_px"] = float(confirmed.meta["entry_px"]) + 25
    assert backtest_dedupe_key(early) == backtest_dedupe_key(confirmed)
