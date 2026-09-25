from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.indicator_pine_inputs import parse_pine_inputs, pine_overlay_on_chart
from app.paper_chart import _load_pattern_bars
from optionflow.patterns.chart_overlays import candles_payload
from optionflow.patterns.indicators import ema, rsi
from optionflow.patterns.ohlc import OhlcBar

logger = logging.getLogger("optionflow.indicator_runtime")


def _bar_times(bars: list[OhlcBar]) -> list[int]:
    from optionflow.patterns.chart_overlays import bar_unix

    return [bar_unix(b) for b in bars]


def _series_from_values(bars: list[OhlcBar], values: list[float | None]) -> list[dict[str, float | int]]:
    times = _bar_times(bars)
    pts: list[dict[str, float | int]] = []
    for i, v in enumerate(values):
        if v is None or i >= len(times):
            continue
        pts.append({"time": times[i], "value": float(v)})
    return pts


def _coerce_settings(raw: dict[str, Any] | None, fields: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_id = {f["id"]: f for f in fields}
    src = raw or {}
    for fid, spec in by_id.items():
        val = src.get(fid, spec.get("default"))
        kind = spec.get("type")
        try:
            if kind == "int":
                out[fid] = int(val)
            elif kind == "float":
                out[fid] = float(val)
            elif kind == "bool":
                out[fid] = bool(val) if not isinstance(val, str) else val.lower() == "true"
            else:
                out[fid] = val
        except (TypeError, ValueError):
            out[fid] = spec.get("default")
    return out


def _find_rsi_period(source: str, settings: dict[str, Any], fields: list[dict[str, Any]]) -> int:
    m = re.search(r"ta\.rsi\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)", source)
    if m:
        var = m.group(1)
        if var.isdigit():
            return max(1, int(var))
        if var in settings:
            try:
                return max(1, int(settings[var]))
            except (TypeError, ValueError):
                pass
    for f in fields:
        t = str(f.get("title") or "").lower()
        if "rsi" in t and f.get("type") == "int":
            try:
                return max(1, int(settings.get(f["id"], f.get("default", 14))))
            except (TypeError, ValueError):
                pass
    return max(1, int(settings.get("length", settings.get("rsiLength", 14)) or 14))


def _find_ob_os(source: str, settings: dict[str, Any], fields: list[dict[str, Any]]) -> tuple[float, float]:
    ob, os_ = 70.0, 30.0
    for f in fields:
        t = str(f.get("title") or "").lower()
        fid = f["id"]
        val = settings.get(fid, f.get("default"))
        if not isinstance(val, (int, float)):
            continue
        if "over" in t or "ob" in t:
            ob = float(val)
        if "under" in t or "oversold" in t or ("os" in t and "close" not in t):
            os_ = float(val)
    return ob, os_


def _compute_pine(
    source: str,
    bars: list[OhlcBar],
    settings: dict[str, Any],
) -> dict[str, Any]:
    fields = parse_pine_inputs(source)
    settings = _coerce_settings(settings, fields)
    closes = [float(b.close) for b in bars]
    panes: list[dict[str, Any]] = []
    overlays: dict[str, Any] = {"hlines": [], "segments": [], "lines": [], "markers": []}

    code = source or ""
    overlay_main = pine_overlay_on_chart(code)

    if "ta.rsi" in code or re.search(r"\brsi\s*\(", code, re.I):
        period = _find_rsi_period(code, settings, fields)
        rs = rsi(closes, period)
        ob, os_ = _find_ob_os(code, settings, fields)
        color = "#7E57C2"
        for f in fields:
            if f.get("type") == "color":
                color = str(settings.get(f["id"], f.get("default", color)))
                break
        rsi_pts = _series_from_values(bars, rs)
        pane = {
            "label": "RSI",
            "min": 0,
            "max": 100,
            "levels": [os_, ob],
            "series": [{"name": "RSI", "color": color, "points": rsi_pts}],
        }
        if overlay_main:
            overlays["lines"].append(
                {"color": color, "label": "RSI", "width": 2, "points": rsi_pts}
            )
        else:
            panes.append(pane)

    # فقط EMAهایی که خود اسکریپت plot کرده؛ فراخوانی داخلی ta.ema خط اضافه روی قیمت نمی‌سازد.
    ema_m = re.findall(
        r"plot\s*\(\s*ta\.ema\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*|\d+)", code
    )
    for ref in ema_m[:3]:
        length = 21
        if ref.isdigit():
            length = int(ref)
        elif ref in settings:
            try:
                length = max(1, int(settings[ref]))
            except (TypeError, ValueError):
                pass
        line = ema(closes, length)
        overlays["lines"].append(
            {
                "color": "#42a5f5",
                "label": f"EMA {length}",
                "width": 1,
                "points": _series_from_values(bars, line),
            }
        )

    return {"panes": panes, "overlays": overlays, "settings": settings, "fields": fields}


def _safe_python_compute(
    source: str,
    bars: list[OhlcBar],
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    candles = [
        {
            "time": t,
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
        }
        for t, b in zip(_bar_times(bars), bars)
    ]
    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "len": len,
        "range": range,
        "float": float,
        "int": int,
        "bool": bool,
        "str": str,
        "list": list,
        "dict": dict,
        "sum": sum,
        "round": round,
    }
    ns: dict[str, Any] = {"__builtins__": safe_builtins}
    try:
        exec(compile(source, "<indicator>", "exec"), ns, ns)
    except Exception:
        logger.exception("python indicator exec failed")
        return None
    fn = ns.get("indicator_series") or ns.get("compute")
    if not callable(fn):
        return None
    try:
        raw = fn(candles, dict(settings))
    except Exception:
        logger.exception("python indicator compute failed")
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def build_indicator_live_payload(
    *,
    language: str,
    source_code: str,
    settings: dict[str, Any] | None = None,
    timeframe: str = "15m",
) -> dict[str, Any] | None:
    try:
        bars = _load_pattern_bars(timeframe)
    except Exception:
        return None
    if len(bars) < 20:
        return None

    lang = (language or "pine").strip().lower()
    panes: list[dict[str, Any]] = []
    overlays: dict[str, Any] = {"hlines": [], "segments": [], "lines": [], "markers": []}
    fields: list[dict[str, Any]] = []
    eff_settings: dict[str, Any] = {}

    if lang == "python":
        raw = _safe_python_compute(source_code, bars, settings or {})
        if raw:
            panes = list(raw.get("panes") or [])
            ov = raw.get("overlays")
            if isinstance(ov, dict):
                overlays = ov
    elif lang == "pine":
        out = _compute_pine(source_code, bars, settings or {})
        panes = out.get("panes") or []
        overlays = out.get("overlays") or overlays
        fields = out.get("fields") or []
        eff_settings = out.get("settings") or {}
    else:
        fields = []
        eff_settings = settings or {}

    return {
        "timeframe": timeframe,
        "candles": candles_payload(bars),
        "panes": panes,
        "overlays": overlays,
        "tv_fields": fields,
        "tv_settings": eff_settings,
    }


def tv_fields_json(indicator: dict[str, Any]) -> str:
    lang = str(indicator.get("language") or "pine")
    if lang != "pine":
        return "[]"
    return json.dumps(parse_pine_inputs(str(indicator.get("source_code") or "")), ensure_ascii=False)
