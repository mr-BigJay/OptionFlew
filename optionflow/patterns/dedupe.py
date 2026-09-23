from __future__ import annotations

from optionflow.patterns.types import PatternHit

_TOUCH_BUCKET = {"5m": 24, "15m": 12, "1h": 8, "4h": 4, "1d": 2}


def _touch_bucket(timeframe: str) -> int:
    return _TOUCH_BUCKET.get(timeframe, 12)


def backtest_dedupe_key(hit: PatternHit) -> str:
    """کلید پایدار برای حذف تکرار در بکتست — هم‌راستا با بخش الگو."""
    meta = hit.meta or {}
    cat = hit.category
    if cat in ("trendline", "channel"):
        return _trendline_channel_key(hit, meta)
    if cat == "triangle":
        kind = meta.get("kind") or ""
        u = meta.get("upper_now")
        lo = meta.get("lower_now")
        uk = int(round(float(u))) if isinstance(u, (int, float)) else 0
        lk = int(round(float(lo))) if isinstance(lo, (int, float)) else 0
        stage = str(meta.get("stage") or "")
        return f"triangle:{kind}:{stage}:u{uk}:l{lk}"
    if cat == "ema50":
        ep = meta.get("entry_px")
        px = int(round(float(ep))) if isinstance(ep, (int, float)) else 0
        return f"ema50:{hit.pattern_id}:e{px}"
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


def _trendline_channel_key(hit: PatternHit, meta: dict) -> str:
    side = meta.get("side") or meta.get("early_side") or ""
    wo = int(meta.get("window_offset") or 0)
    bucket = _touch_bucket(hit.timeframe)
    hi = [int(t) for t in meta.get("touch_highs") or []]
    lo = [int(t) for t in meta.get("touch_lows") or []]
    if hi or lo:
        g_hi = sorted(wo + t for t in hi)
        g_lo = sorted(wo + t for t in lo)
        hi_sig = "-".join(str(x // bucket) for x in g_hi)
        lo_sig = "-".join(str(x // bucket) for x in g_lo)
        return f"{hit.category}:{side}:h{hi_sig}:l{lo_sig}"
    y = meta.get("y_now")
    yk = int(round(float(y) / 100.0)) if isinstance(y, (int, float)) else 0
    return f"{hit.category}:{side}:y{yk}"
