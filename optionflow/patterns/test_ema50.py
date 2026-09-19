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
        hi = max(o, c) + 30
        lo = min(o, c) - 30
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


def _stretch_above(*, signal: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([100_000.0 + 8.0 * i for i in range(80)])
    last = bars[-1].close
    if signal:
        _append(bars, last + 5, last + 95, last - 12, last - 8)
    return bars


def _stretch_below(*, signal: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([108_000.0 - 8.0 * i for i in range(80)])
    last = bars[-1].close
    if signal:
        _append(bars, last - 5, last + 12, last - 95, last + 8)
    return bars


def _pierce_from_above(*, reject: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([100_000.0 + 8.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 5):
        px = last + (e + 55 - last) * k / 4
        _append(bars, bars[-1].close, px + 25, px - 12, px)
    e2 = _ema_now(bars)
    if reject:
        _append(bars, e2 + 45, e2 + 60, e2 - 80, e2 + 40)
    else:
        _append(bars, e2 + 40, e2 + 52, e2 - 8, e2 + 12)
    return bars


def _pierce_from_below(*, reject: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([108_000.0 - 8.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 5):
        px = last + (e - 55 - last) * k / 4
        _append(bars, bars[-1].close, px + 12, px - 25, px)
    e2 = _ema_now(bars)
    if reject:
        _append(bars, e2 - 45, e2 + 80, e2 - 60, e2 - 40)
    else:
        _append(bars, e2 - 40, e2 + 8, e2 - 52, e2 - 12)
    return bars


def _steep_trend_long(*, signal: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([100_000.0 + 140.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 4):
        px = last + (e + 25 - last) * k / 3
        _append(bars, bars[-1].close, max(bars[-1].close, px) + 18, min(bars[-1].close, px) - 18, px)
    e2 = _ema_now(bars)
    if signal:
        _append(bars, e2 + 35, e2 + 70, e2 - 90, e2 + 50)
    else:
        _append(bars, e2 + 30, e2 + 55, e2 + 18, e2 + 48)
    return bars


def _steep_trend_short(*, signal: bool) -> list[OhlcBar]:
    bars = _bars_from_closes([112_000.0 - 140.0 * i for i in range(80)])
    e = _ema_now(bars)
    last = bars[-1].close
    for k in range(1, 4):
        px = last + (e - 25 - last) * k / 3
        _append(bars, bars[-1].close, max(bars[-1].close, px) + 18, min(bars[-1].close, px) - 18, px)
    e2 = _ema_now(bars)
    if signal:
        _append(bars, e2 - 35, e2 + 90, e2 - 70, e2 - 50)
    else:
        _append(bars, e2 - 30, e2 - 8, e2 - 48, e2 - 40)
    return bars


def test_tv_ema_seeds_with_sma() -> None:
    vals = [float(i) for i in range(1, 8)]
    out = ema(vals, 3)
    assert out[0] is None and out[1] is None
    assert out[2] is not None and abs(out[2] - 2.0) < 1e-9
    assert out[3] is not None and abs(out[3] - 3.0) < 1e-9


def test_stretch_fade_short_early_then_confirmed() -> None:
    early_bars = _stretch_above(signal=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["mode"] == "stretch_fade"
    assert early.meta["direction"] == "down"
    assert early.meta["stage"] == "early"
    assert early.meta["exit_style"] == "ema_touch"
    assert "اولیه" in early.status_fa
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    hit = detect_ema50(_stretch_above(signal=True), "15m")
    assert hit is not None
    assert hit.category == "ema50"
    assert hit.meta["mode"] == "stretch_fade"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["direction"] == "down"
    assert hit.meta["exit_style"] == "ema_touch"
    assert "فاصله" in hit.title_fa
    assert hit.meta["sl_px"] > hit.meta["entry_px"]


def test_stretch_fade_long_confirmed() -> None:
    hit = detect_ema50(_stretch_below(signal=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "stretch_fade"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["entry_px"] > hit.meta["sl_px"]


def test_pierce_reject_long_early_then_confirmed() -> None:
    early_bars = _pierce_from_above(reject=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["mode"] == "pierce_reject"
    assert early.meta["direction"] == "up"
    assert early.meta["stage"] == "early"
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    hit = detect_ema50(_pierce_from_above(reject=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "pierce_reject"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["exit_style"] == "stretch_away"
    assert "نفوذ" in hit.title_fa


def test_pierce_reject_short_confirmed() -> None:
    hit = detect_ema50(_pierce_from_below(reject=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "pierce_reject"
    assert hit.meta["direction"] == "down"
    assert hit.meta["stage"] == "confirmed"


def test_steep_trend_long_early_then_confirmed() -> None:
    early_bars = _steep_trend_long(signal=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["mode"] == "trend"
    assert early.meta["direction"] == "up"
    assert early.meta["stage"] == "early"
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    hit = detect_ema50(_steep_trend_long(signal=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "trend"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["exit_style"] == "ema_break"
    assert "روند" in hit.title_fa


def test_steep_trend_short_confirmed() -> None:
    hit = detect_ema50(_steep_trend_short(signal=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "trend"
    assert hit.meta["direction"] == "down"
    assert hit.meta["stage"] == "confirmed"


def test_flat_chop_is_ignored() -> None:
    closes = []
    px = 100_000.0
    for i in range(90):
        px = 100_000.0 + (80 if i % 2 == 0 else -80)
        closes.append(px)
    assert detect_ema50(_bars_from_closes(closes), "15m") is None


def test_stretch_fade_ema_touch_is_success() -> None:
    bars = _stretch_above(signal=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    assert hit.meta["exit_style"] == "ema_touch"
    idx = len(bars) - 1
    e = _ema_now(bars)
    t0 = bars[-1].ts
    extra = [
        OhlcBar(
            ts=t0 + timedelta(minutes=15),
            open=hit.meta["entry_px"],
            high=hit.meta["entry_px"] + 20,
            low=e - 30,
            close=e + 10,
            volume=1.0,
        )
    ]
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is True
    assert hit.meta["path_pct"] > 0
    assert "لمس" in note


def test_stretch_fade_sl_is_fail() -> None:
    bars = _stretch_above(signal=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    entry = hit.meta["entry_px"]
    sl = hit.meta["sl_px"]
    t0 = bars[-1].ts
    extra = [
        OhlcBar(
            ts=t0 + timedelta(minutes=15),
            open=entry,
            high=sl + 20,
            low=entry - 10,
            close=sl,
            volume=1.0,
        )
    ]
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is False
    assert "حد ضرر" in note


def test_pierce_reject_stretch_away_is_success() -> None:
    bars = _pierce_from_above(reject=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    e = _ema_now(bars)
    t0 = bars[-1].ts
    extra = []
    px = e + 80
    for k in range(1, 6):
        px += 40
        extra.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=15 * k),
                open=px - 10,
                high=px + 25,
                low=px - 20,
                close=px,
                volume=1.0,
            )
        )
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is True
    assert "فاصله" in note


def test_trend_ema_break_closes_trade() -> None:
    bars = _steep_trend_long(signal=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    e = _ema_now(bars)
    t0 = bars[-1].ts
    extra = [
        OhlcBar(
            ts=t0 + timedelta(minutes=15),
            open=hit.meta["entry_px"],
            high=hit.meta["entry_px"] + 10,
            low=e - 80,
            close=e - 40,
            volume=1.0,
        )
    ]
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is False
    assert "شکست" in note


def test_ema50_chart_renders() -> None:
    from optionflow.patterns.chart import render_pattern_chart

    bars = _stretch_above(signal=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    png = render_pattern_chart(bars, hit)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ema50_slice_after_is_double_before() -> None:
    from optionflow.patterns.chart import _slice_range

    base = _stretch_above(signal=True)
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
