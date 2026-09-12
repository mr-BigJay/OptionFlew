from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

DERIBIT = "https://www.deribit.com/api/v2/public"
INSTRUMENT = "BTC-PERPETUAL"


@dataclass
class FvgZone:
    kind: Literal["bullish", "bearish"]
    low: int
    high: int
    distance_pct: float


@dataclass
class StructureContext:
    pdh: int | None = None
    pdl: int | None = None
    pwh: int | None = None
    pwl: int | None = None
    range_position: Literal["premium", "discount", "equilibrium"] | None = None
    sweeps: list[str] = field(default_factory=list)
    nearest_fvg: FvgZone | None = None
    notes_fa: list[str] = field(default_factory=list)
    fetch_notes: list[str] = field(default_factory=list)


def _fetch_ohlc(resolution: str, lookback_ms: int) -> list[tuple[float, float, float, float]] | None:
    end = int(time.time() * 1000)
    start = end - lookback_ms
    try:
        r = httpx.get(
            f"{DERIBIT}/get_tradingview_chart_data",
            params={
                "instrument_name": INSTRUMENT,
                "start_timestamp": start,
                "end_timestamp": end,
                "resolution": resolution,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        payload = r.json().get("result") or {}
        opens = payload.get("open") or []
        highs = payload.get("high") or []
        lows = payload.get("low") or []
        closes = payload.get("close") or []
        n = min(len(opens), len(highs), len(lows), len(closes))
        if n < 3:
            return None
        out: list[tuple[float, float, float, float]] = []
        for i in range(n):
            out.append(
                (
                    float(opens[i]),
                    float(highs[i]),
                    float(lows[i]),
                    float(closes[i]),
                )
            )
        return out
    except Exception:
        return None


def _daily_levels(daily: list[tuple[float, float, float, float]]) -> tuple[int | None, ...]:
    if len(daily) < 2:
        return None, None, None, None
    _, dh, dl, _ = daily[-2]
    pdh, pdl = int(round(dh)), int(round(dl))
    pwh = pwl = None
    if len(daily) >= 9:
        window = daily[-9:-2]
        pwh = int(round(max(c[1] for c in window)))
        pwl = int(round(min(c[2] for c in window)))
    elif len(daily) >= 3:
        window = daily[:-2]
        pwh = int(round(max(c[1] for c in window)))
        pwl = int(round(min(c[2] for c in window)))
    return pdh, pdl, pwh, pwl


def _range_position(
    spot: float, pdh: int | None, pdl: int | None
) -> Literal["premium", "discount", "equilibrium"] | None:
    if pdh is None or pdl is None or pdh <= pdl:
        return None
    eq = (pdh + pdl) / 2.0
    band = (pdh - pdl) * 0.12
    if spot >= eq + band:
        return "premium"
    if spot <= eq - band:
        return "discount"
    return "equilibrium"


def _detect_sweeps(
    h4: list[tuple[float, float, float, float]],
    *,
    pdh: int | None,
    pdl: int | None,
    pwh: int | None,
    pwl: int | None,
) -> list[str]:
    if len(h4) < 2:
        return []
    _, hi, lo, cl = h4[-2]
    sweeps: list[str] = []
    if pdh is not None and hi > pdh and cl < pdh:
        sweeps.append(f"sweep_pdh:{pdh}")
    if pdl is not None and lo < pdl and cl > pdl:
        sweeps.append(f"sweep_pdl:{pdl}")
    if pwh is not None and hi > pwh and cl < pwh:
        sweeps.append(f"sweep_pwh:{pwh}")
    if pwl is not None and lo < pwl and cl > pwl:
        sweeps.append(f"sweep_pwl:{pwl}")
    return sweeps


def _nearest_fvg(
    h4: list[tuple[float, float, float, float]],
    spot: float,
    *,
    max_dist_pct: float = 0.03,
) -> FvgZone | None:
    best: FvgZone | None = None
    for i in range(2, len(h4)):
        _, h2, l2, _ = h4[i - 2]
        _, hi, lo, _ = h4[i]
        if lo > h2:
            z_lo, z_hi = int(round(h2)), int(round(lo))
            mid = (z_lo + z_hi) / 2.0
            dist = abs(spot - mid) / spot
            if dist <= max_dist_pct and (best is None or dist < best.distance_pct):
                best = FvgZone("bullish", z_lo, z_hi, dist)
        if hi < l2:
            z_lo, z_hi = int(round(hi)), int(round(l2))
            mid = (z_lo + z_hi) / 2.0
            dist = abs(spot - mid) / spot
            if dist <= max_dist_pct and (best is None or dist < best.distance_pct):
                best = FvgZone("bearish", z_lo, z_hi, dist)
    return best


def _sweep_label_fa(code: str) -> str:
    kind, _, level = code.partition(":")
    level_s = f"{int(level):,}" if level.isdigit() else level
    labels = {
        "sweep_pdh": f"در کندل ۴س اخیر، سقف روزانه (PDH) {level_s} لمس و برگشت داده شد",
        "sweep_pdl": f"در کندل ۴س اخیر، کف روزانه (PDL) {level_s} لمس و برگشت داده شد",
        "sweep_pwh": f"سقف هفتگی (PWH) {level_s} sweep و برگشت دیده شد",
        "sweep_pwl": f"کف هفتگی (PWL) {level_s} sweep و برگشت دیده شد",
    }
    return labels.get(kind, code)


def collect_structure_context(spot: float) -> StructureContext:
    ctx = StructureContext()
    notes: list[str] = []

    daily = _fetch_ohlc("1D", 60 * 86400000)
    if daily is None:
        notes.append("Deribit daily candles unavailable")
    else:
        ctx.pdh, ctx.pdl, ctx.pwh, ctx.pwl = _daily_levels(daily)
        ctx.range_position = _range_position(spot, ctx.pdh, ctx.pdl)

    h4 = _fetch_ohlc("240", 45 * 86400000)
    if h4 is None:
        notes.append("Deribit 4h candles unavailable")
    else:
        ctx.sweeps = _detect_sweeps(
            h4,
            pdh=ctx.pdh,
            pdl=ctx.pdl,
            pwh=ctx.pwh,
            pwl=ctx.pwl,
        )
        ctx.nearest_fvg = _nearest_fvg(h4, spot)

    ctx.fetch_notes = notes
    ctx.notes_fa = structure_notes_fa(ctx)
    return ctx


def structure_notes_fa(ctx: StructureContext) -> list[str]:
    lines: list[str] = []
    if ctx.range_position == "premium" and ctx.pdh and ctx.pdl:
        lines.append(
            f"قیمت در محدودهٔ premium نسبت به بازهٔ دیروز "
            f"(PDL {ctx.pdl:,} تا PDH {ctx.pdh:,})؛ احتمال اصلاح یا جذب فروش بیشتر دیده می‌شود."
        )
    elif ctx.range_position == "discount" and ctx.pdh and ctx.pdl:
        lines.append(
            f"قیمت در discount همان بازهٔ روزانه "
            f"({ctx.pdl:,}–{ctx.pdh:,})؛ تمایل به بازگشت به میانهٔ range محتمل‌تر است."
        )
    elif ctx.range_position == "equilibrium" and ctx.pdh and ctx.pdl:
        lines.append(
            f"قیمت نزدیک equilibrium بازهٔ دیروز (بین PDL {ctx.pdl:,} و PDH {ctx.pdh:,}) است."
        )

    for s in ctx.sweeps[:2]:
        lines.append(_sweep_label_fa(s) + " (liquidity sweep).")

    fvg = ctx.nearest_fvg
    if fvg:
        kind_fa = "صعودی" if fvg.kind == "bullish" else "نزولی"
        lines.append(
            f"FVG {kind_fa} ۴س نزدیک قیمت بین {fvg.low:,} و {fvg.high:,} "
            f"(حدود {fvg.distance_pct * 100:.1f}٪ فاصله)؛ ممکن است به‌عنوان magnet یا محل پر شدن گپ دیده شود."
        )

    return lines
