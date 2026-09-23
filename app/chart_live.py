from __future__ import annotations

from typing import Any

from app.pattern_store import get_pattern_event_by_key
from app.paper_chart import _load_pattern_bars, _pick_interval
from optionflow.patterns.chart_overlays import build_live_chart_payload, overlays_json
from optionflow.patterns.types import PatternHit


def payload_from_pattern_event(event: dict[str, Any]) -> dict[str, Any] | None:
    tf = str(event.get("timeframe") or "15m")
    try:
        bars = _load_pattern_bars(tf)
    except Exception:
        return None
    if len(bars) < 10:
        return None
    return build_live_chart_payload(
        timeframe=tf,
        bars=bars,
        category=str(event.get("category") or ""),
        meta=event.get("meta") if isinstance(event.get("meta"), dict) else {},
        created_at=str(event.get("created_at") or ""),
        title=str(event.get("title_fa") or ""),
    )


def payload_from_pattern_hit(hit: PatternHit) -> dict[str, Any] | None:
    tf = str(hit.timeframe or "15m")
    try:
        bars = _load_pattern_bars(tf)
    except Exception:
        return None
    if len(bars) < 10:
        return None
    return build_live_chart_payload(
        timeframe=tf,
        bars=bars,
        category=str(hit.category or ""),
        meta=hit.meta or {},
        title=str(hit.title_fa or ""),
    )


def _pattern_event_for_position(pos: dict[str, Any]) -> dict[str, Any] | None:
    if str(pos.get("source_type") or "") != "pattern":
        return None
    sk = str(pos.get("source_key") or "").strip()
    if not sk:
        return None
    return get_pattern_event_by_key(sk)


def payload_from_position(pos: dict[str, Any], *, mark: float | None = None) -> dict[str, Any] | None:
    ev = _pattern_event_for_position(pos)
    tf = _pick_interval(str((ev or {}).get("timeframe") or pos.get("timeframe") or "15m"))
    try:
        bars = _load_pattern_bars(tf)
    except Exception:
        return None
    if len(bars) < 10:
        return None
    category = str((ev or {}).get("category") or "")
    meta = (ev or {}).get("meta") if ev and isinstance(ev.get("meta"), dict) else {}
    created = str((ev or {}).get("created_at") or "") if ev else None
    title = str(pos.get("signal_title") or (ev or {}).get("title_fa") or "پوزیشن")
    return build_live_chart_payload(
        timeframe=tf,
        bars=bars,
        category=category,
        meta=meta,
        created_at=created,
        title=title,
        position=pos,
        mark=mark,
    )


def json_for_template(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "{}"
    return overlays_json(payload)
