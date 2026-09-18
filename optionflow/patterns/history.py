from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from optionflow.patterns.ohlc import OhlcBar
from optionflow.scenario_chart import BINANCE_KLINES_MIRROR, BINANCE_KLINES_PRIMARY

logger = logging.getLogger("optionflow.patterns.history")

MAX_KLINES = 1000
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def history_data_dir(base: Path) -> Path:
    d = base / "btc_history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_file(data_dir: Path, interval: str) -> Path:
    return data_dir / f"btcusdt_{interval}.json.gz"


def _bar_to_row(b: OhlcBar) -> list[Any]:
    return [
        b.ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        b.open,
        b.high,
        b.low,
        b.close,
        b.volume,
    ]


def _row_to_bar(row: list[Any]) -> OhlcBar:
    ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    return OhlcBar(
        ts=ts,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]) if len(row) > 5 else 0.0,
    )


def load_cached_bars(data_dir: Path, interval: str) -> list[OhlcBar]:
    path = _cache_file(data_dir, interval)
    if not path.is_file():
        return []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        return [_row_to_bar(r) for r in payload.get("bars", [])]
    except Exception as e:
        logger.warning("Could not read history cache %s: %s", path, e)
        return []


def save_cached_bars(data_dir: Path, interval: str, bars: list[OhlcBar]) -> Path:
    path = _cache_file(data_dir, interval)
    uniq: dict[int, OhlcBar] = {}
    for b in bars:
        uniq[int(b.ts.timestamp() * 1000)] = b
    merged = [uniq[k] for k in sorted(uniq)]
    payload = {
        "symbol": "BTCUSDT",
        "interval": interval,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(merged),
        "bars": [_bar_to_row(b) for b in merged],
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    return path


def _fetch_page(interval: str, start_ms: int, end_ms: int | None) -> list[list[Any]]:
    params: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "interval": interval,
        "limit": MAX_KLINES,
        "startTime": start_ms,
    }
    if end_ms is not None:
        params["endTime"] = end_ms
    last_err: Exception | None = None
    for url in (BINANCE_KLINES_PRIMARY, BINANCE_KLINES_MIRROR):
        try:
            r = httpx.get(url, params=params, timeout=60.0)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return []


def fetch_klines_range(
    interval: str,
    start: datetime,
    end: datetime,
) -> list[OhlcBar]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        return []

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step = INTERVAL_MS[interval]
    out: list[OhlcBar] = []
    cursor = start_ms

    while cursor < end_ms:
        raw = _fetch_page(interval, cursor, end_ms)
        if not raw:
            break
        for k in raw:
            ts_ms = int(k[0])
            if ts_ms > end_ms:
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
        last_open = int(raw[-1][0])
        next_cursor = last_open + step
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(raw) < MAX_KLINES:
            break

    return out


def merge_bars(existing: list[OhlcBar], new: list[OhlcBar]) -> list[OhlcBar]:
    by_ts = {int(b.ts.timestamp() * 1000): b for b in existing}
    for b in new:
        by_ts[int(b.ts.timestamp() * 1000)] = b
    return [by_ts[k] for k in sorted(by_ts)]


def download_and_cache(
    data_dir: Path,
    interval: str,
    start: datetime,
    end: datetime,
) -> tuple[list[OhlcBar], Path]:
    cached = load_cached_bars(data_dir, interval)
    fetched = fetch_klines_range(interval, start, end)
    merged = merge_bars(cached, fetched)
    path = save_cached_bars(data_dir, interval, merged)
    return merged, path


def bars_in_range(bars: list[OhlcBar], start: datetime, end: datetime) -> list[OhlcBar]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return [b for b in bars if start <= b.ts <= end]


def slice_with_warmup(
    bars: list[OhlcBar],
    start: datetime,
    end: datetime,
    warmup: int = 160,
) -> tuple[list[OhlcBar], int, int]:
    """Return full series for replay, first scan index, last scan index (inclusive)."""
    if not bars:
        return [], 0, -1
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    first_in = None
    last_in = None
    for i, b in enumerate(bars):
        if b.ts >= start and first_in is None:
            first_in = i
        if b.ts <= end:
            last_in = i
    if first_in is None or last_in is None or last_in < first_in:
        return bars, 0, -1

    scan_start = max(first_in, warmup)
    return bars, scan_start, last_in
