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
    bars.append(
        OhlcBar(t0 + timedelta(minutes=15), o, h, l, c, 1.0)
    )


def _uptrend_then_long(break_high: bool) -> list[OhlcBar]:
    closes = [100_000.0 + 40.0 * i for i in range(80)]
    bars = _bars_from_closes(closes)
    e = ema(closes, 50)[-1]
    assert e is not None
    last = closes[-1]
    # نزدیک شدن تدریجی به EMA بدون کف‌سازی
    for k in range(1, 5):
        px = last + (e + 40 - last) * k / 4
        _append(bars, bars[-1].close, px + 20, px - 20, px)
    floor = e - 10
    # کف سوئینگ: کمترین low
    _append(bars, bars[-1].close, floor + 50, floor - 15, floor + 15)
    _append(bars, floor + 15, floor + 45, floor + 5, floor + 25)
    _append(bars, floor + 25, floor + 50, floor + 10, floor + 35)
    # کندل تأیید صعودی
    _append(bars, floor + 35, floor + 160, floor + 20, floor + 150)
    if break_high:
        _append(bars, floor + 150, floor + 280, floor + 140, floor + 250)
    return bars


def _downtrend_then_short(break_low: bool) -> list[OhlcBar]:
    closes = [108_000.0 - 40.0 * i for i in range(80)]
    bars = _bars_from_closes(closes)
    e = ema(closes, 50)[-1]
    assert e is not None
    last = closes[-1]
    for k in range(1, 5):
        px = last + (e - 40 - last) * k / 4
        _append(bars, bars[-1].close, px + 20, px - 20, px)
    ceil = e + 10
    _append(bars, bars[-1].close, ceil + 15, ceil - 50, ceil - 15)
    _append(bars, ceil - 15, ceil - 5, ceil - 45, ceil - 25)
    _append(bars, ceil - 25, ceil - 10, ceil - 50, ceil - 35)
    _append(bars, ceil - 35, ceil - 20, ceil - 160, ceil - 150)
    if break_low:
        _append(bars, ceil - 150, ceil - 140, ceil - 280, ceil - 250)
    return bars


def test_tv_ema_seeds_with_sma() -> None:
    vals = [float(i) for i in range(1, 8)]
    out = ema(vals, 3)
    assert out[0] is None and out[1] is None
    assert out[2] is not None and abs(out[2] - 2.0) < 1e-9
    assert out[3] is not None and abs(out[3] - 3.0) < 1e-9


def test_long_early_then_confirmed() -> None:
    early_bars = _uptrend_then_long(break_high=False)
    early = detect_ema50(early_bars, "15m")
    assert early is not None
    assert early.meta["direction"] == "up"
    assert early.meta["stage"] == "early"
    assert "اولیه" in early.status_fa
    assert detect_ema50(early_bars, "15m", allow_early=False) is None

    conf_bars = _uptrend_then_long(break_high=True)
    hit = detect_ema50(conf_bars, "15m")
    assert hit is not None
    assert hit.category == "ema50"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["direction"] == "up"
    assert hit.meta["entry_px"] > hit.meta["sl_px"]
    assert hit.meta["tp_px"] > hit.meta["entry_px"]


def test_short_confirmed() -> None:
    bars = _downtrend_then_short(break_low=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    assert hit.meta["direction"] == "down"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["sl_px"] > hit.meta["entry_px"]


def test_flat_chop_is_ignored() -> None:
    closes = []
    px = 100_000.0
    for i in range(90):
        px = 100_000.0 + (80 if i % 2 == 0 else -80)
        closes.append(px)
    assert detect_ema50(_bars_from_closes(closes), "15m") is None


def test_ema50_tp_is_success() -> None:
    bars = _uptrend_then_long(break_high=True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    idx = len(bars) - 1
    entry = hit.meta["entry_px"]
    tp = hit.meta["tp_px"]
    t0 = bars[-1].ts
    extra = []
    for k in range(1, 6):
        extra.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=15 * k),
                open=entry,
                high=tp + 20 if k == 3 else entry + 40,
                low=entry - 20,
                close=entry + 30,
                volume=1.0,
            )
        )
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is True
    assert hit.meta["path_pct"] > 0
    assert "۱:۲" in note


def test_ema50_sl_is_fail() -> None:
    bars = _uptrend_then_long(break_high=True)
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
            high=entry + 10,
            low=sl - 15,
            close=sl,
            volume=1.0,
        )
    ]
    ok, note = evaluate_ema50_path(bars + extra, idx, hit)
    assert ok is False
    assert "حد ضرر" in note


def _mild_stretch_short(*, confirm: bool, broken: bool) -> list[OhlcBar]:
    closes = [100_000.0 + 10.0 * i for i in range(80)]
    bars = _bars_from_closes(closes)
    e = ema([b.close for b in bars], 50)[-1]
    assert e is not None
    px = e + 200
    for _ in range(4):
        _append(bars, px - 15, px + 35, px - 25, px)
        px += 25
    if confirm:
        _append(bars, px, px + 12, px - 90, px - 80)
    if broken:
        _append(bars, px - 80, px - 70, px - 170, px - 150)
    return bars


def _mild_stretch_long(*, confirm: bool, broken: bool) -> list[OhlcBar]:
    closes = [100_000.0 + 10.0 * i for i in range(80)]
    bars = _bars_from_closes(closes)
    e = ema([b.close for b in bars], 50)[-1]
    assert e is not None
    px = e - 200
    for _ in range(4):
        _append(bars, px + 15, px + 25, px - 35, px)
        px -= 25
    if confirm:
        _append(bars, px, px + 90, px - 12, px + 80)
    if broken:
        _append(bars, px + 80, px + 170, px + 70, px + 150)
    return bars


def test_mild_slope_short_reverts_to_ema() -> None:
    early = detect_ema50(_mild_stretch_short(confirm=False, broken=False), "15m")
    assert early is not None
    assert early.meta["mode"] == "revert"
    assert early.meta["direction"] == "down"
    assert early.meta["stage"] == "early"
    assert "برگشت" in early.title_fa

    hit = detect_ema50(_mild_stretch_short(confirm=True, broken=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "revert"
    assert hit.meta["direction"] == "down"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["tp_px"] < hit.meta["entry_px"]


def test_mild_slope_long_reverts_to_ema() -> None:
    hit = detect_ema50(_mild_stretch_long(confirm=True, broken=True), "15m")
    assert hit is not None
    assert hit.meta["mode"] == "revert"
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["tp_px"] > hit.meta["entry_px"]


def test_ema50_chart_renders() -> None:
    from optionflow.patterns.chart import render_pattern_chart

    bars = _uptrend_then_long(True)
    hit = detect_ema50(bars, "15m")
    assert hit is not None
    png = render_pattern_chart(bars, hit)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ema50_slice_after_is_double_before() -> None:
    from optionflow.patterns.chart import _slice_range

    base = _uptrend_then_long(True)
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
