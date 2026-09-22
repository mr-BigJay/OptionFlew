from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from optionflow.patterns.ohlc import OhlcBar
from optionflow.scalp.four_h_rr import (
    first_ny_4h_bar,
    ny_calendar_date,
    scan_ny_day_4hrr,
)

NY = ZoneInfo("America/New_York")


def _bar(dt: datetime, o: float, h: float, lo: float, c: float) -> OhlcBar:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return OhlcBar(dt, o, h, lo, c, 1.0)


def test_first_ny_4h_is_earliest_open_that_day() -> None:
    d = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc)
    day = ny_calendar_date(d)
    early = datetime(2026, 3, 20, 4, 0, tzinfo=timezone.utc)
    late = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    bars = [
        _bar(late, 1, 2, 0.5, 1.5),
        _bar(early, 1, 2, 0.5, 1.5),
    ]
    first = first_ny_4h_bar(bars, day)
    assert first is not None
    assert first.ts == early


def test_4hrr_short_setup_sequence() -> None:
    """Close بالای RH → Close داخل → Short با استاپ High بریک‌اوت."""
    day_local = datetime(2026, 3, 20, 0, 0, tzinfo=NY)
    open_4h = day_local.astimezone(timezone.utc)
    close_4h = open_4h + timedelta(hours=4)
    bar_4h = _bar(open_4h, 100, 110, 100, 105)
    bars_4h = [bar_4h]

    bars_5m: list[OhlcBar] = []
    t = close_4h
    # breakout close above 110
    bars_5m.append(_bar(t, 109, 113, 108, 111.5))
    t += timedelta(minutes=5)
    # re-entry close inside
    bars_5m.append(_bar(t, 111, 111, 107, 108))

    scenario = {"scenario_id": "4hrr", "title_fa": "4HRR"}
    hits = scan_ny_day_4hrr(
        bars_5m,
        bars_4h,
        ny_calendar_date(open_4h),
        scenario=scenario,
        params={"tp_rr": 2.0},
    )
    assert len(hits) == 1
    _, hit = hits[0]
    assert hit.meta["direction"] == "down"
    assert hit.meta["entry_px"] == 108
    assert hit.meta["stop_px"] == 113
    assert hit.meta["tp_px"] == 98  # 2R: risk 5


def test_4hrr_one_trade_blocks_second_same_day() -> None:
    day_local = datetime(2026, 3, 21, 0, 0, tzinfo=NY)
    open_4h = day_local.astimezone(timezone.utc)
    close_4h = open_4h + timedelta(hours=4)
    bar_4h = _bar(open_4h, 100, 110, 100, 105)
    bars_4h = [bar_4h]
    scenario = {"scenario_id": "4hrr", "title_fa": "4HRR"}

    bars_5m: list[OhlcBar] = []
    t = close_4h

    def short_setup() -> None:
        nonlocal t
        bars_5m.append(_bar(t, 109, 113, 108, 111.5))
        t += timedelta(minutes=5)
        bars_5m.append(_bar(t, 111, 111, 107, 108))
        t += timedelta(minutes=5)

    short_setup()
    # during open trade: no new close-based setups (inside holds, no new breakout close)
    for _ in range(4):
        bars_5m.append(_bar(t, 107, 109, 106, 107))
        t += timedelta(minutes=5)
    # TP for first short (tp=98)
    bars_5m.append(_bar(t, 107, 108, 96, 96.5))
    t += timedelta(minutes=5)
    bars_5m.append(_bar(t, 109, 115, 108, 112))
    t += timedelta(minutes=5)
    bars_5m.append(_bar(t, 112, 112, 107, 109))

    hits = scan_ny_day_4hrr(
        bars_5m,
        bars_4h,
        ny_calendar_date(open_4h),
        scenario=scenario,
        params={"tp_rr": 2.0},
    )
    assert len(hits) == 2
