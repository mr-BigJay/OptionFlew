from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from optionflow.scenario_chart import fetch_btcusdt_klines


@dataclass
class OhlcBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def load_btcusdt(interval: str, limit: int = 200) -> list[OhlcBar]:
    raw = fetch_btcusdt_klines(interval=interval, limit=limit)
    return [
        OhlcBar(b.ts, b.open, b.high, b.low, b.close, 0.0)
        for b in raw
    ]


def load_btcusdt_before(interval: str, before_unix: int, limit: int = 500) -> list[OhlcBar]:
    """کندل‌های قبل از before_unix (ثانیه)."""
    import httpx

    from optionflow.scenario_chart import BINANCE_KLINES_MIRROR, BINANCE_KLINES_PRIMARY

    end_ms = int(before_unix) * 1000 - 1
    params = {
        "symbol": "BTCUSDT",
        "interval": interval,
        "limit": max(1, min(int(limit), 1000)),
        "endTime": end_ms,
    }
    last_err: Exception | None = None
    raw = None
    for url in (BINANCE_KLINES_PRIMARY, BINANCE_KLINES_MIRROR):
        try:
            r = httpx.get(url, params=params, timeout=45.0)
            r.raise_for_status()
            raw = r.json()
            break
        except Exception as e:
            last_err = e
    if raw is None:
        if last_err:
            raise last_err
        return []
    out: list[OhlcBar] = []
    for k in raw:
        ts_ms = int(k[0])
        if ts_ms >= end_ms + 1:
            continue
        out.append(
            OhlcBar(
                ts=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            )
        )
    return out
