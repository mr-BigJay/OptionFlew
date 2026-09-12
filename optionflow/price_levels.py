from __future__ import annotations

from dataclasses import dataclass

import httpx

BINANCE = "https://api.binance.com"


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


def fetch_price_levels() -> PriceLevels:
    """PDH/PDL and PWH/PWL from last closed Binance BTCUSDT daily/weekly candles (UTC)."""
    try:
        with httpx.Client(timeout=20.0) as client:
            day = client.get(
                f"{BINANCE}/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": 5},
            )
            if day.status_code == 200:
                d = _closed_candle_hl(day.json())
            else:
                d = None
            week = client.get(
                f"{BINANCE}/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1w", "limit": 5},
            )
            if week.status_code == 200:
                w = _closed_candle_hl(week.json())
            else:
                w = None
    except Exception:
        d = w = None

    pdh = pdl = pwh = pwl = None
    if d:
        pdh, pdl = d
    if w:
        pwh, pwl = w
    return PriceLevels(pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl)
