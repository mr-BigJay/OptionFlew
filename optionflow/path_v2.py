"""مسیر v2. ربات گزارش را عوض نمی‌کند.

جهت از حق‌بیمهٔ دو ساعت اخیر می‌آید. چهار سطح جدا هستند.
اگر گاما نزدیک قیمت جمع باشد و جریان یک‌طرفه نباشد، مسیر آرام به آهنربا می‌رود.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from optionflow.deribit_client import DeribitClient
from optionflow.expiry_compass import expiry_datetime, fetch_book

WINDOW_HOURS = 2.0
SIDE_RATIO = 1.15
MIN_MOVE = 0.0015
NEAR_PCT = 0.02
BAND_PCT = 0.12
PIN_SPAN = 0.015
PIN_SHARE = 0.35
PIN_NEAR = 0.015
_CACHE_TTL = 90.0

_cache_at = 0.0
_cache_value: "PathV2 | None" = None
_cache_ready = False


@dataclass(frozen=True)
class PathV2:
    spot: float
    side: str  # up | down | pin | ""
    target: int | None
    expiry: str
    expiry_unix: int
    scg: int | None
    bcg: int | None
    bps: int | None
    sps: int | None
    bull_premium: float
    bear_premium: float


def premium_usd(trade: dict[str, Any]) -> float:
    """حق بیمه به دلار: مقدار × قیمت آپشن × شاخص. نه قرارداد × اسپات."""
    try:
        amount = float(trade.get("amount") or 0)
        price = float(trade.get("price") or 0)
        index = float(trade.get("index_price") or 0)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0 or price <= 0 or index <= 0:
        return 0.0
    return amount * price * index


def _parse(name: str) -> tuple[str, float, str] | None:
    parts = name.split("-")
    if len(parts) < 4:
        return None
    try:
        strike = float(parts[2])
    except ValueError:
        return None
    opt = "call" if parts[3].upper().startswith("C") else "put"
    return parts[1], strike, opt


def _nearest_expiry(
    books: list[dict[str, Any]], now: datetime
) -> tuple[str, datetime] | None:
    best: tuple[str, datetime] | None = None
    seen: set[str] = set()
    for row in books:
        parsed = _parse(str(row.get("instrument_name") or ""))
        if parsed is None or parsed[0] in seen:
            continue
        seen.add(parsed[0])
        try:
            when = expiry_datetime(parsed[0])
        except ValueError:
            continue
        if (when - now).total_seconds() < 0.5 * 3600:
            continue
        if best is None or when < best[1]:
            best = (parsed[0], when)
    return best


def _in_band(strike: float, spot: float) -> bool:
    return spot > 0 and abs(strike - spot) / spot <= BAND_PCT


def _away(strike: float, spot: float, way: str) -> bool:
    """استرایک چسبیده به قیمت مقصد نیست."""
    if spot <= 0 or abs(strike - spot) / spot < MIN_MOVE:
        return False
    if way == "up":
        return strike > spot
    return strike < spot


def _best(weights: dict[float, float], pred) -> float | None:
    chosen: float | None = None
    weight = 0.0
    for strike, w in weights.items():
        if w <= 0 or not pred(strike):
            continue
        if w > weight:
            weight = w
            chosen = strike
    return chosen


def _flow(
    trades: list[dict[str, Any]], expiry: str, spot: float
) -> tuple[float, float, dict[str, float | None]]:
    bull = bear = 0.0
    call_buy: dict[float, float] = {}
    call_sell: dict[float, float] = {}
    put_buy: dict[float, float] = {}
    put_sell: dict[float, float] = {}
    for trade in trades:
        parsed = _parse(str(trade.get("instrument_name") or ""))
        if parsed is None:
            continue
        prem = premium_usd(trade)
        if prem <= 0:
            continue
        code, strike, opt = parsed
        direction = str(trade.get("direction") or "")
        if direction == "buy" and opt == "call":
            bull += prem
            bucket = call_buy
        elif direction == "sell" and opt == "put":
            bull += prem
            bucket = put_sell
        elif direction == "buy" and opt == "put":
            bear += prem
            bucket = put_buy
        elif direction == "sell" and opt == "call":
            bear += prem
            bucket = call_sell
        else:
            continue
        if code == expiry and _in_band(strike, spot):
            bucket[strike] = bucket.get(strike, 0.0) + prem
    levels = {
        "scg": _best(call_sell, lambda k: _away(k, spot, "up")),
        "bcg": _best(call_buy, lambda k: abs(k - spot) / spot <= NEAR_PCT),
        "bps": _best(put_buy, lambda k: _away(k, spot, "down")),
        "sps": _best(put_sell, lambda k: _away(k, spot, "down")),
    }
    return bull, bear, levels


def _oi_levels(
    books: list[dict[str, Any]], expiry: str, spot: float
) -> dict[str, float | None]:
    call_above: dict[float, float] = {}
    call_near: dict[float, float] = {}
    put_below: dict[float, float] = {}
    for row in books:
        parsed = _parse(str(row.get("instrument_name") or ""))
        if parsed is None or parsed[0] != expiry:
            continue
        _, strike, opt = parsed
        if not _in_band(strike, spot):
            continue
        oi = float(row.get("open_interest") or 0)
        if oi <= 0:
            continue
        if opt == "call" and _away(strike, spot, "up"):
            call_above[strike] = call_above.get(strike, 0.0) + oi
        if opt == "call" and abs(strike - spot) / spot <= NEAR_PCT:
            call_near[strike] = call_near.get(strike, 0.0) + oi
        if opt == "put" and _away(strike, spot, "down"):
            put_below[strike] = put_below.get(strike, 0.0) + oi
    bps = _best(put_below, lambda k: _away(k, spot, "down"))
    sps = _best(put_below, lambda k: bps is None or k < bps - 1)
    if sps is None:
        sps = bps
    return {
        "scg": _best(call_above, lambda k: k > spot),
        "bcg": _best(call_near, lambda k: True),
        "bps": bps,
        "sps": sps,
    }


def _near_weights(
    books: list[dict[str, Any]],
    expiry: str,
    spot: float,
    greeks: dict[str, float],
) -> dict[float, float]:
    out: dict[float, float] = {}
    for row in books:
        name = str(row.get("instrument_name") or "")
        parsed = _parse(name)
        if parsed is None or parsed[0] != expiry:
            continue
        _, strike, _opt = parsed
        if spot <= 0 or abs(strike - spot) / spot > 0.06:
            continue
        oi = float(row.get("open_interest") or 0)
        if oi <= 0:
            continue
        gamma = abs(float(greeks.get(name) or 0))
        out[strike] = out.get(strike, 0.0) + oi * (1.0 + gamma * spot)
    return out


def _pinned(weights: dict[float, float], spot: float) -> bool:
    ordered = sorted((k, w) for k, w in weights.items() if w > 0)
    if not ordered or spot <= 0:
        return False
    total = sum(w for _, w in ordered)
    best_w = 0.0
    best_mid: float | None = None
    for i, (start, _) in enumerate(ordered):
        window: list[tuple[float, float]] = []
        weight = 0.0
        for strike, w in ordered[i:]:
            if strike > start * (1.0 + PIN_SPAN):
                break
            window.append((strike, w))
            weight += w
        if weight > best_w:
            best_w = weight
            best_mid = max(window, key=lambda item: item[1])[0]
    if best_mid is None or total <= 0:
        return False
    return best_w / total >= PIN_SHARE and abs(best_mid - spot) / spot <= PIN_NEAR


def _flow_side(bull: float, bear: float) -> str:
    if bull <= 0 and bear <= 0:
        return ""
    if bull >= bear * SIDE_RATIO:
        return "up"
    if bear >= bull * SIDE_RATIO:
        return "down"
    return "balanced"


def _as_int(strike: float | None) -> int | None:
    if strike is None:
        return None
    return int(round(strike))


def _usable(strike: int | None, spot: float, way: str) -> int | None:
    if strike is None or spot <= 0:
        return None
    if abs(strike - spot) / spot < MIN_MOVE:
        return None
    if way == "up" and strike <= spot:
        return None
    if way == "down" and strike >= spot:
        return None
    return strike


def build_path_v2(
    *,
    books: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    spot: float,
    now: datetime | None = None,
    greeks: dict[str, float] | None = None,
) -> PathV2 | None:
    if spot <= 0 or not books:
        return None
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    found = _nearest_expiry(books, moment)
    if found is None:
        return None
    expiry, when = found
    bull, bear, tape = _flow(trades, expiry, spot)
    oi = _oi_levels(books, expiry, spot)
    levels = {
        key: _as_int(tape[key] if tape[key] is not None else oi[key])
        for key in ("scg", "bcg", "bps", "sps")
    }
    flow = _flow_side(bull, bear)
    pinned = _pinned(_near_weights(books, expiry, spot, greeks or {}), spot)
    side = ""
    target: int | None = None
    if flow == "up":
        side = "up"
        target = _usable(levels["scg"], spot, "up") or _usable(levels["bcg"], spot, "up")
    elif flow == "down":
        side = "down"
        target = _usable(levels["bps"], spot, "down") or _usable(levels["sps"], spot, "down")
    elif pinned:
        side = "pin"
        target = _usable(levels["bcg"], spot, "up") or _usable(levels["bcg"], spot, "down")
    return PathV2(
        spot=spot,
        side=side,
        target=target,
        expiry=expiry,
        expiry_unix=int(when.timestamp()),
        scg=levels["scg"],
        bcg=levels["bcg"],
        bps=levels["bps"],
        sps=levels["sps"],
        bull_premium=bull,
        bear_premium=bear,
    )


def path_line(
    spot: float,
    target: int | None,
    start_unix: int,
    end_unix: int,
    *,
    drift: str = "linear",
    max_display_seconds: int | None = None,
) -> list[dict[str, float | int]]:
    """یک خط از الان تا سررسید. در رژیم pin شیب اول آرام است.

    max_display_seconds: فقط برای چارت — همان شیب تا سررسید، ولی نقاط تا این افق
    (تا fitContent کندل‌ها را له نکند).
    """
    if target is None or spot <= 0 or end_unix <= start_unix:
        return []
    if abs(target - spot) / spot < MIN_MOVE:
        return []
    span = end_unix - start_unix
    draw_until = end_unix
    if max_display_seconds is not None and max_display_seconds > 0:
        draw_until = min(end_unix, start_unix + int(max_display_seconds))
    if draw_until <= start_unix:
        return []
    step = max(900, min(3600, span // 24 or 3600))
    points: list[dict[str, float | int]] = []

    def _value_at(t: int) -> float:
        frac = (t - start_unix) / span
        if drift == "pin":
            frac = frac * frac
        return round(spot + (target - spot) * frac, 2)

    t = start_unix
    while t < draw_until:
        points.append({"time": t, "value": _value_at(t)})
        t += step
    if not points or points[-1]["time"] != draw_until:
        points.append({"time": draw_until, "value": _value_at(draw_until)})
    return points


def caption_fa(path: PathV2 | None) -> str:
    if path is None:
        return "v2 · مسیر مشخص نیست"
    if path.target is None:
        if path.side == "pin":
            return "v2 · قیمت روی آهنرباست"
        return "v2 · مسیر مشخص نیست"
    word = {"up": "صعودی", "down": "نزولی", "pin": "آهسته به آهنربا"}.get(path.side, "")
    return f"v2 · {word} تا {path.expiry} · {path.target:,}"


def _gamma_near(books: list[dict[str, Any]], spot: float, expiry: str) -> dict[str, float]:
    ranked: list[tuple[float, str]] = []
    for row in books:
        name = str(row.get("instrument_name") or "")
        parsed = _parse(name)
        if parsed is None or parsed[0] != expiry:
            continue
        oi = float(row.get("open_interest") or 0)
        if oi <= 0 or abs(parsed[1] - spot) / spot > 0.04:
            continue
        ranked.append((oi, name))
    ranked.sort(reverse=True)
    out: dict[str, float] = {}
    with httpx.Client(timeout=4.0) as client:
        for _oi, name in ranked[:12]:
            try:
                tr = client.get(
                    "https://www.deribit.com/api/v2/public/ticker",
                    params={"instrument_name": name},
                )
                if tr.status_code != 200:
                    continue
                gamma = float((tr.json().get("result") or {}).get("greeks", {}).get("gamma") or 0)
            except (TypeError, ValueError, httpx.HTTPError):
                continue
            if gamma:
                out[name] = gamma
    return out


def live_path_v2(now: datetime | None = None) -> PathV2 | None:
    global _cache_at, _cache_value, _cache_ready
    moment = now or datetime.now(timezone.utc)
    if _cache_ready and time.monotonic() - _cache_at < _CACHE_TTL:
        return _cache_value
    with DeribitClient() as client:
        spot = client.get_index_price()
        start_ms, end_ms = DeribitClient.window_ms(WINDOW_HOURS)
        trades = client.fetch_option_trades(
            start_ms=start_ms, end_ms=end_ms, max_trades=20_000
        )
    books = fetch_book()
    path = build_path_v2(books=books, trades=trades, spot=spot, now=moment)
    if path is not None:
        try:
            greeks = _gamma_near(books, spot, path.expiry)
        except httpx.HTTPError:
            greeks = {}
        if greeks:
            path = build_path_v2(
                books=books,
                trades=trades,
                spot=spot,
                now=moment,
                greeks=greeks,
            )
    _cache_value = path
    _cache_at = time.monotonic()
    _cache_ready = True
    return path
