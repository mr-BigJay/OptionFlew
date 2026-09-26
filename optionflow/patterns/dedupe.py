from __future__ import annotations

from optionflow.patterns.types import PatternHit

_TOUCH_BUCKET = {"5m": 24, "15m": 12, "1h": 8, "4h": 4, "1d": 2}


def _touch_bucket(timeframe: str) -> int:
    return _TOUCH_BUCKET.get(timeframe, 12)


def _price_sig(points: object) -> str:
    if not isinstance(points, list):
        return ""
    out: list[str] = []
    for p in points:
        if isinstance(p, (int, float)):
            out.append(str(int(round(float(p)))))
    return "-".join(out)


def triangle_structure_key(
    meta: dict, timeframe: str = "", *, prefer_prices: bool = False
) -> str:
    """هویت مثلث، مستقل از مرحله و قیمت لحظه‌ای خط.

    در بخش الگو اندیس برخورد ملاک است تا کارت‌های قبلی هم یکی شوند.
    بکتست قیمت برخورد را ترجیح می‌دهد چون اندیس بعد از جابه‌جایی پنجره عوض می‌شود.
    """
    kind = str(meta.get("kind") or "")
    wo = int(meta.get("window_offset") or 0)
    bucket = _touch_bucket(timeframe or "15m")

    def _idx_sig(points: object) -> str:
        if not isinstance(points, list):
            return ""
        vals = [
            str((wo + int(t)) // bucket)
            for t in points
            if isinstance(t, (int, float))
        ]
        return "-".join(vals)

    hi = _idx_sig(meta.get("touch_highs"))
    lo = _idx_sig(meta.get("touch_lows"))
    idx = f"{kind}:h{hi}:l{lo}" if hi or lo else ""
    hi_px = _price_sig(meta.get("touch_high_prices"))
    lo_px = _price_sig(meta.get("touch_low_prices"))
    price = f"{kind}:ph{hi_px}:pl{lo_px}" if hi_px or lo_px else ""
    if prefer_prices and price:
        return price
    return idx or price or kind


def backtest_dedupe_key(hit: PatternHit, *, entry_on_early: bool = False) -> str:
    """کلید پایدار برای حذف تکرار در بکتست — هم‌راستا با بخش الگو."""
    meta = hit.meta or {}
    cat = hit.category
    if cat in ("trendline", "channel"):
        anchor = 2 if entry_on_early and cat == "trendline" else None
        return _trendline_channel_key(hit, meta, anchor_touches=anchor)
    if cat == "triangle":
        return (
            f"triangle:{triangle_structure_key(meta, hit.timeframe, prefer_prices=True)}"
        )
    if cat == "ema50":
        alert = meta.get("alert_key")
        if alert:
            return f"ema50:{alert}"
        ep = meta.get("entry_px")
        px = int(round(float(ep))) if isinstance(ep, (int, float)) else 0
        mode = meta.get("mode") or ""
        direction = meta.get("direction") or ""
        return f"ema50:{mode}:{direction}:e{px}"
    if cat == "flag":
        fh = meta.get("flag_high")
        fl = meta.get("flag_low")
        fhk = int(round(float(fh))) if isinstance(fh, (int, float)) else 0
        flk = int(round(float(fl))) if isinstance(fl, (int, float)) else 0
        return f"flag:{hit.pattern_id}:h{fhk}:l{flk}"
    if cat == "three_rp":
        sts = meta.get("signal_ts")
        if sts:
            d = meta.get("direction") or ""
            return f"three_rp:{hit.pattern_id}:{sts}:{d}"
        px = (
            meta.get("pattern_low")
            if "bear" in hit.pattern_id
            else meta.get("pattern_high")
        )
        pk = int(round(float(px))) if isinstance(px, (int, float)) else 0
        return f"three_rp:{hit.pattern_id}:p{pk}"
    return hit.pattern_id


def _trendline_channel_key(
    hit: PatternHit, meta: dict, *, anchor_touches: int | None = None
) -> str:
    side = meta.get("side") or meta.get("early_side") or ""
    wo = int(meta.get("window_offset") or 0)
    bucket = _touch_bucket(hit.timeframe)
    hi = [int(t) for t in meta.get("touch_highs") or []]
    lo = [int(t) for t in meta.get("touch_lows") or []]
    if anchor_touches and (hi or lo):
        if side == "low" or (lo and not hi):
            lo = lo[:anchor_touches]
            hi = []
        else:
            hi = hi[:anchor_touches]
            lo = []
    if hi or lo:
        g_hi = sorted(wo + t for t in hi)
        g_lo = sorted(wo + t for t in lo)
        hi_sig = "-".join(str(x // bucket) for x in g_hi)
        lo_sig = "-".join(str(x // bucket) for x in g_lo)
        return f"{hit.category}:{side}:h{hi_sig}:l{lo_sig}"
    y = meta.get("y_now")
    yk = int(round(float(y) / 100.0)) if isinstance(y, (int, float)) else 0
    return f"{hit.category}:{side}:y{yk}"
