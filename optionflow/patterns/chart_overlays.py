from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from optionflow.patterns.ohlc import OhlcBar


def bar_unix(b: OhlcBar) -> int:
    ts = b.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp())


def candles_payload(bars: list[OhlcBar]) -> list[dict[str, float | int]]:
    out: list[dict[str, float | int]] = []
    for b in bars:
        out.append(
            {
                "time": bar_unix(b),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
            }
        )
    return out


def parse_iso_ts(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def nearest_bar_index(bars: list[OhlcBar], ts: datetime) -> int:
    best_i = len(bars) - 1
    best_d = float("inf")
    for i, b in enumerate(bars):
        bt = b.ts
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        d = abs((bt - ts).total_seconds())
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def reanchor_meta(
    bars: list[OhlcBar],
    meta: dict[str, Any],
    *,
    created_at: str | None,
    category: str | None = None,
) -> dict[str, Any]:
    """هم‌تراز کردن متای الگو — start_i و touchها اندیس محلی پنجره‌اند."""
    ts = parse_iso_ts(created_at or "")
    if ts is None or not bars:
        return dict(meta)
    idx = nearest_bar_index(bars, ts)
    m = dict(meta)
    end_i = int(m.get("end_i") or len(bars) - 1)
    old_wo = int(m.get("window_offset") or 0)
    cat = (category or str(m.get("kind") or "")).lower()

    if cat in ("trendline", "channel"):
        touches = m.get("touch_lows") or m.get("touch_highs") or []
        if touches:
            last_ti = int(touches[-1])
            new_wo = max(0, idx - last_ti)
            shift = new_wo - old_wo
            m["window_offset"] = new_wo
            for key in (
                "confirm_index",
                "early_index",
                "entry_index",
                "final_index",
                "break_index",
                "pullback_index",
                "signal_index",
            ):
                v = m.get(key)
                if isinstance(v, int):
                    m[key] = v + shift
            return m

    ref = m.get("confirm_index")
    if not isinstance(ref, int):
        ref = m.get("early_index")
    if not isinstance(ref, int):
        ref = old_wo + end_i
    shift = idx - ref
    m["window_offset"] = max(0, old_wo + shift)
    for key in (
        "confirm_index",
        "early_index",
        "entry_index",
        "final_index",
        "break_index",
        "pullback_index",
        "signal_index",
    ):
        v = m.get(key)
        if isinstance(v, int):
            m[key] = v + shift
    if cat == "divergence" or m.get("pivot_a"):
        for key in ("pivot_a", "pivot_b", "pivot_mid"):
            t = m.get(key)
            if isinstance(t, (list, tuple)) and len(t) >= 2:
                try:
                    m[key] = (int(t[0]) + shift, t[1])
                except (TypeError, ValueError):
                    pass
    return m


def _clamp_i(bars: list[OhlcBar], i: int) -> int:
    return max(0, min(int(i), len(bars) - 1))


def _bar_step_seconds(bars: list[OhlcBar]) -> int:
    if len(bars) < 2:
        return 900
    step = bar_unix(bars[-1]) - bar_unix(bars[-2])
    return max(60, int(step))


def time_at_local_index(bars: list[OhlcBar], wo: int, li: float) -> int:
    """زمان کندل برای اندیس محلی؛ اگر apex بعد از آخرین کندل باشد، خارج از داده extrapolate می‌شود."""
    if not bars:
        return 0
    gi = wo + int(round(li))
    if gi < 0:
        gi = 0
    if gi < len(bars):
        return bar_unix(bars[gi])
    last = len(bars) - 1
    return int(bar_unix(bars[last]) + (gi - last) * _bar_step_seconds(bars))


def _segment_times(
    t0: int,
    p0: float,
    t1: int,
    p1: float,
    *,
    color: str,
    label: str = "",
    width: int = 1,
) -> dict[str, Any]:
    return {
        "t0": int(t0),
        "p0": float(p0),
        "t1": int(t1),
        "p1": float(p1),
        "color": color,
        "label": label,
        "width": width,
    }


def _hline(price: float, *, color: str, label: str, style: str = "dashed") -> dict[str, Any]:
    return {
        "price": float(price),
        "color": color,
        "label": label,
        "style": style,
    }


def _marker(bars: list[OhlcBar], i: int, *, text: str, color: str, position: str) -> dict[str, Any]:
    i = _clamp_i(bars, i)
    return {
        "time": bar_unix(bars[i]),
        "position": position,
        "color": color,
        "text": text,
    }


def _segment(
    bars: list[OhlcBar],
    i0: int,
    p0: float,
    i1: int,
    p1: float,
    *,
    color: str,
    label: str = "",
    width: int = 1,
) -> dict[str, Any]:
    i0, i1 = _clamp_i(bars, i0), _clamp_i(bars, i1)
    return {
        "t0": bar_unix(bars[i0]),
        "p0": float(p0),
        "t1": bar_unix(bars[i1]),
        "p1": float(p1),
        "color": color,
        "label": label,
        "width": width,
    }


def _apex_local_index(
    meta: dict[str, Any], su: float, iu: float, sl: float, il: float
) -> float | None:
    ap = meta.get("apex_index")
    if isinstance(ap, (int, float)):
        return float(ap)
    den = float(su) - float(sl)
    if abs(den) < 1e-12:
        return None
    return (float(il) - float(iu)) / den


def _triangle_range(
    meta: dict[str, Any], bars: list[OhlcBar]
) -> tuple[int, int, float | None] | None:
    wo = int(meta.get("window_offset") or 0)
    i0 = meta.get("start_i")
    i1 = meta.get("end_i")
    if not isinstance(i0, int) or not isinstance(i1, int):
        return None
    su, iu = meta.get("upper_slope"), meta.get("upper_intercept")
    sl, il = meta.get("lower_slope"), meta.get("lower_intercept")
    li_end = float(i1)
    ap: float | None = None
    if all(isinstance(x, (int, float)) for x in (su, iu, sl, il)):
        ap = _apex_local_index(meta, float(su), float(iu), float(sl), float(il))
        if ap is not None:
            li_end = max(li_end, ap + 2.0)
    pad_right = 6
    core_g0 = wo + int(i0)
    core_g1 = wo + int(li_end)
    core_len = max(1, core_g1 - core_g0 + 1)
    # ~۲۰٪ زوم کمتر: حدود ۱۰٪ حاشیه در هر طرف + سابقهٔ قبل از الگو
    zoom_out = max(6, int(core_len * 0.10))
    history = max(14, int((int(i1) - int(i0)) * 0.35))
    g0 = max(0, core_g0 - history - zoom_out)
    g1 = min(len(bars) - 1, core_g1 + pad_right + zoom_out)
    if g1 <= g0:
        return None
    return g0, g1, ap


def _meta_for_sliced_bars(meta: dict[str, Any], g0: int) -> dict[str, Any]:
    m = dict(meta)
    wo = int(m.get("window_offset") or 0)
    m["window_offset"] = wo - g0
    for key in (
        "confirm_index",
        "early_index",
        "entry_index",
        "final_index",
        "break_index",
        "pullback_index",
        "signal_index",
    ):
        v = m.get(key)
        if isinstance(v, int):
            m[key] = v - g0
    return m


def triangle_viewport(meta: dict[str, Any], bars: list[OhlcBar]) -> dict[str, float | int] | None:
    rng = _triangle_range(meta, bars)
    if rng is None:
        return None
    g0, g1, ap = rng
    wo = int(meta.get("window_offset") or 0)
    su, iu = meta.get("upper_slope"), meta.get("upper_intercept")
    sl, il = meta.get("lower_slope"), meta.get("lower_intercept")
    t_from = bar_unix(bars[0])
    t_to = bar_unix(bars[-1])
    if len(bars) > 1 and ap is not None:
        t_to = max(t_to, time_at_local_index(bars, wo, ap + 1.0))
    prices: list[float] = []
    for gi in range(0, len(bars)):
        prices.append(float(bars[gi].high))
        prices.append(float(bars[gi].low))
    if ap is not None and all(isinstance(x, (int, float)) for x in (su, iu, sl, il)):
        prices.append(float(su) * ap + float(iu))
    if not prices:
        return {"from": t_from, "to": t_to, "fitTime": 1}
    lo_p, hi_p = min(prices), max(prices)
    pad = max(30.0, (hi_p - lo_p) * 0.12)
    return {
        "from": t_from,
        "to": t_to,
        "priceMin": lo_p - pad,
        "priceMax": hi_p + pad,
        "fitTime": 1,
    }


def _trendline_line_points(
    meta: dict[str, Any], bars: list[OhlcBar], *, upper: bool
) -> list[dict[str, float | int]]:
    sk = "upper_slope" if upper else "lower_slope"
    ik = "upper_intercept" if upper else "lower_intercept"
    slope, intercept = meta.get(sk), meta.get(ik)
    if not isinstance(slope, (int, float)) or not isinstance(intercept, (int, float)):
        return []
    side = meta.get("side")
    if meta.get("kind") == "trendline":
        if side == "low" and upper:
            return []
        if side == "high" and not upper:
            return []
    wo = int(meta.get("window_offset") or 0)
    i0 = meta.get("start_i")
    i1 = meta.get("end_i")
    if isinstance(i0, int) and isinstance(i1, int):
        li0, li1 = int(i0), int(i1)
    else:
        li0, li1 = 0, max(0, len(bars) - 1 - wo)
    li_end = max(li1, len(bars) - 1 - wo)
    g0 = max(0, wo + li0)
    g1 = min(len(bars) - 1, wo + li_end)
    if g1 <= g0:
        return []
    pts: list[dict[str, float | int]] = []
    for gi in range(g0, g1 + 1):
        li = gi - wo
        y = float(slope) * li + float(intercept)
        pts.append({"time": bar_unix(bars[gi]), "value": y})
    return pts


def _y_line(meta: dict[str, Any], bars: list[OhlcBar], *, upper: bool) -> list[dict[str, float | int]]:
    return _trendline_line_points(meta, bars, upper=upper)


def position_overlays(pos: dict[str, Any], *, mark: float | None = None) -> dict[str, Any]:
    hlines = [
        _hline(float(pos["entry_price"]), color="#fbbf24", label="Entry", style="solid"),
        _hline(float(pos["sl_price"]), color="#f87171", label="SL"),
        _hline(float(pos["tp_price"]), color="#34d399", label="TP"),
    ]
    if mark is not None and mark > 0:
        hlines.append(_hline(float(mark), color="#60a5fa", label="Mark", style="dotted"))
    return {"hlines": hlines, "segments": [], "lines": [], "markers": []}


def _triangle_lines(
    meta: dict[str, Any], bars: list[OhlcBar]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    segments: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    su, iu = meta.get("upper_slope"), meta.get("upper_intercept")
    sl, il = meta.get("lower_slope"), meta.get("lower_intercept")
    i0, i1 = meta.get("start_i"), meta.get("end_i")
    if not all(isinstance(x, (int, float)) for x in (su, iu, sl, il, i0, i1)):
        u, lo = meta.get("upper_now"), meta.get("lower_now")
        if isinstance(u, (int, float)):
            segments.append(
                _segment(
                    bars,
                    len(bars) - 40,
                    float(u),
                    len(bars) - 1,
                    float(u),
                    color="#ffb74d",
                    label="سقف",
                )
            )
        if isinstance(lo, (int, float)):
            segments.append(
                _segment(
                    bars,
                    len(bars) - 40,
                    float(lo),
                    len(bars) - 1,
                    float(lo),
                    color="#81c784",
                    label="کف",
                )
            )
        return segments, markers
    wo = int(meta.get("window_offset") or 0)
    li0, li1 = int(i0), int(i1)
    y_u0 = float(su) * li0 + float(iu)
    y_l0 = float(sl) * li0 + float(il)
    t0 = time_at_local_index(bars, wo, li0)
    ap = _apex_local_index(meta, float(su), float(iu), float(sl), float(il))
    if ap is not None and ap > li0:
        li_apex = float(ap)
        y_apex = float(su) * li_apex + float(iu)
        t1 = time_at_local_index(bars, wo, li_apex)
        segments.append(
            _segment_times(
                t0, y_u0, t1, y_apex, color="#ffb74d", label="مقاومت", width=1
            )
        )
        segments.append(
            _segment_times(
                t0, y_l0, t1, y_apex, color="#81c784", label="حمایت", width=1
            )
        )
    else:
        y_u1 = float(su) * li1 + float(iu)
        y_l1 = float(sl) * li1 + float(il)
        t1 = time_at_local_index(bars, wo, li1)
        segments.append(
            _segment_times(t0, y_u0, t1, y_u1, color="#ffb74d", label="مقاومت", width=1)
        )
        segments.append(
            _segment_times(t0, y_l0, t1, y_l1, color="#81c784", label="حمایت", width=1)
        )
    return segments, markers


def pattern_overlays(
    category: str,
    meta: dict[str, Any],
    bars: list[OhlcBar],
) -> dict[str, Any]:
    hlines: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    cat = (category or "").strip().lower()

    if cat == "divergence":
        pa, pb = meta.get("pivot_a"), meta.get("pivot_b")
        if isinstance(pa, (list, tuple)) and isinstance(pb, (list, tuple)) and len(pa) >= 2 and len(pb) >= 2:
            ia, ib = int(pa[0]), int(pb[0])
            segments.append(
                _segment(
                    bars,
                    ia,
                    float(pa[1]),
                    ib,
                    float(pb[1]),
                    color="#ef5350" if meta.get("direction") == "down" else "#66bb6a",
                    label="واگرایی",
                )
            )
            markers.append(_marker(bars, ib, text="B", color="#ef5350", position="aboveBar"))
            markers.append(_marker(bars, ia, text="A", color="#90caf9", position="belowBar"))
        cf = meta.get("confirm_index")
        if isinstance(cf, int):
            markers.append(_marker(bars, cf, text="تأیید", color="#78909c", position="aboveBar"))
        ei = meta.get("entry_index")
        if isinstance(ei, int):
            markers.append(_marker(bars, ei, text="ورود", color="#fbbf24", position="belowBar"))

    elif cat in ("trendline", "channel"):
        up_pts = _trendline_line_points(meta, bars, upper=True)
        lo_pts = _trendline_line_points(meta, bars, upper=False)
        if up_pts:
            lines.append({"color": "#ffb74d", "label": "مقاومت", "points": up_pts, "width": 1})
        if lo_pts:
            lines.append({"color": "#81c784", "label": "حمایت", "points": lo_pts, "width": 1})

    elif cat == "ema50":
        ep, sl = meta.get("entry_px"), meta.get("sl_px")
        if isinstance(ep, (int, float)):
            hlines.append(_hline(float(ep), color="#fbbf24", label="ورود", style="solid"))
        if isinstance(sl, (int, float)):
            hlines.append(_hline(float(sl), color="#f87171", label="SL"))
        tp = meta.get("tp_px") or meta.get("ema_now")
        if isinstance(tp, (int, float)):
            hlines.append(_hline(float(tp), color="#42a5f5", label="EMA50"))
        pb = meta.get("pullback_index")
        if isinstance(pb, int):
            markers.append(_marker(bars, pb, text="PB", color="#90caf9", position="belowBar"))

    elif cat == "three_rp":
        ep = meta.get("entry_px")
        if isinstance(ep, (int, float)):
            hlines.append(_hline(float(ep), color="#fbbf24", label="ورود", style="solid"))
        ei = meta.get("entry_index")
        if isinstance(ei, int):
            markers.append(_marker(bars, ei, text="ورود", color="#fbbf24", position="belowBar"))

    elif cat in ("triangle", "flag"):
        if cat == "triangle":
            tri_seg, tri_mk = _triangle_lines(meta, bars)
            segments.extend(tri_seg)
            markers.extend(tri_mk)
        else:
            fh, fl = meta.get("flag_high"), meta.get("flag_low")
            if isinstance(fh, (int, float)):
                hlines.append(_hline(float(fh), color="#ffb74d", label="سقف پرچم"))
            if isinstance(fl, (int, float)):
                hlines.append(_hline(float(fl), color="#81c784", label="کف پرچم"))
            ps = meta.get("pole_start")
            if isinstance(ps, int):
                markers.append(_marker(bars, ps, text="pole", color="#90caf9", position="belowBar"))

    elif cat == "meaningful_behavior":
        strike = meta.get("strike") or meta.get("tp_px")
        spot = meta.get("spot_at_signal")
        if isinstance(strike, (int, float)):
            hlines.append(_hline(float(strike), color="#a78bfa", label="Strike"))
        if isinstance(spot, (int, float)):
            hlines.append(_hline(float(spot), color="#60a5fa", label="Spot"))

    else:
        ep = meta.get("entry_px")
        if isinstance(ep, (int, float)):
            hlines.append(_hline(float(ep), color="#fbbf24", label="ورود"))

    return {
        "hlines": hlines,
        "segments": segments,
        "lines": lines,
        "markers": markers,
    }


def merge_overlay_specs(*specs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "hlines": [],
        "segments": [],
        "lines": [],
        "markers": [],
    }
    for s in specs:
        if not s:
            continue
        for k in out:
            out[k].extend(s.get(k) or [])
    return out


def build_live_chart_payload(
    *,
    timeframe: str,
    bars: list[OhlcBar],
    category: str,
    meta: dict[str, Any] | None,
    created_at: str | None = None,
    title: str = "",
    position: dict[str, Any] | None = None,
    mark: float | None = None,
) -> dict[str, Any]:
    m = dict(meta or {})
    if created_at:
        m = reanchor_meta(bars, m, created_at=created_at, category=category)
    cat = (category or "").strip().lower()
    chart_bars = bars
    m_chart = m
    if cat == "triangle" and m:
        rng = _triangle_range(m, bars)
        if rng:
            g0, g1, _ap = rng
            chart_bars = bars[g0 : g1 + 1]
            m_chart = _meta_for_sliced_bars(m, g0)
    specs: list[dict[str, Any]] = []
    if category and m_chart:
        specs.append(pattern_overlays(category, m_chart, chart_bars))
    if position:
        specs.append(position_overlays(position, mark=mark))
    overlays = merge_overlay_specs(*specs)
    payload: dict[str, Any] = {
        "timeframe": timeframe,
        "title": title,
        "candles": candles_payload(chart_bars),
        "overlays": overlays,
    }
    if cat == "triangle" and m_chart:
        vp = triangle_viewport(m_chart, chart_bars)
        if vp:
            payload["viewport"] = vp
    return payload


def overlays_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
