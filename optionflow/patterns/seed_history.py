from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from optionflow.patterns.history import BACKTEST_INTERVALS, download_and_cache, history_data_dir

logger = logging.getLogger("optionflow.patterns.seed")

DEFAULT_HISTORY_DAYS = 730


def seed_btc_history(
    data_base: Path,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
    intervals: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """دانلود/merge کش چند تایم‌فریم برای بکتست (پیش‌فرض ~۲ سال)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    hist = history_data_dir(data_base)
    ivs = intervals or BACKTEST_INTERVALS
    counts: dict[str, int] = {}
    for iv in ivs:
        logger.info("Seeding BTC history %s from %s to %s", iv, start.date(), end.date())
        bars, _ = download_and_cache(hist, iv, start, end)
        counts[iv] = len(bars)
    return counts
