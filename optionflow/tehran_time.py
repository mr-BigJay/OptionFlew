from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

REPORT_MINUTE = 31
CANDLE_CLOSE_MINUTE = 30
# 4h candle closes at :30 on these hours (Tehran); report at :31
CRON_4H_HOURS = "3,7,11,15,19,23"
CRON_DAILY_HOUR = "0"
# Legacy alias
CRON_ODD_HOURS = CRON_4H_HOURS

FOUR_H_CLOSE_HOURS = (3, 7, 11, 15, 19, 23)


def now_tehran() -> datetime:
    return datetime.now(TEHRAN)


def parse_utc_iso(iso: str) -> datetime:
    if iso.endswith("Z"):
        iso = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


def format_dt_tehran(iso: str) -> str:
    try:
        dt = parse_utc_iso(iso).astimezone(TEHRAN)
        return dt.strftime("%Y/%m/%d — %H:%M")
    except ValueError:
        return iso


def format_time_tehran(iso: str) -> str:
    try:
        return parse_utc_iso(iso).astimezone(TEHRAN).strftime("%H:%M")
    except ValueError:
        return ""


def format_date_tehran(iso: str) -> str:
    try:
        return parse_utc_iso(iso).astimezone(TEHRAN).strftime("%Y/%m/%d")
    except ValueError:
        return iso


def tehran_date_key(iso: str) -> str:
    return parse_utc_iso(iso).astimezone(TEHRAN).strftime("%Y-%m-%d")


def last_closed_4h_candle_end(at: datetime | None = None) -> datetime:
    t = (at or now_tehran()).astimezone(TEHRAN)
    ready = t - timedelta(minutes=1)
    for day_offset in (0, 1):
        base = t if day_offset == 0 else t - timedelta(days=1)
        for h in reversed(FOUR_H_CLOSE_HOURS):
            close = base.replace(
                hour=h, minute=CANDLE_CLOSE_MINUTE, second=0, microsecond=0
            )
            if ready >= close:
                return close
    return (t - timedelta(days=1)).replace(
        hour=23, minute=CANDLE_CLOSE_MINUTE, second=0, microsecond=0
    )


def last_closed_daily_end(at: datetime | None = None) -> datetime:
    """Midnight Tehran at start of the calendar day that just finished."""
    t = (at or now_tehran()).astimezone(TEHRAN)
    end = t.replace(hour=0, minute=0, second=0, microsecond=0)
    if t < end + timedelta(minutes=1):
        end -= timedelta(days=1)
    return end


def candle_window_4h(at: datetime | None = None) -> tuple[datetime, datetime, str]:
    end = last_closed_4h_candle_end(at)
    start = end - timedelta(hours=4)
    label = (
        f"کندل ۴ ساعته {start.strftime('%H:%M')}–{end.strftime('%H:%M')} (وقت تهران)"
    )
    return start, end, label


def candle_window_daily(at: datetime | None = None) -> tuple[datetime, datetime, str]:
    end = last_closed_daily_end(at)
    start = end - timedelta(days=1)
    label = f"روز معاملاتی {start.strftime('%Y/%m/%d')} (وقت تهران)"
    return start, end, label


def candle_window(at: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Backward-compatible alias for 4h window."""
    return candle_window_4h(at)


def to_utc_ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def tehran_day_bounds_utc(anchor_date: str | None = None) -> tuple[str, str]:
    if anchor_date:
        base = datetime.fromisoformat(anchor_date + "T00:00:00").replace(tzinfo=TEHRAN)
    else:
        base = now_tehran().replace(hour=0, minute=0, second=0, microsecond=0)
    end = base + timedelta(days=1)

    def iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    return iso(base), iso(end)


def tehran_week_bounds_utc(anchor_date: str | None = None) -> tuple[str, str]:
    if anchor_date:
        base = datetime.fromisoformat(anchor_date + "T00:00:00").replace(tzinfo=TEHRAN)
    else:
        base = now_tehran()
    start = base - timedelta(days=base.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    def iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    return iso(start), iso(end)


def tehran_month_bounds_utc(anchor_date: str | None = None) -> tuple[str, str]:
    if anchor_date:
        base = datetime.fromisoformat(anchor_date + "T00:00:00").replace(tzinfo=TEHRAN)
    else:
        base = now_tehran()
    start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    def iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    return iso(start), iso(end)


def next_report_times_tehran(count: int = 4) -> list[str]:
    """Human-readable next 4h + daily report times in Tehran."""
    t = now_tehran()
    times: list[tuple[datetime, str]] = []
    probe = t.replace(second=0, microsecond=0)
    for _ in range(72 * 60):
        h, m = probe.hour, probe.minute
        if m == REPORT_MINUTE and probe > t:
            if h in FOUR_H_CLOSE_HOURS:
                times.append((probe, f"۴h {probe.strftime('%H:%M')}"))
            if h == 0:
                times.append((probe, f"روزانه {probe.strftime('%H:%M')}"))
        if len(times) >= count:
            break
        probe += timedelta(minutes=1)
    times.sort(key=lambda x: x[0])
    return [label for _, label in times[:count]]
