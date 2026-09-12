from __future__ import annotations

from datetime import datetime

from optionflow.report_service import ReportKind
from optionflow.tehran_time import (
    FOUR_H_CLOSE_HOURS,
    last_closed_4h_candle_end,
    last_closed_daily_end,
    now_tehran,
    TEHRAN,
)

_SLOT_BY_HOUR = {h: i + 1 for i, h in enumerate(FOUR_H_CLOSE_HOURS)}


def tehran_date_key_compact(at: datetime | None = None) -> str:
    t = (at or now_tehran()).astimezone(TEHRAN)
    return t.strftime("%Y%m%d")


def four_h_slot_index(close_end_tehran: datetime) -> int:
    h = close_end_tehran.astimezone(TEHRAN).hour
    return _SLOT_BY_HOUR.get(h, 1)


def scheduled_report_code(kind: ReportKind, at: datetime | None = None) -> str:
    """YYYYMMDD-4h1..4h6 or YYYYMMDD-d (Tehran, aligned to closed candle)."""
    if kind == "daily":
        end = last_closed_daily_end(at)
        return f"{end.astimezone(TEHRAN).strftime('%Y%m%d')}-d"
    end = last_closed_4h_candle_end(at)
    slot = four_h_slot_index(end)
    return f"{end.astimezone(TEHRAN).strftime('%Y%m%d')}-4h{slot}"


def manual_report_code(date_key: str, index: int) -> str:
    """Manual snapshot code: YYYYMMDD-j1 .. jn (Tehran calendar day)."""
    return f"{date_key}-j{index}"
