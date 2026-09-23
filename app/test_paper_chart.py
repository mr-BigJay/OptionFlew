from datetime import datetime, timedelta, timezone

from app.paper_chart import _reanchor_meta
from optionflow.patterns.ohlc import OhlcBar

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _bar(i: int, close: float) -> OhlcBar:
    return OhlcBar(
        ts=_T0 + timedelta(hours=i),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
    )


def test_reanchor_meta_shifts_with_event_time() -> None:
    bars = [_bar(i, 100.0 + i) for i in range(30)]
    meta = {
        "window_offset": 10,
        "end_i": 19,
        "confirm_index": 28,
        "early_index": 22,
        "start_i": 0,
        "touch_lows": [2, 8],
    }
    ev = {"created_at": bars[28].ts.isoformat().replace("+00:00", "Z")}
    out = _reanchor_meta(bars, meta, ev)
    assert out["window_offset"] == 10
    assert out["confirm_index"] == 28

    ev2 = {"created_at": bars[25].ts.isoformat().replace("+00:00", "Z")}
    out2 = _reanchor_meta(bars, meta, ev2)
    assert out2["confirm_index"] == 25
    assert out2["window_offset"] == 7