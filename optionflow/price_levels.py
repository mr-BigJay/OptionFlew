from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

BINANCE = "https://api.binance.com"
DERIBIT = "https://www.deribit.com/api/v2/public"


@dataclass(frozen=True)
class PriceLevels:
    pdh: int | None
    pdl: int | None
    pwh: int | None
    pwl: int | None


def _closed_candle_hl(candles: list, index: int = -2) -> tuple[int, int] | None:
    if len(candles) < 2:
        return None
    try:
        c = candles[index]
        high = int(round(float(c[2])))
        low = int(round(float(c[3])))
        return high, low
    except (IndexError, TypeError, ValueError):
        return None


def _from_deribit_perp() -> PriceLevels:
    end = int(time.time() * 1000)
    start = end - 30 * 86400000
    r = httpx.get(
        f"{DERIBIT}/get_tradingview_chart_data",
        params={
            "instrument_name": "BTC-PERPETUAL",
            "start_timestamp": start,
            "end_timestamp": end,
            "resolution": "1D",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    payload = r.json().get("result") or {}
    highs = payload.get("high") or []
    lows = payload.get("low") or []
    if len(highs) < 2 or len(lows) < 2:
        return PriceLevels(None, None, None, None)

    pdh = int(round(float(highs[-2])))
    pdl = int(round(float(lows[-2])))
    pwh = pwl = None
    if len(highs) >= 9:
        window_h = highs[-9:-2]
        window_l = lows[-9:-2]
        pwh = int(round(max(float(x) for x in window_h)))
        pwl = int(round(min(float(x) for x in window_l)))

    return PriceLevels(pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl)


def _from_binance() -> PriceLevels | None:
    try:
        with httpx.Client(timeout=20.0) as client:
            day = client.get(
                f"{BINANCE}/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": 5},
            )
            week = client.get(
                f"{BINANCE}/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1w", "limit": 5},
            )
        if day.status_code != 200:
            return None
        d = _closed_candle_hl(day.json())
        w = _closed_candle_hl(week.json()) if week.status_code == 200 else None
    except Exception:
        return None

    pdh = pdl = pwh = pwl = None
    if d:
        pdh, pdl = d
    if w:
        pwh, pwl = w
    return PriceLevels(pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl)


def fetch_price_levels() -> PriceLevels:
    """PDH/PDL from last closed daily bar; PWH/PWL from prior 7 daily bars (Deribit BTC-PERPETUAL)."""
    try:
        levels = _from_deribit_perp()
        if levels.pdh is not None:
            return levels
    except Exception:
        pass
    fallback = _from_binance()
    if fallback:
        return fallback
    return PriceLevels(None, None, None, None)
