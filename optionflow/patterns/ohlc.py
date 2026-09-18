from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
