from __future__ import annotations

from datetime import datetime, timezone

from optionflow.patterns.history import (
    _1m_cache_summary,
    _last_1m_bar,
    _save_1m_segment,
    history_data_dir,
    load_cached_bars,
)
from optionflow.patterns.ohlc import OhlcBar


def _bar(minute: int) -> OhlcBar:
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + __import__(
        "datetime"
    ).timedelta(minutes=minute)
    return OhlcBar(ts=ts, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


def test_1m_segments_save_and_summary(tmp_path):
    hist = history_data_dir(tmp_path)
    _save_1m_segment(hist, [_bar(0), _bar(1)])
    _save_1m_segment(hist, [_bar(2), _bar(3)])
    summary = _1m_cache_summary(hist)
    assert summary["count"] == 4
    assert summary["from_iso"]
    assert summary["to_iso"]
    last = _last_1m_bar(hist)
    assert last is not None
    assert last.ts.minute == 3
    bars = load_cached_bars(hist, "1m")
    assert len(bars) == 4
