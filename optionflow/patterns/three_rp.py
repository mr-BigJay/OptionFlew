from __future__ import annotations

from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# LuxAlgo brpType — فقط Enhanced (Normal در Pine جدا فیلتر می‌شود)
DEFAULT_PATTERN_TYPE = "Enhanced"

# ورود روی کندل سوم بزرگ (دامنه ≥ ۱٪ close): تاچ ۵۰٪ high/low در ۸ کندل بعد
PULLBACK_WAIT_BARS = 8
LARGE_CANDLE_RANGE_PCT = 1.0

_TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def _bar_ts(bar: OhlcBar) -> datetime:
    ts = bar.ts
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _bar_is_forming(bar: OhlcBar, timeframe: str) -> bool:
    sec = _TF_SECONDS.get(timeframe, 3600)
    end = _bar_ts(bar) + timedelta(seconds=sec)
    return end > datetime.now(timezone.utc)


def last_closed_index(bars: list[OhlcBar], timeframe: str) -> int:
    i = len(bars) - 1
    while i >= 0 and _bar_is_forming(bars[i], timeframe):
        i -= 1
    return i


def _is_bullish_reversal(bars: list[OhlcBar], i: int) -> bool:
    if i < 2:
        return False
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
    return (
        b0.close < b0.open
        and b1.low < b0.low
        and b1.high < b0.high
        and b1.close < b1.open
        and b2.close > b2.open
        and b2.high > b0.high
    )


def _is_bearish_reversal(bars: list[OhlcBar], i: int) -> bool:
    if i < 2:
        return False
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
    return (
        b0.close > b0.open
        and b1.high > b0.high
        and b1.low > b0.low
        and b1.close > b1.open
        and b2.close < b2.open
        and b2.low < b0.low
    )


def _matches_pattern_type(
    *,
    bullish: bool,
    b0: OhlcBar,
    b2: OhlcBar,
    pattern_type: str,
) -> bool:
    pt = (pattern_type or DEFAULT_PATTERN_TYPE).strip()
    if pt == "All":
        return True
    if pt == "Enhanced":
        return b2.close > b0.high if bullish else b2.close < b0.low
    if pt == "Normal":
        return b2.close < b0.high if bullish else b2.close > b0.low
    return False


def _bull_support(b1: OhlcBar, b2: OhlcBar) -> float:
    return min(b1.low, b2.low)


def _bear_resistance(b1: OhlcBar, b2: OhlcBar) -> float:
    return max(b1.high, b2.high)


def _follow_bull(
    bars: list[OhlcBar], i: int, pattern_high: float, support: float
) -> tuple[str, int | None]:
    enhanced_at_detect = bars[i].close > pattern_high
    for j in range(i + 1, len(bars)):
        prev = bars[j - 1]
        if _is_bearish_reversal(bars, j) or prev.close < support:
            return "failed", None
        if prev.close > pattern_high:
            return "confirmed", j - 1
    if enhanced_at_detect:
        return "confirmed", i
    return "detected", None


def _follow_bear(
    bars: list[OhlcBar], i: int, pattern_low: float, resistance: float
) -> tuple[str, int | None]:
    enhanced_at_detect = bars[i].close < pattern_low
    for j in range(i + 1, len(bars)):
        prev = bars[j - 1]
        if _is_bullish_reversal(bars, j) or prev.close > resistance:
            return "failed", None
        if prev.close < pattern_low:
            return "confirmed", j - 1
    if enhanced_at_detect:
        return "confirmed", i
    return "detected", None


def _signal_ts_iso(bar: OhlcBar) -> str:
    return _bar_ts(bar).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def third_candle_range_pct(b2: OhlcBar) -> float:
    c = b2.close
    if c <= 0:
        return 0.0
    return (b2.high - b2.low) / c * 100.0


def third_candle_mid(b2: OhlcBar) -> float:
    return (b2.high + b2.low) / 2.0


def resolve_three_rp_entry(
    bars: list[OhlcBar],
    signal_index: int,
    *,
    direction: str,
    b2: OhlcBar,
    support: float,
    resistance: float,
) -> tuple[int, float, str] | None:
    """ورود: کوچک → close کندل سوم؛ بزرگ → تاچ ۵۰٪ در حداکثر ۸ کندل (OHLC)."""
    i = signal_index
    rng = third_candle_range_pct(b2)
    if rng < LARGE_CANDLE_RANGE_PCT:
        return i, float(b2.close), "close_third"

    mid = third_candle_mid(b2)
    last_j = min(len(bars) - 1, i + PULLBACK_WAIT_BARS)
    if last_j <= i:
        # کندل سوم همین الان بسته شده؛ مثل برچسب تریدینگ‌ویو سیگنال همان‌جا می‌ماند.
        return i, float(b2.close), "close_third"
    for j in range(i + 1, last_j + 1):
        if direction == "up":
            if j >= 2 and _is_bearish_reversal(bars, j):
                return None
            if bars[j - 1].close < support:
                return None
            if bars[j].low <= mid:
                return j, mid, "mid_touch"
        else:
            if j >= 2 and _is_bullish_reversal(bars, j):
                return None
            if bars[j - 1].close > resistance:
                return None
            if bars[j].high >= mid:
                return j, mid, "mid_touch"
    return None


def _attach_entry_meta(
    meta: dict,
    *,
    entry_index: int,
    entry_px: float,
    entry_mode: str,
    b2: OhlcBar,
) -> None:
    meta["entry_index"] = entry_index
    meta["entry_px"] = entry_px
    meta["entry_mode"] = entry_mode
    meta["third_candle_mid"] = third_candle_mid(b2)
    meta["third_candle_range_pct"] = round(third_candle_range_pct(b2), 4)
    meta["pullback_wait_bars"] = PULLBACK_WAIT_BARS


def detect_three_rp_at(
    bars: list[OhlcBar],
    timeframe: str,
    signal_index: int,
    *,
    pattern_type: str = DEFAULT_PATTERN_TYPE,
) -> PatternHit | None:
    """تشخیص دقیق روی یک کندل (همان bar_index که در Pine برچسب می‌خورد)."""
    if timeframe != "1h":
        return None
    i = signal_index
    if i < 2 or i >= len(bars):
        return None

    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]

    if _is_bullish_reversal(bars, i):
        if not _matches_pattern_type(
            bullish=True, b0=b0, b2=b2, pattern_type=pattern_type
        ):
            return None
        pattern_high = b0.high
        support = _bull_support(b1, b2)
        stage, confirm_i = _follow_bull(bars, i, pattern_high, support)
        if stage == "failed":
            return None
        status = {
            "confirmed": "تأییدشده",
            "detected": "سیگنال ۳BRP",
        }[stage]
        entry = resolve_three_rp_entry(
            bars,
            i,
            direction="up",
            b2=b2,
            support=support,
            resistance=pattern_high,
        )
        if entry is None:
            return None
        entry_i, entry_px, entry_mode = entry
        summary = (
            f"برگشت سه‌کندلی Enhanced · بسته {b2.close:,.0f} > high[2] {pattern_high:,.0f} · "
            f"کف ساختار {support:,.0f}."
        )
        if entry_mode == "mid_touch":
            summary += (
                f" ورود پس از تاچ ۵۰٪ کندل سوم ({entry_px:,.0f}) در کندل {entry_i - i}."
            )
        meta = {
            "direction": "up",
            "stage": stage,
            "kind": "enhanced",
            "pattern_type": pattern_type,
            "signal_index": i,
            "signal_ts": _signal_ts_iso(b2),
            "confirm_index": confirm_i if confirm_i is not None else i,
            "bar_first": i - 2,
            "bar_middle": i - 1,
            "pattern_high": pattern_high,
            "pattern_low": pattern_high,
            "support_line": support,
            "resistance_line": pattern_high,
            "enhanced": True,
        }
        _attach_entry_meta(
            meta,
            entry_index=entry_i,
            entry_px=entry_px,
            entry_mode=entry_mode,
            b2=b2,
        )
        return PatternHit(
            category="three_rp",
            timeframe=timeframe,
            pattern_id="three_rp_bull",
            title_fa="۳BRP صعودی (Three Bar Reversal)",
            status_fa=status,
            summary_fa=summary,
            forecast_fa="LuxAlgo Enhanced — close بالای سقف کندل اول.",
            meta=meta,
        )

    if _is_bearish_reversal(bars, i):
        if not _matches_pattern_type(
            bullish=False, b0=b0, b2=b2, pattern_type=pattern_type
        ):
            return None
        pattern_low = b0.low
        resistance = _bear_resistance(b1, b2)
        stage, confirm_i = _follow_bear(bars, i, pattern_low, resistance)
        if stage == "failed":
            return None
        status = {
            "confirmed": "تأییدشده",
            "detected": "سیگنال ۳BRP",
        }[stage]
        entry = resolve_three_rp_entry(
            bars,
            i,
            direction="down",
            b2=b2,
            support=pattern_low,
            resistance=resistance,
        )
        if entry is None:
            return None
        entry_i, entry_px, entry_mode = entry
        summary = (
            f"برگشت سه‌کندلی Enhanced · بسته {b2.close:,.0f} < low[2] {pattern_low:,.0f} · "
            f"سقف ساختار {resistance:,.0f}."
        )
        if entry_mode == "mid_touch":
            summary += (
                f" ورود پس از تاچ ۵۰٪ کندل سوم ({entry_px:,.0f}) در کندل {entry_i - i}."
            )
        meta = {
            "direction": "down",
            "stage": stage,
            "kind": "enhanced",
            "pattern_type": pattern_type,
            "signal_index": i,
            "signal_ts": _signal_ts_iso(b2),
            "confirm_index": confirm_i if confirm_i is not None else i,
            "bar_first": i - 2,
            "bar_middle": i - 1,
            "pattern_high": pattern_low,
            "pattern_low": pattern_low,
            "support_line": pattern_low,
            "resistance_line": resistance,
            "enhanced": True,
        }
        _attach_entry_meta(
            meta,
            entry_index=entry_i,
            entry_px=entry_px,
            entry_mode=entry_mode,
            b2=b2,
        )
        return PatternHit(
            category="three_rp",
            timeframe=timeframe,
            pattern_id="three_rp_bear",
            title_fa="۳BRP نزولی (Three Bar Reversal)",
            status_fa=status,
            summary_fa=summary,
            forecast_fa="LuxAlgo Enhanced — close زیر کف کندل اول.",
            meta=meta,
        )

    return None


def enumerate_three_rp_enhanced(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    pattern_type: str = DEFAULT_PATTERN_TYPE,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[tuple[int, PatternHit]]:
    """همهٔ Enhanced روی هر کندل بسته — برای مقایسه با TradingView."""
    out: list[tuple[int, PatternHit]] = []
    last = last_closed_index(bars, timeframe)
    for i in range(2, last + 1):
        ts = _bar_ts(bars[i])
        if start and ts < start:
            continue
        if end and ts > end:
            continue
        hit = detect_three_rp_at(bars, timeframe, i, pattern_type=pattern_type)
        if hit:
            out.append((i, hit))
    return out


def detect_three_rp(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    pattern_type: str = DEFAULT_PATTERN_TYPE,
) -> PatternHit | None:
    """اسکن زنده: سیگنال تازه یا ورود تأخیری (تاچ ۵۰٪) روی آخرین کندل 1h بسته."""
    if timeframe != "1h" or len(bars) < 3:
        return None
    last = last_closed_index(bars, timeframe)
    if last < 2:
        return None
    closed = bars[: last + 1]
    lo = max(2, last - PULLBACK_WAIT_BARS)
    for sig in range(lo, last + 1):
        hit = detect_three_rp_at(closed, timeframe, sig, pattern_type=pattern_type)
        if hit is None:
            continue
        entry_i = int(hit.meta.get("entry_index", sig))
        signal_i = int(hit.meta.get("signal_index", sig))
        if entry_i == last or signal_i == last:
            return hit
    return None
