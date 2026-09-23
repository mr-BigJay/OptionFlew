from optionflow.patterns.chart_overlays import build_live_chart_payload, pattern_overlays
from optionflow.patterns.ohlc import OhlcBar
from datetime import datetime, timedelta, timezone


def _bar(i: int, c: float) -> OhlcBar:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OhlcBar(
        ts=t0 + timedelta(minutes=15 * i),
        open=c,
        high=c + 10,
        low=c - 10,
        close=c,
        volume=1.0,
    )


def test_divergence_overlay_has_segment() -> None:
    bars = [_bar(i, 100_000 + i * 10) for i in range(80)]
    meta = {
        "direction": "down",
        "pivot_a": (20, 100_400.0),
        "pivot_b": (50, 100_700.0),
        "confirm_index": 60,
        "entry_index": 61,
    }
    ov = pattern_overlays("divergence", meta, bars)
    assert len(ov["segments"]) == 1
    assert len(ov["markers"]) >= 2


def test_triangle_converging_lines() -> None:
    bars = [_bar(i, 84_400 + (i % 5) * 8) for i in range(80)]
    meta = {
        "upper_slope": -2.5,
        "upper_intercept": 84480.0,
        "lower_slope": 2.0,
        "lower_intercept": 84320.0,
        "start_i": 10,
        "end_i": 70,
        "window_offset": 0,
        "touch_highs": [20, 40, 55],
        "touch_lows": [15, 35, 50],
    }
    ov = pattern_overlays("triangle", meta, bars)
    assert len(ov["segments"]) == 2
    assert len(ov["markers"]) >= 4


def test_position_and_pattern_merge() -> None:
    bars = [_bar(i, 90_000 + i) for i in range(40)]
    pos = {
        "entry_price": 90100.0,
        "sl_price": 89500.0,
        "tp_price": 91000.0,
    }
    payload = build_live_chart_payload(
        timeframe="15m",
        bars=bars,
        category="ema50",
        meta={"entry_px": 90100, "sl_px": 89500, "ema_now": 90050},
        position=pos,
        mark=90200.0,
    )
    assert len(payload["candles"]) == 40
    assert len(payload["overlays"]["hlines"]) >= 4
