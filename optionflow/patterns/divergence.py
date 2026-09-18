from __future__ import annotations

from optionflow.patterns.indicators import (
    is_pivot_high,
    is_pivot_low,
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# TradingView: تأیید نهایی pivot RSI با 5/5
LOOKBACK_LEFT = 5
LOOKBACK_RIGHT = 5
# سیگنال اولیه: ۲ کندل راست کافی است؛ تا کندل ۵ام هنوز «اولیه» است
EARLY_RIGHT = 2
RANGE_LOWER = 5
RANGE_UPPER = 60
MIN_RSI_DIFF = 3.0
RSI_OVERBOUGHT = 65.0
RSI_OVERSOLD = 35.0
# سقف/کف قیمت تقریباً برابر را واگرایی حساب نکن (۰٫۱۲٪)
MIN_PRICE_PCT = 0.0012

_TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _in_range(prev_pivot: int, pivot: int) -> bool:
    return RANGE_LOWER <= (pivot - prev_pivot) <= RANGE_UPPER


def _recent_confirm(conf_b: int, n: int, right: int) -> bool:
    return conf_b >= n - right - 2


def _price_apart(a: float, b: float) -> bool:
    base = max(abs(a), 1e-9)
    return abs(b - a) / base >= MIN_PRICE_PCT


def _delay_fa(timeframe: str, bars: int) -> str:
    mins = _TF_MINUTES.get(timeframe, 5) * bars
    if mins < 60:
        return f"{bars} کندل (~{mins} دقیقه)"
    hours = mins / 60
    if hours == int(hours):
        return f"{bars} کندل (~{int(hours)} ساعت)"
    return f"{bars} کندل (~{hours:.1f} ساعت)"


def _forming_pivot(
    values: list[float | None],
    *,
    high: bool,
    n: int,
) -> tuple[int, int] | None:
    """آخرین سقف/کف در حال شکل‌گیری: ۲ تا ۴ کندل راست (قبل از تأیید ۵)."""
    for right in range(EARLY_RIGHT, LOOKBACK_RIGHT):
        p = n - 1 - right
        if p < LOOKBACK_LEFT:
            continue
        ok = (
            is_pivot_high(values, p, LOOKBACK_LEFT, right)
            if high
            else is_pivot_low(values, p, LOOKBACK_LEFT, right)
        )
        if ok:
            return p, right
    return None


def _bearish_ok(
    rs: list[float | None],
    highs: list[float],
    p_a: int,
    p_b: int,
) -> tuple[float, float] | None:
    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None:
        return None
    if ra < RSI_OVERBOUGHT or (ra - rb) < MIN_RSI_DIFF:
        return None
    if highs[p_b] <= highs[p_a] or not _price_apart(highs[p_a], highs[p_b]):
        return None
    return float(ra), float(rb)


def _bullish_ok(
    rs: list[float | None],
    lows: list[float],
    p_a: int,
    p_b: int,
) -> tuple[float, float] | None:
    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None:
        return None
    if ra > RSI_OVERSOLD or (rb - ra) < MIN_RSI_DIFF:
        return None
    if lows[p_b] >= lows[p_a] or not _price_apart(lows[p_a], lows[p_b]):
        return None
    return float(ra), float(rb)


def _hit_bearish(
    timeframe: str,
    p_a: int,
    p_b: int,
    highs: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    *,
    early: bool,
) -> PatternHit:
    diff = ra - rb
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    delay_txt = _delay_fa(timeframe, delay)
    extra = (
        f"هشدار زودهنگام پس از {delay_txt}؛ اگر تا ۵ کندل سقف RSI نشکند، تأیید نهایی می‌شود."
        if early
        else f"تأیید pivot بعد از {delay_txt}."
    )
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bearish · دو سقف متوالی — "
            f"قیمت بالاتر ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI پایین‌تر ({rb:.1f} < {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "پیش‌بینی: احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
            if not early
            else "پیش‌بینی اولیه: اگر سقف RSI در ۲–۳ کندل بعد بالاتر نرود، واگرایی نزولی تأیید می‌شود."
        ),
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_b, highs[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "down",
            "confirm_index": confirm_index,
            "tv_pivot": True,
            "stage": "early" if early else "confirmed",
            "delay_bars": delay,
        },
    )


def _hit_bullish(
    timeframe: str,
    p_a: int,
    p_b: int,
    lows: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    *,
    early: bool,
) -> PatternHit:
    diff = rb - ra
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    delay_txt = _delay_fa(timeframe, delay)
    extra = (
        f"هشدار زودهنگام پس از {delay_txt}؛ اگر تا ۵ کندل کف RSI نشکند، تأیید نهایی می‌شود."
        if early
        else f"تأیید pivot بعد از {delay_txt}."
    )
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bullish · دو کف متوالی — "
            f"قیمت پایین‌تر ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI بالاتر ({rb:.1f} > {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "پیش‌بینی: احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
            if not early
            else "پیش‌بینی اولیه: اگر کف RSI در ۲–۳ کندل بعد پایین‌تر نرود، واگرایی مثبت تأیید می‌شود."
        ),
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_b, lows[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "up",
            "confirm_index": confirm_index,
            "tv_pivot": True,
            "stage": "early" if early else "confirmed",
            "delay_bars": delay,
        },
    )


def detect_rsi_divergence(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + 20
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    n = len(bars)

    ph = rsi_pivot_high_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )
    pl = rsi_pivot_low_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )

    if len(ph) >= 2:
        conf_b, p_b = ph[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            _, p_a = ph[-2]
            if _in_range(p_a, p_b):
                pair = _bearish_ok(rs, highs, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bearish(
                        timeframe, p_a, p_b, highs, ra, rb, conf_b, early=False
                    )

    if len(pl) >= 2:
        conf_b, p_b = pl[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            _, p_a = pl[-2]
            if _in_range(p_a, p_b):
                pair = _bullish_ok(rs, lows, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bullish(
                        timeframe, p_a, p_b, lows, ra, rb, conf_b, early=False
                    )

    if not allow_early:
        return None

    forming_h = _forming_pivot(rs, high=True, n=n)
    if forming_h and ph:
        p_b, right = forming_h
        _, p_a = ph[-1]
        if p_a < p_b and _in_range(p_a, p_b):
            pair = _bearish_ok(rs, highs, p_a, p_b)
            if pair:
                ra, rb = pair
                return _hit_bearish(
                    timeframe, p_a, p_b, highs, ra, rb, p_b + right, early=True
                )

    forming_l = _forming_pivot(rs, high=False, n=n)
    if forming_l and pl:
        p_b, right = forming_l
        _, p_a = pl[-1]
        if p_a < p_b and _in_range(p_a, p_b):
            pair = _bullish_ok(rs, lows, p_a, p_b)
            if pair:
                ra, rb = pair
                return _hit_bullish(
                    timeframe, p_a, p_b, lows, ra, rb, p_b + right, early=True
                )

    return None
