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
        # end_i کندل تشخیص است، نه آخرین برخورد. سیگنال اولیه چند کندل بعد از
        # برخورد ثبت می‌شود؛ اگر خط را به زمان ثبت بچسبانیم از کف‌ها جدا می‌شود.
        end_local = int(m.get("end_i") or 0)
        ref = old_wo + end_local
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


def _time_at_extended_index(bars: list[OhlcBar], wo: int, li: int) -> int:
    """زمان اندیس محلی، حتی اگر خط از اولین یا آخرین کندل بیرون بزند."""
    if not bars:
        return 0
    step = _bar_step_seconds(bars)
    gi = wo + int(li)
    if gi < 0:
        return bar_unix(bars[0]) + gi * step
    if gi >= len(bars):
        return bar_unix(bars[-1]) + (gi - (len(bars) - 1)) * step
    return bar_unix(bars[gi])


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
    history = max(48, int((int(i1) - int(i0)) * 0.65))
    zoom_out = max(6, int(core_len * 0.08))
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


def _viewport_price_bounds(
    bars: list[OhlcBar],
    meta: dict[str, Any],
    g0: int,
    g1: int,
    category: str,
) -> tuple[float, float]:
    g0 = max(0, min(g0, len(bars) - 1))
    g1 = max(g0, min(g1, len(bars) - 1))
    window = bars[g0 : g1 + 1]
    lo = min(b.low for b in window)
    hi = max(b.high for b in window)
    cat = (category or "").strip().lower()
    if cat in ("triangle", "trendline", "channel"):
        wo = int(meta.get("window_offset") or 0)
        i0 = int(meta.get("start_i", 0))
        i1 = int(meta.get("end_i", i0))
        li0 = max(i0, g0 - wo)
        li1 = min(i1, g1 - wo)
        if li1 >= li0:
            for sl, ic in (
                (meta.get("upper_slope"), meta.get("upper_intercept")),
                (meta.get("lower_slope"), meta.get("lower_intercept")),
            ):
                if sl is None or ic is None:
                    continue
                y0 = float(sl) * li0 + float(ic)
                y1 = float(sl) * li1 + float(ic)
                lo = min(lo, y0, y1)
                hi = max(hi, y0, y1)
        for ti in (meta.get("touch_highs") or []) + (meta.get("touch_lows") or []):
            gi = wo + int(ti)
            if g0 <= gi <= g1:
                lo = min(lo, bars[gi].low)
                hi = max(hi, bars[gi].high)
    for key in ("tp_px", "entry_px", "entry_blended_px", "sl_px"):
        v = meta.get(key)
        if isinstance(v, (int, float)):
            px = float(v)
            lo = min(lo, px)
            hi = max(hi, px)
    span = hi - lo
    pad = span * 0.10 if span > 0 else max(abs(hi) * 0.002, 1.0)
    return lo - pad, hi + pad


def triangle_viewport(meta: dict[str, Any], bars: list[OhlcBar]) -> dict[str, float | int] | None:
    rng = _triangle_range(meta, bars)
    if rng is None:
        return None
    g0, g1, _ap = rng
    t_from = bar_unix(bars[g0])
    t_to = bar_unix(bars[g1])
    p_lo, p_hi = _viewport_price_bounds(bars, meta, g0, g1, "triangle")
    # Viewport = initial pan/zoom only; apex line extends in overlays, not empty future time.
    return {
        "from": t_from,
        "to": t_to,
        "priceMin": p_lo,
        "priceMax": p_hi,
    }


def _trendline_focus_viewport(meta: dict[str, Any], bars: list[OhlcBar]) -> dict[str, float | int] | None:
    """زوم اولیه روی بدنهٔ خط؛ کندل‌های قبل از g0 در سری می‌مانند تا اسکرول چپ کار کند."""
    if not bars:
        return None
    wo, i0, i1 = trendline_local_indices(meta, len(bars))
    li_end = max(i0, i1)
    pad_left = 16
    pad_right = 14
    g0 = max(0, wo + int(i0) - pad_left)
    g1 = min(len(bars) - 1, wo + li_end + pad_right)
    if g1 <= g0:
        return None
    return {
        "from": bar_unix(bars[g0]),
        "to": bar_unix(bars[g1]),
    }


def signal_bar_index(
    meta: dict[str, Any],
    bars: list[OhlcBar],
    *,
    created_at: str | None = None,
) -> int | None:
    if not bars:
        return None
    for key in (
        "confirm_index",
        "entry_index",
        "signal_index",
        "final_index",
        "break_index",
        "pullback_index",
    ):
        v = meta.get(key)
        if isinstance(v, int):
            return max(0, min(v, len(bars) - 1))
    ts = parse_iso_ts(created_at or "")
    if ts is not None:
        return nearest_bar_index(bars, ts)
    return None


def signal_focus_viewport(
    meta: dict[str, Any],
    bars: list[OhlcBar],
    *,
    created_at: str | None = None,
    pad_left: int = 40,
    pad_right: int = 18,
) -> dict[str, int] | None:
    """زوم اولیه دور کندلی که الگو سیگنال شده."""
    idx = signal_bar_index(meta, bars, created_at=created_at)
    if idx is None:
        return None
    g0 = max(0, idx - pad_left)
    g1 = min(len(bars) - 1, idx + pad_right)
    if g1 <= g0:
        return None
    return {"from": bar_unix(bars[g0]), "to": bar_unix(bars[g1])}


def live_pattern_viewport(
    category: str, meta: dict[str, Any], bars: list[OhlcBar]
) -> dict[str, float | int] | None:
    cat = (category or "").strip().lower()
    if cat == "triangle":
        return triangle_viewport(meta, bars)
    if cat in ("trendline", "channel") and meta:
        return _trendline_focus_viewport(meta, bars)
    return None


TRENDLINE_LINE_EXTEND_RATIO = 0.5


def trendline_local_indices(
    meta: dict[str, Any], n_bars: int, *, wo: int | None = None
) -> tuple[int, int, int]:
    """window_offset و start_i/end_i محلی نسبت به پنجرهٔ فیت — نه اندیس سراسری سری."""
    w = int(meta.get("window_offset") or 0) if wo is None else int(wo)
    i0 = int(meta.get("start_i") or 0)
    i1_raw = meta.get("end_i", i0)
    i1 = int(i1_raw) if isinstance(i1_raw, (int, float)) else i0
    if i1 < i0:
        i0, i1 = i1, i0
    last_li = max(0, n_bars - 1 - w)
    if i0 > last_li + 32:
        i0 -= w
        i1 -= w
    i0 = max(0, min(i0, last_li))
    i1 = max(i0, min(i1, last_li))
    return w, i0, i1


def _trendline_extended_local_range(li0: int, li_end: int) -> tuple[int, int]:
    span = max(1, li_end - li0)
    pad = int(round(span * TRENDLINE_LINE_EXTEND_RATIO))
    return li0 - pad, li_end + pad


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
    wo, li0, li1 = trendline_local_indices(meta, len(bars))
    # مثل چارت الگو: خط تا آخرین کندل می‌رود، بعد از هر طرف نصف همین طول اضافه می‌شود.
    last_li = len(bars) - 1 - wo
    li_end = max(li1, last_li)
    li_from, li_to = _trendline_extended_local_range(li0, li_end)
    pts: list[dict[str, float | int]] = []
    seen_t: set[int] = set()
    for li in range(li_from, li_to + 1):
        t = _time_at_extended_index(bars, wo, li)
        if t in seen_t:
            continue
        seen_t.add(t)
        pts.append({"time": t, "value": float(slope) * li + float(intercept)})
    return pts


def _y_line(meta: dict[str, Any], bars: list[OhlcBar], *, upper: bool) -> list[dict[str, float | int]]:
    return _trendline_line_points(meta, bars, upper=upper)


def position_overlays(pos: dict[str, Any], *, mark: float | None = None) -> dict[str, Any]:
    del pos, mark
    return {"hlines": [], "segments": [], "lines": [], "markers": []}


def position_box_payload(pos: dict[str, Any], bars: list[OhlcBar]) -> dict[str, Any] | None:
    """باکس لانگ/شورت مثل ابزار TradingView؛ بدون خط Entry/SL/TP."""
    try:
        entry = float(pos["entry_price"])
        sl = float(pos["sl_price"])
        tp = float(pos["tp_price"])
    except (KeyError, TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    notional = pos.get("notional_usdt")
    qty = float(notional) / entry if isinstance(notional, (int, float)) and notional > 0 else 0.0
    t = bar_unix(bars[-1]) if bars else 0
    opened = str(pos.get("opened_at") or "").strip()
    if opened and bars:
        try:
            dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            target = int(dt.timestamp())
            t = min((bar_unix(b) for b in bars), key=lambda u: abs(u - target))
        except ValueError:
            pass
    return {
        "direction": "short" if str(pos.get("direction") or "") == "short" else "long",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "qty": qty,
        "time": t,
    }


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

    elif cat == "scalp":
        ep = meta.get("entry_px")
        sl = meta.get("stop_px")
        tp = meta.get("tp_px")
        if isinstance(ep, (int, float)):
            hlines.append(_hline(float(ep), color="#fbbf24", label="ورود", style="solid"))
        if isinstance(sl, (int, float)):
            hlines.append(_hline(float(sl), color="#f87171", label="SL"))
        if isinstance(tp, (int, float)):
            hlines.append(_hline(float(tp), color="#42a5f5", label="TP"))
        for band_key, label, color in (
            ("upper_band", "باند بالا", "#ffb74d"),
            ("mid_band", "میانه", "#90caf9"),
            ("lower_band", "باند پایین", "#81c784"),
        ):
            v = meta.get(band_key)
            if isinstance(v, (int, float)):
                hlines.append(_hline(float(v), color=color, label=label))
        ei = meta.get("entry_index") or meta.get("confirm_index")
        if isinstance(ei, int):
            pos = "belowBar" if meta.get("direction") == "up" else "aboveBar"
            markers.append(_marker(bars, ei, text="ورود", color="#fbbf24", position=pos))

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


def bar_indices_for_unix_range(
    bars: list[OhlcBar], t_from: int, t_to: int
) -> tuple[int, int]:
    if not bars:
        return 0, 0
    g0 = 0
    g1 = len(bars) - 1
    for i, b in enumerate(bars):
        if bar_unix(b) >= t_from:
            g0 = i
            break
    for i in range(len(bars) - 1, -1, -1):
        if bar_unix(bars[i]) <= t_to:
            g1 = i
            break
    if g1 < g0:
        return 0, max(0, len(bars) - 1)
    return g0, g1


def _without_trade_labels(spec: dict[str, Any]) -> dict[str, Any]:
    """روی چارت پوزیشن فقط Entry / SL / TP می‌ماند؛ برچسب الگوی ورود تکرار نشود."""
    drop = {"ورود", "entry", "mark", "sl", "tp"}
    hlines = [
        h
        for h in (spec.get("hlines") or [])
        if str(h.get("label") or "").strip().lower() not in drop
    ]
    markers = [
        mk
        for mk in (spec.get("markers") or [])
        if str(mk.get("text") or "").strip().lower() not in drop
    ]
    return {
        "hlines": hlines,
        "segments": list(spec.get("segments") or []),
        "lines": list(spec.get("lines") or []),
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
    specs: list[dict[str, Any]] = []
    if category and m:
        spec = pattern_overlays(category, m, bars)
        if position:
            spec = _without_trade_labels(spec)
        specs.append(spec)
    if position:
        specs.append(position_overlays(position, mark=mark))
    overlays = merge_overlay_specs(*specs)
    box = position_box_payload(position, bars) if position else None
    payload: dict[str, Any] = {
        "timeframe": timeframe,
        "title": title,
        "candles": candles_payload(bars),
        "overlays": overlays,
    }
    if box:
        payload["position_box"] = box
    vp = live_pattern_viewport(cat, m, bars) if m else None
    if vp is None and m and cat == "scalp":
        vp = signal_focus_viewport(m, bars, created_at=created_at or "")
    if vp is None and position:
        opened = str(position.get("opened_at") or "") or (created_at or "")
        vp = signal_focus_viewport(m, bars, created_at=opened)
    if vp:
        payload["viewport"] = {
            "from": vp["from"],
            "to": vp["to"],
        }
    return payload


def overlays_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
