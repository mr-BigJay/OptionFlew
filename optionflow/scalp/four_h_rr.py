from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

NY = ZoneInfo("America/New_York")
FOUR_H = timedelta(hours=4)


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def ny_calendar_date(ts: datetime) -> date:
    return _aware(ts).astimezone(NY).date()


def ny_day_end_utc(d: date) -> datetime:
    """نیمه‌شب شروع روز بعد در NY → پایان روز معاملاتی d."""
    start_next = datetime(
        d.year, d.month, d.day, tzinfo=NY
    ) + timedelta(days=1)
    return start_next.astimezone(timezone.utc)


def first_ny_4h_bar(bars_4h: list[OhlcBar], trading_day: date) -> OhlcBar | None:
    """اولین کندل 4H که زمان باز شدنش در NY همان روز trading_day باشد."""
    cands = [b for b in bars_4h if ny_calendar_date(b.ts) == trading_day]
    if not cands:
        return None
    return min(cands, key=lambda b: _aware(b.ts))


def range_close_time(bar_4h: OhlcBar) -> datetime:
    return _aware(bar_4h.ts) + FOUR_H


def close_inside_range(close: float, range_low: float, range_high: float) -> bool:
    return range_low <= close <= range_high


@dataclass
class _ShortSetup:
    breakout_index: int
    breakout_high: float


@dataclass
class _LongSetup:
    breakout_index: int
    breakout_low: float


@dataclass
class _OpenTrade:
    direction: str
    entry_index: int
    entry_px: float
    stop_px: float
    tp_px: float


def _tp_from_r(
    direction: str, entry: float, stop: float, tp_rr: float
) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        risk = entry * 1e-6
    if direction == "up":
        return entry + tp_rr * risk
    return entry - tp_rr * risk


def _build_hit(
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    timeframe: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    confirm_i: int,
    range_low: float,
    range_high: float,
    trading_day: date,
    breakout_index: int,
    day_last: int,
) -> PatternHit:
    sid = scenario["scenario_id"]
    title = scenario.get("title_fa", sid)
    dir_fa = "Short" if direction == "down" else "Long"
    sk = f"{trading_day.isoformat()}:{direction}:{breakout_index}:{confirm_i}"
    return PatternHit(
        category="scalp",
        timeframe=timeframe,
        pattern_id=f"scalp_{sid}",
        title_fa=f"{title} · {dir_fa}",
        status_fa="فعال",
        summary_fa=(
            f"NY {trading_day.isoformat()} · Range 4H {range_low:,.0f}–{range_high:,.0f} · "
            f"ورود {entry:,.0f} · استاپ {stop:,.0f} · TP {tp:,.0f} (2R)"
        ),
        forecast_fa="خروج مکانیکی روی استاپ یا TP.",
        meta={
            "scenario_id": sid,
            "direction": direction,
            "entry_px": entry,
            "stop_px": stop,
            "tp_px": tp,
            "entry_index": confirm_i,
            "confirm_index": confirm_i,
            "breakout_index": breakout_index,
            "range_low": range_low,
            "range_high": range_high,
            "ny_trading_day": trading_day.isoformat(),
            "setup_key": sk,
            "stage": "active",
            "tp_rr": float(params.get("tp_rr", 2.0)),
            "max_hold_bars": max(1, day_last - confirm_i),
        },
    )


def _simulate_until_close(
    bars: list[OhlcBar],
    trade: _OpenTrade,
    day_last_index: int,
) -> int:
    """آخرین اندیس پرداز‌شده (خروج از معامله)."""
    for j in range(trade.entry_index + 1, day_last_index + 1):
        b = bars[j]
        if trade.direction == "down":
            if b.high >= trade.stop_px:
                return j
            if b.low <= trade.tp_px:
                return j
        else:
            if b.low <= trade.stop_px:
                return j
            if b.high >= trade.tp_px:
                return j
    return day_last_index


def scan_ny_day_4hrr(
    bars_5m: list[OhlcBar],
    bars_4h: list[OhlcBar],
    trading_day: date,
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    timeframe: str = "5m",
) -> list[tuple[int, PatternHit]]:
    """تمام سیگنال‌های یک روز NY با قانون یک معامله باز."""
    bar_4h = first_ny_4h_bar(bars_4h, trading_day)
    if bar_4h is None:
        return []
    range_low = float(bar_4h.low)
    range_high = float(bar_4h.high)
    r_close = range_close_time(bar_4h)
    day_end = ny_day_end_utc(trading_day)
    tp_rr = float(params.get("tp_rr", 2.0))

    day_indices: list[int] = []
    for i, b in enumerate(bars_5m):
        ts = _aware(b.ts)
        if ts < r_close:
            continue
        if ts >= day_end:
            break
        day_indices.append(i)
    if not day_indices:
        return []

    day_last = day_indices[-1]
    signals: list[tuple[int, PatternHit]] = []
    short_setup: _ShortSetup | None = None
    long_setup: _LongSetup | None = None
    open_trade: _OpenTrade | None = None
    scan_i = 0

    while scan_i < len(day_indices):
        i = day_indices[scan_i]
        b = bars_5m[i]

        if open_trade is not None:
            exit_i = _simulate_until_close(bars_5m, open_trade, day_last)
            open_trade = None
            scan_i = next(
                (k for k, idx in enumerate(day_indices) if idx > exit_i),
                len(day_indices),
            )
            short_setup = None
            long_setup = None
            continue

        c = b.close
        if c > range_high:
            short_setup = _ShortSetup(breakout_index=i, breakout_high=b.high)
        elif c < range_low:
            long_setup = _LongSetup(breakout_index=i, breakout_low=b.low)

        fired = False
        if short_setup is not None and close_inside_range(c, range_low, range_high):
            entry = c
            stop = short_setup.breakout_high
            tp = _tp_from_r("down", entry, stop, tp_rr)
            hit = _build_hit(
                scenario=scenario,
                params=params,
                timeframe=timeframe,
                direction="down",
                entry=entry,
                stop=stop,
                tp=tp,
                confirm_i=i,
                range_low=range_low,
                range_high=range_high,
                trading_day=trading_day,
                breakout_index=short_setup.breakout_index,
                day_last=day_last,
            )
            signals.append((i, hit))
            open_trade = _OpenTrade("down", i, entry, stop, tp)
            fired = True

        if not fired and long_setup is not None and close_inside_range(
            c, range_low, range_high
        ):
            entry = c
            stop = long_setup.breakout_low
            tp = _tp_from_r("up", entry, stop, tp_rr)
            hit = _build_hit(
                scenario=scenario,
                params=params,
                timeframe=timeframe,
                direction="up",
                entry=entry,
                stop=stop,
                tp=tp,
                confirm_i=i,
                range_low=range_low,
                range_high=range_high,
                trading_day=trading_day,
                breakout_index=long_setup.breakout_index,
                day_last=day_last,
            )
            signals.append((i, hit))
            open_trade = _OpenTrade("up", i, entry, stop, tp)
            fired = True

        if fired:
            short_setup = None
            long_setup = None

        scan_i += 1

    return signals


def iter_trading_days_in_range(
    bars_5m: list[OhlcBar], start: datetime, end: datetime
) -> list[date]:
    if not bars_5m:
        return []
    days: list[date] = []
    seen: set[date] = set()
    start_a = _aware(start)
    end_a = _aware(end)
    for b in bars_5m:
        ts = _aware(b.ts)
        if ts < start_a or ts > end_a:
            continue
        d = ny_calendar_date(ts)
        if d not in seen:
            seen.add(d)
            days.append(d)
    return sorted(days)


def scan_4hrr_backtest(
    bars_5m: list[OhlcBar],
    bars_4h: list[OhlcBar],
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    start: datetime,
    end: datetime,
    timeframe: str = "5m",
) -> list[tuple[int, PatternHit]]:
    out: list[tuple[int, PatternHit]] = []
    for d in iter_trading_days_in_range(bars_5m, start, end):
        for ix, hit in scan_ny_day_4hrr(
            bars_5m, bars_4h, d, scenario=scenario, params=params, timeframe=timeframe
        ):
            ts = _aware(bars_5m[ix].ts)
            if _aware(start) <= ts <= _aware(end):
                out.append((ix, hit))
    return out


def detect_4hrr_live(
    bars_5m: list[OhlcBar],
    bars_4h: list[OhlcBar],
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    timeframe: str = "5m",
) -> PatternHit | None:
    """سیگنال فقط اگر آخرین کندل 5m همان کندل تأیید ستاپ باشد."""
    if not bars_5m:
        return None
    today = ny_calendar_date(bars_5m[-1].ts)
    hits = scan_ny_day_4hrr(
        bars_5m, bars_4h, today, scenario=scenario, params=params, timeframe=timeframe
    )
    if not hits:
        return None
    last_i, hit = hits[-1]
    if last_i != len(bars_5m) - 1:
        return None
    return hit
