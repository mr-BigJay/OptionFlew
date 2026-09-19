from datetime import datetime, timedelta, timezone

from optionflow.patterns.ema50 import detect_ema50, evaluate_ema50_path
from optionflow.patterns.indicators import ema
from optionflow.patterns.ohlc import OhlcBar


def _bars_from_closes(closes: list[float], minutes: int = 15) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[OhlcBar] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        hi = max(o, c) + 4
        lo = min(o, c) - 4
        out.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=minutes * i),
                open=o,
                high=hi,
                low=lo,
                close=c,
                volume=1.0,
            )
        )
        prev = c
    return out


def _append(bars: list[OhlcBar], o: float, h: float, l: float, c: float) -> None:
    t0 = bars[-1].ts
    bars.append(OhlcBar(t0 + timedelta(minutes=15), o, h, l, c, 1.0))


def _ema_now(bars: list[OhlcBar]) -> float:
    e = ema([b.close for b in bars], 50)[-1]
    assert e is not None
    return e


def _flat_away_above(*, wick: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([100_000.0 + 8.0 * i for i in range(80)])
    last = bars[-1].close
    if wick:
        # ویک بالا > بادی
        _append(bars, last + 10, last + 90, last + 2, last + 18)
    return bars


def _flat_away_below(*, wick: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([108_000.0 - 8.0 * i for i in range(80)])
    last = bars[-1].close
    if wick:
        _append(bars, last - 10, last - 2, last - 90, last - 18)
    return bars


def _steep_trend_long(*, bullish: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([100_000.0 + 140.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 4):
        px = last + (e + 20 - last) * k / 3
        _append(bars, bars[-1].close, px + 8, px - 8, px)
    e2 = _ema_now(bars)
    if bullish:
        _append(bars, e2 + 10, e2 + 70, e2 + 4, e2 + 55)
    else:
        _append(bars, e2 + 50, e2 + 58, e2 + 20, e2 + 28)
    return bars


def _steep_trend_short(*, bearish: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([112_000.0 - 140.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 4):
        px = last + (e - 20 - last) * k / 3
        _append(bars, bars[-1].close, px + 8, px - 8, px)
    e2 = _ema_now(bars)
    if bearish:
        _append(bars, e2 - 10, e2 - 4, e2 - 70, e2 - 55)
    else:
        _append(bars, e2 - 50, e2 - 20, e2 - 58, e2 - 28)
    return bars


def test_tv_ema_seeds_with_sma() -> None:
    vals = [float(i) for i in range(1, 8)]
    out = ema(vals, 3)
    assert out[0] is None and out[1] is None
    assert out[2] is not None and abs(out[2] - 2.0) < 1e-9
    assert out[3] is not None and abs(out[3] - 3.0) < 1e-9


def test_flat_stretch_short_early_then_wick_entry() -> None:
    early_bars = _flat_away_above(wick=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["mode"] == "flat"
    assert early.meta["direction"] == "down"
    assert early.meta["stage"] == "early"
    assert early.meta["exit_style"] == "ema_touch"
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    hit = detect_ema50(_flat_away_above(wick=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "flat"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["direction"] == "down"
    assert hit.meta["exit_style"] == "ema_touch"
    assert "فاصله" in hit.title_fa


def test_flat_stretch_long_wick_entry() -> None:
    hit = detect_ema50(_flat_away_below(wick=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "flat"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"


def test_steep_trend_long_early_then_confirmed() -> None:
    early_bars = _steep_trend_long(bullish=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["mode"] == "trend"
    assert early.meta["direction"] == "up"
    assert early.meta["stage"] == "early"
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    hit = detect_ema50(_steep_trend_long(bullish=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "trend"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["exit_style"] == "three_closes"
    assert "روند" in hit.title_fa


def test_steep_trend_short_confirmed() -> None:
    hit = detect_ema50(_steep_trend_short(bearish=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "trend"
    assert hit.meta["direction"] == "down"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["exit_style"] == "three_closes"


def test_flat_chop_is_ignored() -> None:
    closes = []
    for i in range(90):
        closes.append(100_000.0 + (80 if i % 2 == 0 else -80))
    assert detect_ema50(_bars_from_closes(closes), "15m") is None


def test_flat_exit_on_first_ema_touch() -> None:
    bars = _flat_away_above(wick=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    e = _ema_now(bars)
    extra = [
        OhlcBar(
            ts=bars[-1].ts + timedelta(minutes=15),
            open=hit.meta["entry_px"],
            high=hit.meta["entry_px"] + 20,
            low=e - 30,
            close=e + 10,
            volume=1.0,
        )
    ]
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is True
    assert "لمس" in note


def test_trend_exit_needs_three_closes_against() -> None:
    bars = _steep_trend_long(bullish=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    e = _ema_now(bars)
    t0 = bars[-1].ts
    one = [
        OhlcBar(
            ts=t0 + timedelta(minutes=15),
            open=hit.meta["entry_px"],
            high=hit.meta["entry_px"] + 10,
            low=e - 80,
            close=e - 40,
            volume=1.0,
        )
    ]
    ok_one, _ = evaluate_ema50_path(bars + one, idx, hit)
    assert ok_one is None

    extra = []
    for k in range(1, 4):
        extra.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=15 * k),
                open=e - 20,
                high=e - 10,
                low=e - 90,
                close=e - 40,
                volume=1.0,
            )
        )
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is False
    assert "سه کلوز" in note


def test_ema50_chart_renders() -> None:
    from optionflow.patterns.chart import render_pattern_chart

    bars = _flat_away_above(wick=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    png = render_pattern_chart(bars, hit)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ema50_slice_after_is_double_before() -> None:
    from optionflow.patterns.chart import _slice_range

    base = _flat_away_above(wick=True)
    hit = detect_ema50(base, "15m")
    assert hit is not None
    sig = hit.meta["entry_index"]
    assert isinstance(sig, int)
    bars = list(base)
    last = bars[-1].close
    for _ in range(120):
        _append(bars, last, last + 20, last - 20, last)
    start, end, _ = _slice_range(bars, hit, sig, 8)
    before = sig - start
    after = end - 1 - sig
    assert before > 0
    assert after == 2 * before
