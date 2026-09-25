from __future__ import annotations

from datetime import datetime, timedelta, timezone

from optionflow.patterns.history import (
    bars_cover_completed_utc_day,
    cache_status,
    history_data_dir,
    interval_is_fresh,
    last_completed_utc_day,
    save_cached_bars,
)
from optionflow.patterns.ohlc import OhlcBar


def _bar(ts: datetime, price: float = 1.0) -> OhlcBar:
    return OhlcBar(ts=ts, open=price, high=price, low=price, close=price, volume=1.0)


def test_bars_cover_completed_utc_day_daily(tmp_path):
    day = last_completed_utc_day()
    bars = [_bar(day.replace(hour=0))]
    assert bars_cover_completed_utc_day(bars, "1d") is True


def test_interval_fresh_when_through_yesterday(tmp_path):
    hist = history_data_dir(tmp_path)
    day = last_completed_utc_day()
    start = day - timedelta(days=800)
    bars = []
    t = start
    while t <= day + timedelta(hours=23):
        bars.append(_bar(t))
        t += timedelta(hours=1)
    save_cached_bars(hist, "1h", bars)
    assert interval_is_fresh(hist, "1h", target_days=730) is True
    rows = cache_status(tmp_path, target_days=730)
    row = next(r for r in rows if r["interval"] == "1h")
    assert row["status_fa"] == "بروز می باشد"


def test_stale_when_last_bar_old(tmp_path):
    hist = history_data_dir(tmp_path)
    old = last_completed_utc_day() - timedelta(days=5)
    bars = [_bar(old)]
    save_cached_bars(hist, "5m", bars)
    assert interval_is_fresh(hist, "5m", target_days=730) is False
    rows = cache_status(tmp_path, target_days=730)
    row = next(r for r in rows if r["interval"] == "5m")
    assert row["status_fa"] == "قدیمی است"
