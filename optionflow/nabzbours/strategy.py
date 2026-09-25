"""نبض‌بورس (RSI_MACD_VWAP_EMA) — مستقل از بقیهٔ سناریوها.

جهت: تایم‌فریم بالاتر (پیش‌فرض ۱۵m)
ورود: تایم‌فریم ورود (پیش‌فرض ۵m) — VWAP + EMA + RSI + MACD
خروج: تایم‌فریم خروج (پیش‌فرض ۳m) — هشدار RSI سپس تأیید MACD
اگر ۳m در کش نباشد، خروج روی همان تایم‌فریم ورود ارزیابی می‌شود.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from optionflow.patterns.indicators import atr, ema, rsi
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.nabzbours")

TF_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

# امتیازها و فیلترها — یک‌جا قابل تغییر
DEFAULT_CONFIG: dict[str, Any] = {
    "higher_timeframe": "15m",
    "entry_timeframe": "5m",
    "exit_timeframe": "3m",
    "require_higher_tf": True,
    "ema_length": 50,
    "rsi_period": 14,
    "rsi_slope_bars": 2,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "use_vwap": True,
    "use_ema": True,
    "use_rsi": True,
    "use_macd": True,
    "use_divergence": True,
    "score_vwap": 1,
    "score_ema": 1,
    "score_rsi": 1,
    "score_macd": 1,
    "score_divergence": 1,
    "min_score": 4,
    "pivot_left": 5,
    "pivot_right": 5,
    "atr_len": 14,
    "stop_atr_mult": 1.0,
    "tp_rr": 1.5,
    "max_hold_bars": 48,
    "long_trades": True,
    "short_trades": True,
}


def merge_config(params: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if params:
        cfg.update(params)
    return cfg


def macd_lines(
    closes: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    line: list[float | None] = [None] * len(closes)
    for i, (f, s) in enumerate(zip(fast_e, slow_e)):
        if f is not None and s is not None:
            line[i] = f - s
    # EMA روی خط MACD؛ Noneها را با آخرین مقدار پر نمی‌کنیم (بدون lookahead)
    filled: list[float] = []
    idx_map: list[int] = []
    for i, v in enumerate(line):
        if v is not None:
            filled.append(v)
            idx_map.append(i)
    sig_raw = ema(filled, signal)
    sig: list[float | None] = [None] * len(closes)
    hist: list[float | None] = [None] * len(closes)
    for j, i in enumerate(idx_map):
        if sig_raw[j] is not None:
            sig[i] = sig_raw[j]
            hist[i] = line[i] - sig_raw[j] if line[i] is not None else None
    return line, sig, hist


def _ts(bar: OhlcBar) -> datetime:
    ts = bar.ts
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _closed_index(bars: list[OhlcBar], timeframe: str, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    sec = TF_SECONDS.get(timeframe, 300)
    i = len(bars) - 1
    while i >= 0 and _ts(bars[i]) + timedelta(seconds=sec) > now:
        i -= 1
    return i


def session_vwap_at(bars: list[OhlcBar], i: int) -> float | None:
    """VWAP روز UTC تا کندل i (شامل). حجم صفر → وزن ۱ (typical)."""
    if i < 0 or i >= len(bars):
        return None
    day = _ts(bars[i]).date()
    pv = 0.0
    vol = 0.0
    for j in range(i, -1, -1):
        b = bars[j]
        if _ts(b).date() != day:
            break
        typical = (b.high + b.low + b.close) / 3.0
        w = b.volume if b.volume and b.volume > 0 else 1.0
        pv += typical * w
        vol += w
    if vol <= 0:
        return None
    return pv / vol


def _rising(series: list[float | None], i: int, bars_back: int) -> bool | None:
    if i - bars_back < 0:
        return None
    a, b = series[i], series[i - bars_back]
    if a is None or b is None:
        return None
    return a > b


def _falling(series: list[float | None], i: int, bars_back: int) -> bool | None:
    if i - bars_back < 0:
        return None
    a, b = series[i], series[i - bars_back]
    if a is None or b is None:
        return None
    return a < b


def _pivot_high(values: list[float], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values):
        return False
    v = values[p]
    for j in range(p - left, p + right + 1):
        if j != p and values[j] >= v:
            return False
    return True


def _pivot_high_opt(values: list[float | None], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values) or values[p] is None:
        return False
    v = values[p]
    for j in range(p - left, p + right + 1):
        o = values[j]
        if o is None or (j != p and o >= v):
            return False
    return True


def _pivot_low_opt(values: list[float | None], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values) or values[p] is None:
        return False
    v = values[p]
    for j in range(p - left, p + right + 1):
        o = values[j]
        if o is None or (j != p and o <= v):
            return False
    return True


def _pivot_low(values: list[float], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values):
        return False
    v = values[p]
    for j in range(p - left, p + right + 1):
        if j != p and values[j] <= v:
            return False
    return True


def divergence_at(
    bars: list[OhlcBar],
    rsi_vals: list[float | None],
    i: int,
    *,
    left: int,
    right: int,
) -> dict[str, bool]:
    """واگرایی فقط با پیوت تأییدشده تا کندل i (بدون lookahead)."""
    out = {"bullish": False, "bearish": False}
    highs: list[tuple[int, float, float]] = []
    lows: list[tuple[int, float, float]] = []
    prices_h = [b.high for b in bars]
    prices_l = [b.low for b in bars]
    last_p = i - right
    if last_p < left:
        return out
    # فقط پیوت‌های اخیر؛ اسکن کل تاریخچه بکتست را قفل می‌کند
    start_p = max(left, last_p - 80)
    for p in range(start_p, last_p + 1):
        rv = rsi_vals[p]
        if rv is None:
            continue
        if _pivot_high(prices_h, p, left, right) and _pivot_high_opt(rsi_vals, p, left, right):
            highs.append((p, bars[p].high, rv))
        if _pivot_low(prices_l, p, left, right) and _pivot_low_opt(rsi_vals, p, left, right):
            lows.append((p, bars[p].low, float(rv)))
    if len(highs) >= 2:
        _, p1, r1 = highs[-2]
        _, p2, r2 = highs[-1]
        if p2 > p1 and r2 < r1:
            out["bearish"] = True
    if len(lows) >= 2:
        _, p1, r1 = lows[-2]
        _, p2, r2 = lows[-1]
        if p2 < p1 and r2 > r1:
            out["bullish"] = True
    return out


def _index_closed_before(bars: list[OhlcBar], tf: str, asof: datetime) -> int:
    sec = TF_SECONDS.get(tf, 900)
    idx = -1
    for i, b in enumerate(bars):
        if _ts(b) + timedelta(seconds=sec) <= asof:
            idx = i
        else:
            break
    return idx


def resample_minutes(bars: list[OhlcBar], minutes: int) -> list[OhlcBar]:
    if not bars or minutes < 1:
        return []
    bucket = minutes * 60
    groups: dict[int, list[OhlcBar]] = {}
    for b in bars:
        key = int(_ts(b).timestamp()) // bucket * bucket
        groups.setdefault(key, []).append(b)
    out: list[OhlcBar] = []
    for key in sorted(groups):
        chunk = groups[key]
        out.append(
            OhlcBar(
                ts=datetime.fromtimestamp(key, tz=timezone.utc),
                open=chunk[0].open,
                high=max(x.high for x in chunk),
                low=min(x.low for x in chunk),
                close=chunk[-1].close,
                volume=sum(x.volume for x in chunk),
            )
        )
    return out


@dataclass
class SetupView:
    direction: str
    score: int
    reasons: dict[str, bool]
    log: str
    entry: float
    stop: float
    tp: float


def _score(flags: dict[str, bool], cfg: dict[str, Any], direction: str) -> int:
    s = 0
    if flags.get("vwap"):
        s += int(cfg["score_vwap"])
    if flags.get("ema"):
        s += int(cfg["score_ema"])
    if flags.get("rsi"):
        s += int(cfg["score_rsi"])
    if flags.get("macd"):
        s += int(cfg["score_macd"])
    div_ok = flags.get("bull_div") if direction == "long" else flags.get("bear_div")
    if div_ok and cfg.get("use_divergence", True):
        s += int(cfg["score_divergence"])
    return s


def evaluate_entry(
    bars: list[OhlcBar],
    i: int,
    cfg: dict[str, Any],
    *,
    higher_bars: list[OhlcBar] | None = None,
    higher_tf: str = "15m",
) -> SetupView | None:
    need = max(
        int(cfg["ema_length"]),
        int(cfg["macd_slow"]) + int(cfg["macd_signal"]),
        int(cfg["rsi_period"]) + int(cfg["rsi_slope_bars"]),
        int(cfg["pivot_left"]) + int(cfg["pivot_right"]) + 2,
    )
    if i < need or i >= len(bars):
        return None
    closes = [b.close for b in bars]
    ema_v = ema(closes, int(cfg["ema_length"]))
    rsi_v = rsi(closes, int(cfg["rsi_period"]))
    macd_l, macd_s, _ = macd_lines(
        closes,
        fast=int(cfg["macd_fast"]),
        slow=int(cfg["macd_slow"]),
        signal=int(cfg["macd_signal"]),
    )
    price = bars[i].close
    vwap = session_vwap_at(bars, i)
    e = ema_v[i]
    rv = rsi_v[i]
    ml, ms = macd_l[i], macd_s[i]
    slope = int(cfg["rsi_slope_bars"])
    rsi_up = _rising(rsi_v, i, slope)
    rsi_dn = _falling(rsi_v, i, slope)
    macd_bull = ml is not None and ms is not None and ml > ms
    macd_bear = ml is not None and ms is not None and ml < ms
    div = (
        divergence_at(
            bars,
            rsi_v,
            i,
            left=int(cfg["pivot_left"]),
            right=int(cfg["pivot_right"]),
        )
        if cfg.get("use_divergence", True)
        else {"bullish": False, "bearish": False}
    )

    def _pass(flag: bool | None, enabled: bool) -> bool:
        if not enabled:
            return True
        return bool(flag)

    above_vwap = vwap is not None and price > vwap
    below_vwap = vwap is not None and price < vwap
    above_ema = e is not None and price > e
    below_ema = e is not None and price < e

    long_core = (
        _pass(above_vwap, bool(cfg["use_vwap"]))
        and _pass(above_ema, bool(cfg["use_ema"]))
        and _pass(rsi_up, bool(cfg["use_rsi"]))
        and _pass(macd_bull, bool(cfg["use_macd"]))
    )
    short_core = (
        _pass(below_vwap, bool(cfg["use_vwap"]))
        and _pass(below_ema, bool(cfg["use_ema"]))
        and _pass(rsi_dn, bool(cfg["use_rsi"]))
        and _pass(macd_bear, bool(cfg["use_macd"]))
    )

    higher_ok_long = True
    higher_ok_short = True
    if cfg.get("require_higher_tf") and higher_bars:
        asof = _ts(bars[i]) + timedelta(seconds=TF_SECONDS.get(cfg["entry_timeframe"], 300))
        hi = _index_closed_before(higher_bars, higher_tf, asof)
        if hi < int(cfg["ema_length"]):
            higher_ok_long = higher_ok_short = False
        else:
            h_closes = [b.close for b in higher_bars[: hi + 1]]
            h_ema = ema(h_closes, int(cfg["ema_length"]))
            h_price = higher_bars[hi].close
            h_vwap = session_vwap_at(higher_bars[: hi + 1], hi)
            h_e = h_ema[hi] if hi < len(h_ema) else None
            if cfg.get("use_vwap") and (h_vwap is None or not (h_price > h_vwap)):
                higher_ok_long = False
            if cfg.get("use_ema") and (h_e is None or not (h_price > h_e)):
                higher_ok_long = False
            if cfg.get("use_vwap") and (h_vwap is None or not (h_price < h_vwap)):
                higher_ok_short = False
            if cfg.get("use_ema") and (h_e is None or not (h_price < h_e)):
                higher_ok_short = False
    elif cfg.get("require_higher_tf") and not higher_bars:
        higher_ok_long = higher_ok_short = False

    direction = ""
    if long_core and higher_ok_long and cfg.get("long_trades", True):
        direction = "long"
    elif short_core and higher_ok_short and cfg.get("short_trades", True):
        direction = "short"
    if not direction:
        return None

    flags = {
        "vwap": above_vwap if direction == "long" else below_vwap,
        "ema": above_ema if direction == "long" else below_ema,
        "rsi": bool(rsi_up) if direction == "long" else bool(rsi_dn),
        "macd": macd_bull if direction == "long" else macd_bear,
        "bull_div": div["bullish"],
        "bear_div": div["bearish"],
    }
    # فیلتر خاموش = شرط پاس، ولی امتیاز فقط اگر واقعاً True باشد
    score = _score(flags, cfg, direction)
    if score < int(cfg["min_score"]):
        return None

    atrs = atr(bars[: i + 1], int(cfg["atr_len"]))
    atr_now = next((v for v in reversed(atrs) if v), None)
    risk = (atr_now or price * 0.002) * float(cfg["stop_atr_mult"])
    if risk <= 0:
        risk = price * 0.001
    if direction == "long":
        stop = price - risk
        tp = price + float(cfg["tp_rr"]) * risk
    else:
        stop = price + risk
        tp = price - float(cfg["tp_rr"]) * risk

    side = "LONG" if direction == "long" else "SHORT"
    log = (
        f"{side} SIGNAL\n"
        f"Price > VWAP: {above_vwap}\n"
        f"Price > EMA: {above_ema}\n"
        f"Price < VWAP: {below_vwap}\n"
        f"Price < EMA: {below_ema}\n"
        f"RSI Rising: {rsi_up}\n"
        f"RSI Falling: {rsi_dn}\n"
        f"MACD Bullish: {macd_bull}\n"
        f"MACD Bearish: {macd_bear}\n"
        f"Bullish Divergence: {div['bullish']}\n"
        f"Bearish Divergence: {div['bearish']}\n"
        f"Higher TF OK: {higher_ok_long if direction == 'long' else higher_ok_short}\n"
        f"Score: {score}"
    )
    logger.info("nabzbours %s", log.replace("\n", " | "))
    return SetupView(direction, score, flags, log, price, stop, tp)


def exit_state(
    bars: list[OhlcBar],
    i: int,
    direction: str,
    cfg: dict[str, Any],
    *,
    warned: bool,
) -> tuple[bool, bool, str]:
    """برمی‌گرداند (warning, exit_confirmed, log)."""
    closes = [b.close for b in bars[: i + 1]]
    rsi_v = rsi(closes, int(cfg["rsi_period"]))
    macd_l, macd_s, _ = macd_lines(
        closes,
        fast=int(cfg["macd_fast"]),
        slow=int(cfg["macd_slow"]),
        signal=int(cfg["macd_signal"]),
    )
    slope = int(cfg["rsi_slope_bars"])
    if direction == "long":
        rsi_flip = bool(_falling(rsi_v, i, slope))
        macd_confirm = (
            i > 0
            and macd_l[i] is not None
            and macd_s[i] is not None
            and macd_l[i - 1] is not None
            and macd_s[i - 1] is not None
            and macd_l[i - 1] >= macd_s[i - 1]
            and macd_l[i] < macd_s[i]
        )
    else:
        rsi_flip = bool(_rising(rsi_v, i, slope))
        macd_confirm = (
            i > 0
            and macd_l[i] is not None
            and macd_s[i] is not None
            and macd_l[i - 1] is not None
            and macd_s[i - 1] is not None
            and macd_l[i - 1] <= macd_s[i - 1]
            and macd_l[i] > macd_s[i]
        )
    warning = warned or rsi_flip
    confirmed = warning and macd_confirm
    side = "LONG" if direction == "long" else "SHORT"
    log = (
        f"EXIT {side}\n"
        f"RSI Direction Change: {rsi_flip}\n"
        f"Early Warning: {warning}\n"
        f"MACD Confirmation: {macd_confirm}\n"
        f"Exit Confirmed: {confirmed}"
    )
    return warning, confirmed, log


def _load_series(interval: str, *, limit: int = 800) -> list[OhlcBar]:
    try:
        from app.storage import data_dir
        from optionflow.patterns.history import history_data_dir, load_cached_bars

        cached = load_cached_bars(history_data_dir(data_dir()), interval)
        if len(cached) >= 50:
            return cached[-limit:]
    except Exception:
        logger.debug("nabzbours cache miss %s", interval, exc_info=True)
    if interval == "3m":
        try:
            from app.storage import data_dir
            from optionflow.patterns.history import history_data_dir, load_cached_bars

            one = load_cached_bars(history_data_dir(data_dir()), "1m")
            if one:
                return resample_minutes(one, 3)[-limit:]
        except Exception:
            logger.debug("nabzbours 3m resample failed", exc_info=True)
    from optionflow.patterns.ohlc import load_btcusdt

    return load_btcusdt(interval, limit=min(limit, 1000))


def detect_nabzbours(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    cfg = merge_config(params)
    entry_tf = str(cfg["entry_timeframe"])
    if timeframe != entry_tf:
        return None
    i = _closed_index(bars, timeframe)
    if i < 0:
        return None
    higher = _load_series(str(cfg["higher_timeframe"]))
    setup = evaluate_entry(
        bars,
        i,
        cfg,
        higher_bars=higher,
        higher_tf=str(cfg["higher_timeframe"]),
    )
    if setup is None:
        return None
    direction = "up" if setup.direction == "long" else "down"
    sk = f"{setup.direction}:{bars[i].ts.isoformat()}"
    return PatternHit(
        category="scalp",
        timeframe=timeframe,
        pattern_id="scalp_nabzbours",
        title_fa=scenario.get("title_fa") or "نبض‌بورس",
        status_fa="فعال",
        summary_fa=setup.log.replace("\n", " · "),
        forecast_fa=(
            f"امتیاز {setup.score} · استاپ {setup.stop:,.0f} · TP {setup.tp:,.0f}"
        ),
        meta={
            "scenario_id": scenario.get("scenario_id", "nabzbours"),
            "strategy": "RSI_MACD_VWAP_EMA",
            "direction": direction,
            "nabz_side": setup.direction,
            "entry_px": setup.entry,
            "stop_px": setup.stop,
            "tp_px": setup.tp,
            "entry_index": i,
            "confirm_index": i,
            "setup_key": sk,
            "stage": "active",
            "score": setup.score,
            "reasons": setup.reasons,
            "signal_log": setup.log,
            "tp_rr": cfg["tp_rr"],
            "max_hold_bars": int(cfg["max_hold_bars"]),
            "exit_timeframe": cfg["exit_timeframe"],
        },
    )


@dataclass
class TradeStat:
    side: str
    r_multiple: float
    win: bool
    entry_log: str
    exit_log: str
    exit_reason: str


def _r_multiple(side: str, entry: float, stop: float, exit_px: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    if side == "long":
        return (exit_px - entry) / risk
    return (entry - exit_px) / risk


def simulate_trade(
    entry_bars: list[OhlcBar],
    entry_i: int,
    setup: SetupView,
    cfg: dict[str, Any],
    exit_bars: list[OhlcBar] | None,
) -> TradeStat:
    """SL قبل از TP؛ خروج اندیکاتوری روی سری خروج (یا ورود اگر ۳m نباشد)."""
    series = exit_bars if exit_bars else entry_bars
    exit_tf = str(cfg["exit_timeframe"]) if exit_bars else str(cfg["entry_timeframe"])
    start_ts = _ts(entry_bars[entry_i]) + timedelta(
        seconds=TF_SECONDS.get(str(cfg["entry_timeframe"]), 300)
    )
    start_j = 0
    for j, b in enumerate(series):
        if _ts(b) + timedelta(seconds=TF_SECONDS.get(exit_tf, 180)) > start_ts:
            start_j = j
            break
    hold = int(cfg["max_hold_bars"])
    end_j = min(len(series) - 1, start_j + hold)
    warned = False
    exit_px = series[end_j].close if series else setup.entry
    reason = "پایان مهلت نگه‌داری"
    exit_log = ""
    # map SL/TP روی کندل‌های ورود هم چک شود
    entry_end = min(len(entry_bars) - 1, entry_i + hold)
    for i in range(entry_i + 1, entry_end + 1):
        b = entry_bars[i]
        if setup.direction == "long":
            if b.low <= setup.stop:
                exit_px, reason = setup.stop, "برخورد استاپ"
                break
            if b.high >= setup.tp:
                exit_px, reason = setup.tp, "رسیدن به TP"
                break
        else:
            if b.high >= setup.stop:
                exit_px, reason = setup.stop, "برخورد استاپ"
                break
            if b.low <= setup.tp:
                exit_px, reason = setup.tp, "رسیدن به TP"
                break
        if reason in ("برخورد استاپ", "رسیدن به TP"):
            break
    else:
        for j in range(start_j, end_j + 1):
            warned, confirmed, exit_log = exit_state(
                series, j, setup.direction, cfg, warned=warned
            )
            if confirmed:
                exit_px = series[j].close
                reason = "خروج RSI+MACD"
                break
        else:
            exit_px = series[end_j].close if series else setup.entry
            reason = "پایان مهلت نگه‌داری"
    r = _r_multiple(setup.direction, setup.entry, setup.stop, exit_px)
    return TradeStat(
        setup.direction,
        r,
        r > 0,
        setup.log,
        exit_log,
        reason,
    )


def scan_backtest(
    entry_bars: list[OhlcBar],
    *,
    higher_bars: list[OhlcBar],
    exit_bars: list[OhlcBar],
    cfg: dict[str, Any],
    scan_start: int,
    scan_end: int,
    on_progress: Any = None,
    should_cancel: Any = None,
) -> list[tuple[int, SetupView, TradeStat]]:
    cfg = merge_config(cfg)
    out: list[tuple[int, SetupView, TradeStat]] = []
    span = max(1, scan_end - scan_start + 1)
    i = scan_start
    while i <= scan_end:
        if should_cancel and should_cancel():
            break
        if on_progress and (i == scan_start or (i - scan_start) % 40 == 0):
            on_progress(i - scan_start, span)
        setup = evaluate_entry(
            entry_bars,
            i,
            cfg,
            higher_bars=higher_bars,
            higher_tf=str(cfg["higher_timeframe"]),
        )
        if setup is None:
            i += 1
            continue
        stat = simulate_trade(entry_bars, i, setup, cfg, exit_bars or None)
        out.append((i, setup, stat))
        i += max(1, int(cfg["max_hold_bars"]))
    if on_progress:
        on_progress(span, span)
    return out


def summarize_trades(trades: list[TradeStat]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "text": "معامله‌ای نیست."}
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]
    gross_win = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = 0
    max_streak = 0
    for t in trades:
        equity += t.r_multiple
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if not t.win:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    longs = sum(1 for t in trades if t.side == "long")
    shorts = n - longs
    avg_r = equity / n
    text = (
        f"معاملات {n} · برد {len(wins)/n*100:.1f}٪ · "
        f"PF {pf:.2f} · " if pf is not None else f"معاملات {n} · برد {len(wins)/n*100:.1f}٪ · PF — · "
    )
    text += (
        f"لانگ {longs} · شورت {shorts} · میانگین R {avg_r:.2f} · "
        f"بیشترین افت {max_dd:.2f}R · باخت پیاپی {max_streak}"
    )
    return {
        "trades": n,
        "win_rate": len(wins) / n,
        "profit_factor": pf,
        "longs": longs,
        "shorts": shorts,
        "avg_r": avg_r,
        "max_dd_r": max_dd,
        "max_loss_streak": max_streak,
        "text": text,
    }


def pairs_for_engine(
    entry_bars: list[OhlcBar],
    trades: list[tuple[int, SetupView, TradeStat]],
    scenario: dict[str, Any],
    timeframe: str,
) -> list[tuple[int, PatternHit]]:
    hits: list[tuple[int, PatternHit]] = []
    for i, setup, stat in trades:
        direction = "up" if setup.direction == "long" else "down"
        hit = PatternHit(
            category="scalp",
            timeframe=timeframe,
            pattern_id="scalp_nabzbours",
            title_fa=scenario.get("title_fa") or "نبض‌بورس",
            status_fa="بکتست",
            summary_fa=setup.log.replace("\n", " · "),
            forecast_fa=f"{stat.exit_reason} · R {stat.r_multiple:+.2f}",
            meta={
                "scenario_id": "nabzbours",
                "direction": direction,
                "entry_px": setup.entry,
                "stop_px": setup.stop,
                "tp_px": setup.tp,
                "entry_index": i,
                "confirm_index": i,
                "setup_key": f"{setup.direction}:{i}",
                "score": setup.score,
                "signal_log": setup.log,
                "exit_log": stat.exit_log,
                "exit_reason": stat.exit_reason,
                "r_multiple": stat.r_multiple,
                "nabz_done": True,
                "nabz_win": stat.win,
                "max_hold_bars": 1,
            },
        )
        hits.append((i, hit))
    return hits
