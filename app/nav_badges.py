from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.auth_middleware import current_user
from app.pattern_store import list_all_pattern_events
from app.position_store import list_positions
from app.storage import list_reports

NAV_SEEN_PATTERNS = "nav_seen_patterns"
NAV_SEEN_REPORTS = "nav_seen_reports"
NAV_SEEN_POSITION = "nav_seen_position"

_BADGE_CAP = 99


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def init_nav_seen_session(request: Request) -> None:
    now = _utc_now_iso()
    request.session[NAV_SEEN_PATTERNS] = now
    request.session[NAV_SEEN_REPORTS] = now
    request.session[NAV_SEEN_POSITION] = now


def mark_nav_seen(request: Request, section: str) -> None:
    now = _utc_now_iso()
    if section == "patterns":
        request.session[NAV_SEEN_PATTERNS] = now
    elif section == "reports":
        request.session[NAV_SEEN_REPORTS] = now
    elif section == "position":
        request.session[NAV_SEEN_POSITION] = now


def _since(session: dict[str, Any], key: str) -> str:
    val = session.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return "1970-01-01T00:00:00Z"


def _cap(n: int) -> int:
    return min(max(0, n), _BADGE_CAP)


def compute_nav_badges(
    request: Request,
    *,
    active: str | None = None,
    scheduled_reports_only: bool = False,
) -> dict[str, int]:
    """تعداد رویدادهای جدید از آخرین بازدید هر بخش."""
    user = current_user(request)
    if not user:
        return {"patterns": 0, "reports": 0, "position": 0}

    sess = request.session
    if NAV_SEEN_PATTERNS not in sess:
        init_nav_seen_session(request)
    uid = int(user["id"])

    patterns_n = 0
    if active != "patterns":
        since = _since(sess, NAV_SEEN_PATTERNS)
        patterns_n = len(list_all_pattern_events(start_iso=since, limit=500))

    reports_n = 0
    if active != "reports":
        since = _since(sess, NAV_SEEN_REPORTS)
        reports_n = len(
            list_reports(
                start_iso=since,
                limit=200,
                scheduled_only=scheduled_reports_only,
            )
        )

    position_n = 0
    if active != "position":
        since = _since(sess, NAV_SEEN_POSITION)
        position_n = len(
            list_positions(uid, opened_from=since, limit=200)
        )

    return {
        "patterns": _cap(patterns_n),
        "reports": _cap(reports_n),
        "position": _cap(position_n),
    }
