from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

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

BACKTEST_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")

INTERVAL_LABEL_FA = {
    "1m": "۱ دقیقه",
    "5m": "۵ دقیقه",
    "15m": "۱۵ دقیقه",
    "1h": "۱ ساعت",
    "4h": "۴ ساعت",
    "1d": "روزانه",
}

ProgressCallback = Callable[[int, str], None]

DEFAULT_HISTORY_DAYS = 730

SYNC_META_FILENAME = "sync_meta.json"


def history_data_dir(base: Path) -> Path:
    d = base / "btc_history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_file(data_dir: Path, interval: str) -> Path:
    return data_dir / f"btcusdt_{interval}.json.gz"


def _sync_meta_path(data_dir: Path) -> Path:
    return data_dir / SYNC_META_FILENAME


def utc_day_start(dt: datetime) -> datetime:
    u = dt.astimezone(timezone.utc)
    return u.replace(hour=0, minute=0, second=0, microsecond=0)


def last_completed_utc_day() -> datetime:
    """Start of the last fully completed UTC calendar day."""
    today = utc_day_start(datetime.now(timezone.utc))
    return today - timedelta(days=1)


def expected_sync_utc_day_str() -> str:
    return last_completed_utc_day().strftime("%Y-%m-%d")


def load_sync_meta(data_dir: Path) -> dict[str, Any]:
    path = _sync_meta_path(data_dir)
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not read sync meta %s: %s", path, e)
        return {}


def save_sync_meta(data_dir: Path, meta: dict[str, Any]) -> None:
    path = _sync_meta_path(data_dir)
    meta = {**meta, "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def record_daily_sync_success(data_dir: Path, *, utc_day: str, intervals: tuple[str, ...]) -> None:
    prev = load_sync_meta(data_dir)
    ok = set(prev.get("intervals_ok") or [])
    ok.update(intervals)
    save_sync_meta(
        data_dir,
        {
            "last_success_utc_day": utc_day,
            "intervals_ok": sorted(ok),
            "last_error": "",
        },
    )


def record_daily_sync_failure(data_dir: Path, *, error: str, failed_interval: str = "") -> None:
    prev = load_sync_meta(data_dir)
    save_sync_meta(
        data_dir,
        {
            "last_success_utc_day": prev.get("last_success_utc_day", ""),
            "intervals_ok": prev.get("intervals_ok") or [],
            "last_error": error[:500],
            "last_failed_interval": failed_interval,
            "last_failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )


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


def _estimate_pages(interval: str, start: datetime, end: datetime) -> int:
    if end <= start:
        return 1
    step = INTERVAL_MS[interval]
    span_ms = int(end.timestamp() * 1000) - int(start.timestamp() * 1000)
    bars = max(1, span_ms // step)
    return max(1, (bars + MAX_KLINES - 1) // MAX_KLINES)


def fetch_klines_range(
    interval: str,
    start: datetime,
    end: datetime,
    *,
    on_progress: ProgressCallback | None = None,
    progress_base: int = 0,
    progress_span: int = 100,
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
    total_pages = _estimate_pages(interval, start, end)
    page = 0

    while cursor < end_ms:
        raw = _fetch_page(interval, cursor, end_ms)
        page += 1
        if on_progress and total_pages > 0:
            pct = progress_base + int(page * progress_span / total_pages)
            on_progress(min(progress_base + progress_span, pct), f"صفحه {page}/{total_pages}")
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


def incremental_fetch_start(bars: list[OhlcBar], interval: str) -> datetime | None:
    """First timestamp to request when appending; None if nothing new needed."""
    if not bars:
        return None
    step_ms = INTERVAL_MS[interval]
    last_ms = int(bars[-1].ts.timestamp() * 1000)
    return datetime.fromtimestamp((last_ms + step_ms) / 1000, tz=timezone.utc)


def download_and_cache(
    data_dir: Path,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    on_progress: ProgressCallback | None = None,
    progress_base: int = 0,
    progress_span: int = 100,
) -> tuple[list[OhlcBar], Path]:
    cached = load_cached_bars(data_dir, interval)
    fetched = fetch_klines_range(
        interval,
        start,
        end,
        on_progress=on_progress,
        progress_base=progress_base,
        progress_span=progress_span,
    )
    merged = merge_bars(cached, fetched)
    path = save_cached_bars(data_dir, interval, merged)
    return merged, path


def sync_interval_incremental(
    data_dir: Path,
    interval: str,
    *,
    end: datetime | None = None,
    backfill_days: int = DEFAULT_HISTORY_DAYS,
    on_progress: ProgressCallback | None = None,
    progress_base: int = 0,
    progress_span: int = 100,
) -> tuple[list[OhlcBar], bool]:
    """Append only missing bars. Full backfill when cache is empty."""
    if end is None:
        end = datetime.now(timezone.utc)
    cached = load_cached_bars(data_dir, interval)
    if not cached:
        start = end - timedelta(days=backfill_days)
    else:
        inc_start = incremental_fetch_start(cached, interval)
        if inc_start is None or inc_start >= end:
            if on_progress:
                on_progress(progress_base + progress_span, "به‌روز")
            return cached, False
        start = inc_start
    merged, _ = download_and_cache(
        data_dir,
        interval,
        start,
        end,
        on_progress=on_progress,
        progress_base=progress_base,
        progress_span=progress_span,
    )
    return merged, True


def bars_cover_completed_utc_day(bars: list[OhlcBar], interval: str) -> bool:
    if not bars:
        return False
    day = last_completed_utc_day()
    day_end = day + timedelta(days=1) - timedelta(milliseconds=1)
    last_bar = bars[-1].ts.astimezone(timezone.utc)
    if interval == "1d":
        return last_bar.date() >= day.date()
    return last_bar >= day_end - timedelta(milliseconds=INTERVAL_MS[interval])


def _needs_initial_depth(bars: list[OhlcBar], *, target_days: int) -> bool:
    if not bars:
        return True
    now = datetime.now(timezone.utc)
    want_start = now - timedelta(days=target_days)
    from_dt = bars[0].ts.astimezone(timezone.utc)
    to_dt = bars[-1].ts.astimezone(timezone.utc)
    shallow = from_dt > want_start + timedelta(days=14)
    span_days = (to_dt - from_dt).total_seconds() / 86400.0
    enough_bars = len(bars) >= max(50, target_days - 20)
    deep_enough = span_days >= target_days - 25
    return shallow or not (enough_bars and deep_enough)


def interval_is_fresh(
    data_dir: Path,
    interval: str,
    *,
    target_days: int = DEFAULT_HISTORY_DAYS,
) -> bool:
    """داده تا پایان آخرین روز UTC کامل + عمق کافی برای بکتست."""
    bars = load_cached_bars(data_dir, interval)
    if not bars or _needs_initial_depth(bars, target_days=target_days):
        return False
    return bars_cover_completed_utc_day(bars, interval)


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


def cache_status(data_dir: Path, *, target_days: int = DEFAULT_HISTORY_DAYS) -> list[dict[str, Any]]:
    """وضعیت کش هر تایم‌فریم برای UI ذخیرهٔ کندل."""
    hist = history_data_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for iv in BACKTEST_INTERVALS:
        path = _cache_file(hist, iv)
        bars = load_cached_bars(hist, iv) if path.is_file() else []
        if not bars:
            rows.append(
                {
                    "interval": iv,
                    "label_fa": INTERVAL_LABEL_FA.get(iv, iv),
                    "count": 0,
                    "from_iso": "",
                    "to_iso": "",
                    "file_exists": path.is_file(),
                    "status": "missing",
                    "status_fa": "ذخیره نشده",
                    "needs_download": True,
                }
            )
            continue
        from_dt = bars[0].ts.astimezone(timezone.utc)
        to_dt = bars[-1].ts.astimezone(timezone.utc)
        fresh = interval_is_fresh(hist, iv, target_days=target_days)
        if fresh:
            status, status_fa, needs = "ok", "بروز می باشد", False
        else:
            status, status_fa, needs = "stale", "قدیمی است", True
        rows.append(
            {
                "interval": iv,
                "label_fa": INTERVAL_LABEL_FA.get(iv, iv),
                "count": len(bars),
                "from_iso": from_dt.isoformat().replace("+00:00", "Z"),
                "to_iso": to_dt.isoformat().replace("+00:00", "Z"),
                "file_exists": True,
                "status": status,
                "status_fa": status_fa,
                "needs_download": needs,
            }
        )
    return rows
