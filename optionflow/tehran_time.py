from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

REPORT_MINUTE = 31
CANDLE_CLOSE_MINUTE = 30
CRON_ODD_HOURS = "1,3,5,7,9,11,13,15,17,19,21,23"


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


def last_closed_candle_end(at: datetime | None = None) -> datetime:
    t = (at or now_tehran()).astimezone(TEHRAN)
    odd = t.hour if t.hour % 2 == 1 else t.hour - 1
    if odd < 0:
        close = (t - timedelta(days=1)).replace(
            hour=23, minute=CANDLE_CLOSE_MINUTE, second=0, microsecond=0
        )
    else:
        close = t.replace(hour=odd, minute=CANDLE_CLOSE_MINUTE, second=0, microsecond=0)
    if t < close + timedelta(minutes=1):
        close -= timedelta(hours=2)
    return close


def candle_window(at: datetime | None = None) -> tuple[datetime, datetime, str]:
    end = last_closed_candle_end(at)
    start = end - timedelta(hours=2)
    label = (
        f"کندل ۲ ساعته {start.strftime('%H:%M')}–{end.strftime('%H:%M')} (وقت تهران)"
    )
    return start, end, label


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


def next_report_times_tehran(count: int = 3) -> list[str]:
    """Human-readable next run times in Tehran."""
    t = now_tehran()
    times: list[str] = []
    probe = t.replace(second=0, microsecond=0)
    for _ in range(48):
        h = probe.hour
        if h % 2 == 1 and probe.minute == REPORT_MINUTE and probe > t:
            times.append(probe.strftime("%H:%M"))
            if len(times) >= count:
                break
        probe += timedelta(minutes=1)
    return times
