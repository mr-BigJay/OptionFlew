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

# BigBeluga Trading Toolkit — Regular RSI divergence (Pine) + تأیید اولیه ۲ کندل
RSI_PERIOD = 24
LOOKBACK_LEFT = 10
LOOKBACK_RIGHT = 10
EARLY_RIGHT = 2
RANGE_LOWER = 5
RANGE_UPPER = 60
TAKE_PROFIT_PCT = 0.005


def _in_range(p_a: int, p_b: int) -> bool:
    return RANGE_LOWER <= (p_b - p_a) <= RANGE_UPPER


def _recent_confirm(conf_b: int, n: int, right: int) -> bool:
    return conf_b >= n - right - 2


def _bearish_ok(
    rs: list[float | None],
    highs: list[float],
    p_a: int,
    p_b: int,
) -> tuple[float, float] | None:
    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None:
        return None
    if rb >= ra:
        return None
    if highs[p_b] <= highs[p_a]:
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
    if rb <= ra:
        return None
    if lows[p_b] >= lows[p_a]:
        return None
    return float(ra), float(rb)


def _bar_close(bars: list[OhlcBar], idx: int) -> float | None:
    if idx < 0 or idx >= len(bars):
        return None
    return float(bars[idx].close)


def _price_txt(px: float | None) -> str:
    if px is None:
        return "—"
    return f"{px:,.0f}"


def _entry_lines(
    bars: list[OhlcBar],
    p_b: int,
    *,
    early: bool,
) -> tuple[int, int | None, float | None, float | None, str]:
    early_ix = p_b + EARLY_RIGHT
    final_ix = p_b + LOOKBACK_RIGHT
    early_px = _bar_close(bars, early_ix)
    final_px = None if early else _bar_close(bars, final_ix)
    if early:
        extra = (
            f"تأیید اولیه در قیمت {_price_txt(early_px)}؛ "
            f"منتظر pivot RSI {LOOKBACK_LEFT}/{LOOKBACK_RIGHT} (حدود "
            f"{LOOKBACK_RIGHT - EARLY_RIGHT} کندل)."
        )
        return early_ix, None, early_px, None, extra
    extra = (
        f"تأیید اولیه در قیمت {_price_txt(early_px)}، "
        f"تأیید نهایی (BigBeluga) در قیمت {_price_txt(final_px)}."
    )
    return early_ix, final_ix, early_px, final_px, extra


def _hit_bearish(
    bars: list[OhlcBar],
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
    status = "سیگنال اولیه" if early else "تأییدشده"
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early
    )
    entry_i = early_ix if early else (final_ix if final_ix is not None else confirm_index)
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bearish (BigBeluga) · "
            f"قیمت HH ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI LH ({rb:.1f} < {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
            if not early
            else "سقف RSI در حال شکل‌گیری؛ با ۲ کندل راست مثل TV تأیید می‌شود."
        ),
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_b, highs[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "down",
            "confirm_index": confirm_index,
            "early_index": early_ix,
            "final_index": final_ix,
            "early_price": early_px,
            "final_price": final_px,
            "entry_index": entry_i,
            "early_side": "high",
            "stage": "early" if early else "confirmed",
        },
    )


def _hit_bullish(
    bars: list[OhlcBar],
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
    status = "سیگنال اولیه" if early else "تأییدشده"
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early
    )
    entry_i = early_ix if early else (final_ix if final_ix is not None else confirm_index)
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bullish (BigBeluga) · "
            f"قیمت LL ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI HL ({rb:.1f} > {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
            if not early
            else "کف RSI در حال شکل‌گیری؛ با ۲ کندل راست مثل TV تأیید می‌شود."
        ),
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_b, lows[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "up",
            "confirm_index": confirm_index,
            "early_index": early_ix,
            "final_index": final_ix,
            "early_price": early_px,
            "final_price": final_px,
            "entry_index": entry_i,
            "early_side": "low",
            "stage": "early" if early else "confirmed",
        },
    )


def _confirmed_bearish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    highs: list[float],
    ph: list[tuple[int, int]],
    n: int,
) -> PatternHit | None:
    if len(ph) < 2:
        return None
    conf_b, p_b = ph[-1]
    if not _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
        return None
    _, p_a = ph[-2]
    if not _in_range(p_a, p_b):
        return None
    pair = _bearish_ok(rs, highs, p_a, p_b)
    if not pair:
        return None
    ra, rb = pair
    return _hit_bearish(
        bars, timeframe, p_a, p_b, highs, ra, rb, conf_b, early=False
    )


def _confirmed_bullish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    lows: list[float],
    pl: list[tuple[int, int]],
    n: int,
) -> PatternHit | None:
    if len(pl) < 2:
        return None
    conf_b, p_b = pl[-1]
    if not _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
        return None
    _, p_a = pl[-2]
    if not _in_range(p_a, p_b):
        return None
    pair = _bullish_ok(rs, lows, p_a, p_b)
    if not pair:
        return None
    ra, rb = pair
    return _hit_bullish(
        bars, timeframe, p_a, p_b, lows, ra, rb, conf_b, early=False
    )


def _early_bearish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    highs: list[float],
    ph: list[tuple[int, int]],
    n: int,
) -> PatternHit | None:
    if not ph:
        return None
    _, p_ref = ph[-1]
    best: tuple[int, int, float, float] | None = None
    for right in range(EARLY_RIGHT, LOOKBACK_RIGHT):
        p = n - 1 - right
        if p < LOOKBACK_LEFT or p <= p_ref:
            continue
        if not is_pivot_high(rs, p, LOOKBACK_LEFT, right):
            continue
        if not _in_range(p_ref, p):
            continue
        pair = _bearish_ok(rs, highs, p_ref, p)
        if pair and (best is None or p > best[0]):
            best = (p, right, pair[0], pair[1])
    if not best:
        return None
    p_b, right, ra, rb = best
    return _hit_bearish(
        bars,
        timeframe,
        p_ref,
        p_b,
        highs,
        ra,
        rb,
        p_b + right,
        early=True,
    )


def _early_bullish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    lows: list[float],
    pl: list[tuple[int, int]],
    n: int,
) -> PatternHit | None:
    if not pl:
        return None
    _, p_ref = pl[-1]
    best: tuple[int, int, float, float] | None = None
    for right in range(EARLY_RIGHT, LOOKBACK_RIGHT):
        p = n - 1 - right
        if p < LOOKBACK_LEFT or p <= p_ref:
            continue
        if not is_pivot_low(rs, p, LOOKBACK_LEFT, right):
            continue
        if not _in_range(p_ref, p):
            continue
        pair = _bullish_ok(rs, lows, p_ref, p)
        if pair and (best is None or p > best[0]):
            best = (p, right, pair[0], pair[1])
    if not best:
        return None
    p_b, right, ra, rb = best
    return _hit_bullish(
        bars,
        timeframe,
        p_ref,
        p_b,
        lows,
        ra,
        rb,
        p_b + right,
        early=True,
    )


def _pick_latest(*hits: PatternHit | None) -> PatternHit | None:
    found = [h for h in hits if h is not None]
    if not found:
        return None
    return max(found, key=lambda h: int(h.meta.get("confirm_index", 0)))


def evaluate_divergence_path(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
) -> tuple[bool | None, str]:
    """ورود = early_index؛ خروج = ۰.۵٪ سود یا آخرین کندل (مثل ترندلاین برای TP)."""
    meta = hit.meta
    direction = meta.get("direction")
    if direction not in ("up", "down"):
        return None, "جهت واگرایی مشخص نیست."

    entry_i = meta.get("entry_index")
    if not isinstance(entry_i, int):
        early = meta.get("early_index")
        final = meta.get("final_index")
        entry_i = early if isinstance(early, int) else final
    if not isinstance(entry_i, int):
        entry_i = idx
    entry_i = max(0, min(entry_i, len(bars) - 1))
    entry_px = float(bars[entry_i].close)
    if entry_px <= 0:
        return None, "قیمت ورود نامعتبر است."

    start = entry_i + 1
    if start >= len(bars):
        return None, "کندل کافی بعد از ورود نبود."

    if direction == "up":
        tp_px = entry_px * (1 + TAKE_PROFIT_PCT)
    else:
        tp_px = entry_px * (1 - TAKE_PROFIT_PCT)

    exit_i: int | None = None
    exit_px: float | None = None
    reason = ""
    for i in range(start, len(bars)):
        b = bars[i]
        if direction == "up" and b.high >= tp_px:
            exit_i, exit_px, reason = i, tp_px, "بستن در سود ۰.۵٪"
            break
        if direction == "down" and b.low <= tp_px:
            exit_i, exit_px, reason = i, tp_px, "بستن در سود ۰.۵٪"
            break

    if exit_i is None:
        exit_i = len(bars) - 1
        exit_px = float(bars[exit_i].close)
        reason = "پایان داده"

    if direction == "up":
        pct = (exit_px - entry_px) / entry_px
    else:
        pct = (entry_px - exit_px) / entry_px

    meta["entry_index"] = entry_i
    meta["exit_index"] = exit_i
    meta["path_pct"] = pct
    meta["exit_reason"] = reason
    ok = pct > 0
    note = (
        f"بازده مسیر ورود تا {reason}: {pct * 100:+.2f}٪ "
        f"({entry_px:,.0f} → {exit_px:,.0f})"
    )
    return ok, note


def detect_rsi_divergence(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + RSI_PERIOD + 20
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes, RSI_PERIOD)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    n = len(bars)

    ph = rsi_pivot_high_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )
    pl = rsi_pivot_low_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )

    confirmed = _pick_latest(
        _confirmed_bearish(bars, timeframe, rs, highs, ph, n),
        _confirmed_bullish(bars, timeframe, rs, lows, pl, n),
    )
    if confirmed is not None:
        return confirmed

    if not allow_early:
        return None

    return _pick_latest(
        _early_bearish(bars, timeframe, rs, highs, ph, n),
        _early_bullish(bars, timeframe, rs, lows, pl, n),
    )
