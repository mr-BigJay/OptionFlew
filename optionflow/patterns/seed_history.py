from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from optionflow.patterns.history import (
    BACKTEST_INTERVALS,
    DEFAULT_HISTORY_DAYS,
    ProgressCallback,
    _1m_cache_summary,
    download_and_cache,
    expected_sync_utc_day_str,
    history_data_dir,
    record_daily_sync_failure,
    record_daily_sync_success,
    sync_interval_incremental,
)

logger = logging.getLogger("optionflow.patterns.seed")


def seed_btc_history(
    data_base: Path,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
    intervals: tuple[str, ...] | None = None,
    on_interval_progress: Callable[[str, int, str], None] | None = None,
) -> dict[str, int]:
    """دانلود/merge کش — فقط بازهٔ جدید وقتی کش وجود دارد."""
    end = datetime.now(timezone.utc)
    hist = history_data_dir(data_base)
    ivs = intervals or BACKTEST_INTERVALS
    counts: dict[str, int] = {}
    total = len(ivs)
    for n, iv in enumerate(ivs):
        base_pct = int(n * 100 / total)
        span = int(100 / total) if total else 100

        def _cb(pct: int, msg: str, _iv: str = iv, _b: int = base_pct, _s: int = span) -> None:
            if on_interval_progress:
                on_interval_progress(_iv, min(99, _b + int(pct * _s / 100)), msg)

        logger.info("Sync BTC history %s (incremental when cached)", iv)
        bars, _ = sync_interval_incremental(
            hist,
            iv,
            end=end,
            backfill_days=days,
            on_progress=_cb if on_interval_progress else None,
            progress_base=0,
            progress_span=100,
        )
        if iv == "1m":
            counts[iv] = int(_1m_cache_summary(hist).get("count") or 0)
        else:
            counts[iv] = len(bars)
        if on_interval_progress:
            on_interval_progress(iv, int((n + 1) * 100 / total), "تمام")
    return counts


def run_daily_candle_sync(data_base: Path, *, days: int = DEFAULT_HISTORY_DAYS) -> None:
    """پس از پایان روز UTC — همگام‌سازی روز قبل (کرون ۰۳:۳۰ تهران)."""
    hist = history_data_dir(data_base)
    utc_day = expected_sync_utc_day_str()
    ok: list[str] = []
    try:
        for iv in BACKTEST_INTERVALS:
            logger.info("Daily candle sync %s for UTC day %s", iv, utc_day)
            sync_interval_incremental(hist, iv, backfill_days=days)
            ok.append(iv)
        record_daily_sync_success(hist, utc_day=utc_day, intervals=tuple(ok))
        logger.info("Daily candle sync OK for %s (%d intervals)", utc_day, len(ok))
    except Exception as e:
        logger.exception("Daily candle sync failed")
        record_daily_sync_failure(hist, error=str(e), failed_interval=ok[-1] if ok else "")
        raise


def seed_btc_history_full_range(
    data_base: Path,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
    intervals: tuple[str, ...] | None = None,
    on_interval_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Force full-range download (used rarely; prefer seed_btc_history)."""
    from datetime import timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    hist = history_data_dir(data_base)
    ivs = intervals or BACKTEST_INTERVALS
    counts: dict[str, int] = {}
    for iv in ivs:
        bars, _ = download_and_cache(
            hist,
            iv,
            start,
            end,
            on_progress=on_interval_progress,
        )
        counts[iv] = len(bars)
    return counts
