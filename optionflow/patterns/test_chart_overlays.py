from datetime import datetime, timedelta, timezone

from optionflow.patterns.chart_overlays import (
    bar_unix,
    build_live_chart_payload,
    pattern_overlays,
    reanchor_meta,
    triangle_viewport,
)
from optionflow.patterns.ohlc import OhlcBar


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


def test_reanchor_preserves_triangle_local_indices() -> None:
    bars = [_bar(i, 84_400.0) for i in range(100)]
    meta = {
        "window_offset": 20,
        "start_i": 10,
        "end_i": 70,
        "confirm_index": 90,
        "touch_highs": [25, 45, 60],
    }
    ts = bars[85].ts.isoformat().replace("+00:00", "Z")
    m2 = reanchor_meta(bars, dict(meta), created_at=ts, category="triangle")
    assert m2["start_i"] == 10
    assert m2["end_i"] == 70
    assert m2["touch_highs"] == [25, 45, 60]
    assert m2["confirm_index"] == 85
    assert m2["window_offset"] == 15


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
    assert len(ov["markers"]) == 0
    up, lo = ov["segments"][0], ov["segments"][1]
    assert up["width"] == 1 and lo["width"] == 1
    assert up["t1"] == lo["t1"]
    assert abs(up["p1"] - lo["p1"]) < 0.01
    vp = triangle_viewport(meta, bars)
    assert vp is not None
    payload = build_live_chart_payload(
        timeframe="15m",
        bars=bars,
        category="triangle",
        meta=meta,
    )
    assert len(payload["candles"]) >= 55
    pvp = payload.get("viewport")
    assert pvp is not None
    assert pvp.get("fitTime") == 1
    assert pvp.get("priceMin") is not None


def test_trendline_line_on_touch_lows_no_touch_markers() -> None:
    wo = 30
    slope, intercept = 6.0, 81_000.0
    touch_lows = [18, 38, 55]
    bars = [_bar(i, 84_000.0) for i in range(100)]
    for ti in touch_lows:
        gi = wo + ti
        y = slope * ti + intercept
        b = bars[gi]
        bars[gi] = OhlcBar(
            ts=b.ts,
            open=y + 30,
            high=y + 80,
            low=y,
            close=y + 40,
            volume=1.0,
        )
    meta = {
        "kind": "trendline",
        "side": "low",
        "lower_slope": slope,
        "lower_intercept": intercept,
        "upper_slope": None,
        "upper_intercept": None,
        "window_offset": wo,
        "start_i": 15,
        "end_i": 58,
        "touch_lows": touch_lows,
        "touch_highs": [],
        "confirm_index": wo + touch_lows[-1],
    }
    ov = pattern_overlays("trendline", meta, bars)
    assert len(ov["lines"]) == 1
    assert all(m.get("text") not in ("▲", "▼") for m in ov["markers"])
    pts = ov["lines"][0]["points"]
    for ti in touch_lows:
        gi = wo + ti
        t = bar_unix(bars[gi])
        val = next(p["value"] for p in pts if p["time"] == t)
        assert abs(val - bars[gi].low) < 0.01


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
