from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from optionflow.enriched_feeds import (
    deribit_option_stats,
    fetch_depth_imbalance,
    fetch_fear_greed,
    fetch_futures_bundle,
    fetch_spot_ticker,
    fetch_technical_4h,
)

DERIBIT = "https://www.deribit.com/api/v2/public"
BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"
FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


@dataclass
class MarketContext:
    binance_spot: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    liq_long_usd: float | None = None
    liq_short_usd: float | None = None
    gamma_resistance: int | None = None
    gamma_support: int | None = None
    max_pain: int | None = None
    max_pain_expiry: str | None = None
    news_hint: str | None = None
    mark_price: float | None = None
    index_price: float | None = None
    basis_pct: float | None = None
    spot_change_pct_24h: float | None = None
    depth_imbalance_pct: float | None = None
    taker_buy_sell_ratio: float | None = None
    long_short_ratio: float | None = None
    top_trader_long_short: float | None = None
    oi_change_pct_1h: float | None = None
    put_call_oi: float | None = None
    deribit_opt_volume: float | None = None
    avg_iv_pct: float | None = None
    fear_greed: int | None = None
    fear_greed_label: str | None = None
    rsi_4h: float | None = None
    ema20_4h: float | None = None
    structure_notes: list[str] = field(default_factory=list)
    summary_lines_fa: list[str] = field(default_factory=list)
    fetch_notes: list[str] = field(default_factory=list)


def _parse_instrument(name: str) -> tuple[str, float, str]:
    parts = name.split("-")
    expiry = parts[1]
    strike = float(parts[2])
    opt = "call" if parts[3].startswith("C") else "put"
    return expiry, strike, opt


def _fetch_deribit_book() -> list[dict[str, Any]]:
    r = httpx.get(
        f"{DERIBIT}/get_book_summary_by_currency",
        params={"currency": "BTC", "kind": "option"},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["result"]


def _compute_max_pain(
    books: list[dict[str, Any]], expiry: str, spot: float
) -> int | None:
    strikes: list[float] = []
    calls: dict[float, float] = {}
    puts: dict[float, float] = {}
    for row in books:
        name = row["instrument_name"]
        ex, strike, opt = _parse_instrument(name)
        if ex != expiry:
            continue
        oi = float(row.get("open_interest") or 0)
        if oi <= 0:
            continue
        strikes.append(strike)
        if opt == "call":
            calls[strike] = calls.get(strike, 0) + oi
        else:
            puts[strike] = puts.get(strike, 0) + oi
    if not strikes:
        return None
    strikes = sorted(set(strikes))
    best_k = strikes[0]
    best_pain = float("inf")
    for k in strikes:
        pain = 0.0
        for s, oi in calls.items():
            pain += oi * max(0.0, k - s)
        for s, oi in puts.items():
            pain += oi * max(0.0, s - k)
        if pain < best_pain:
            best_pain = pain
            best_k = k
    return int(round(best_k))


def _nearest_expiry_with_oi(books: list[dict[str, Any]]) -> str | None:
    expiries: dict[str, float] = {}
    for row in books:
        oi = float(row.get("open_interest") or 0)
        if oi <= 0:
            continue
        ex, _, _ = _parse_instrument(row["instrument_name"])
        expiries[ex] = expiries.get(ex, 0) + oi
    if not expiries:
        return None
    return max(expiries.items(), key=lambda x: x[1])[0]


def _gamma_levels(books: list[dict[str, Any]], spot: float, limit: int = 35) -> tuple[int | None, int | None]:
    ranked = sorted(
        [b for b in books if float(b.get("open_interest") or 0) > 0],
        key=lambda x: -float(x["open_interest"]),
    )[:limit]
    pos_by_strike: dict[float, float] = {}
    neg_by_strike: dict[float, float] = {}
    with httpx.Client(timeout=20.0) as client:
        for row in ranked:
            name = row["instrument_name"]
            _, strike, opt = _parse_instrument(name)
            oi = float(row["open_interest"])
            tr = client.get(f"{DERIBIT}/ticker", params={"instrument_name": name})
            if tr.status_code != 200:
                continue
            greeks = tr.json().get("result", {}).get("greeks") or {}
            gamma = float(greeks.get("gamma") or 0)
            gex = gamma * oi * spot
            if opt == "call":
                pos_by_strike[strike] = pos_by_strike.get(strike, 0) + gex
            else:
                neg_by_strike[strike] = neg_by_strike.get(strike, 0) + gex
    if not pos_by_strike:
        return None, None
    res = max(
        (s for s in pos_by_strike if s >= spot * 0.99),
        key=lambda s: pos_by_strike[s],
        default=None,
    )
    sup = max(
        (s for s in neg_by_strike if s <= spot * 1.01),
        key=lambda s: neg_by_strike[s],
        default=None,
    )
    return (int(round(res)) if res else None, int(round(sup)) if sup else None)


def _fetch_news_hint() -> str | None:
    try:
        r = httpx.get(FF_CALENDAR, timeout=15.0)
        if r.status_code != 200:
            return None
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=48)
        hits: list[str] = []
        for ev in r.json():
            if ev.get("country") not in ("USD", "US"):
                continue
            impact = (ev.get("impact") or "").lower()
            if impact not in ("high", "medium"):
                continue
            date_s = ev.get("date") or ""
            try:
                dt = datetime.fromisoformat(date_s.replace("Z", "+00:00"))
            except ValueError:
                continue
            if now <= dt <= horizon:
                hits.append(f"{ev.get('title', 'رویداد')} ({dt.astimezone().strftime('%m/%d %H:%M')})")
        if not hits:
            return None
        return "اخبار دلار ۴۸س: " + "؛ ".join(hits[:2])
    except Exception:
        return None


def _summary_lines_fa(ctx: MarketContext, deribit_spot: float) -> list[str]:
    lines: list[str] = []
    if ctx.fear_greed is not None:
        lines.append(
            f"شاخص ترس/طمع {ctx.fear_greed} ({ctx.fear_greed_label or '—'})"
        )
    if ctx.funding_rate is not None:
        fr = ctx.funding_rate * 100
        tag = "تمایل خرید با اهرم" if fr > 0.01 else "فشار روی خرید اهرمی" if fr < -0.01 else "فاندینگ خنثی"
        lines.append(f"فاندینگ آتی {fr:.3f}٪؛ {tag}.")
    if ctx.open_interest is not None:
        oi_bit = f"OI آتی {ctx.open_interest:,.0f} BTC"
        if ctx.oi_change_pct_1h is not None:
            oi_bit += f" (۱س: {ctx.oi_change_pct_1h:+.1f}٪)"
        lines.append(oi_bit + ".")
    if ctx.long_short_ratio is not None:
        lines.append(f"نسبت long/short حساب‌ها {ctx.long_short_ratio:.2f}.")
    if ctx.taker_buy_sell_ratio is not None:
        lines.append(f"خرید/فروش taker آتی {ctx.taker_buy_sell_ratio:.2f}.")
    if ctx.basis_pct is not None:
        lines.append(f"Basis آتی {ctx.basis_pct:+.2f}٪ (mark نسبت index).")
    if ctx.depth_imbalance_pct is not None:
        side = "تقاضا در دفتر" if ctx.depth_imbalance_pct > 0 else "عرضه در دفتر"
        lines.append(f"Order book: {side} ({ctx.depth_imbalance_pct:+.1f}٪).")
    if ctx.put_call_oi is not None:
        lines.append(f"Put/Call OI در Deribit {ctx.put_call_oi:.2f}.")
    if ctx.max_pain and ctx.max_pain_expiry:
        lines.append(f"Max pain سررسید {ctx.max_pain_expiry}: {ctx.max_pain:,}.")
    if ctx.gamma_resistance or ctx.gamma_support:
        lines.append(
            f"گاما: مقاومت ~{ctx.gamma_resistance or '—'} · حمایت ~{ctx.gamma_support or '—'}."
        )
    if ctx.rsi_4h is not None and ctx.ema20_4h is not None:
        pos = "بالای EMA20" if deribit_spot >= ctx.ema20_4h else "زیر EMA20"
        lines.append(f"RSI 4h {ctx.rsi_4h:.0f}؛ قیمت {pos} (EMA20≈{ctx.ema20_4h:,.0f}).")
    for sn in ctx.structure_notes[:2]:
        lines.append(sn)
    if ctx.news_hint:
        lines.append(ctx.news_hint)
    if ctx.liq_long_usd or ctx.liq_short_usd:
        lines.append(
            f"لیکوئید اخیر (نمونه): long {ctx.liq_long_usd or 0:,.0f}$ · short {ctx.liq_short_usd or 0:,.0f}$."
        )
    return lines[:6]


def collect_market_context(deribit_spot: float) -> MarketContext:
    ctx = MarketContext()
    notes: list[str] = []

    try:
        books = _fetch_deribit_book()
    except Exception as e:
        notes.append(f"Deribit OI: {e}")
        books = []

    if books:
        stats = deribit_option_stats(books)
        ctx.put_call_oi = stats.get("put_call_oi")
        ctx.deribit_opt_volume = stats.get("volume")
        if stats.get("avg_iv"):
            ctx.avg_iv_pct = float(stats["avg_iv"])

    expiry = _nearest_expiry_with_oi(books) if books else None
    if expiry and books:
        ctx.max_pain = _compute_max_pain(books, expiry, deribit_spot)
        ctx.max_pain_expiry = expiry
        try:
            gr, gs = _gamma_levels(books, deribit_spot)
            ctx.gamma_resistance = gr
            ctx.gamma_support = gs
        except Exception as e:
            notes.append(f"gamma: {e}")

    try:
        spot = fetch_spot_ticker()
        if "error" not in spot:
            ctx.binance_spot = spot.get("price")
            ctx.spot_change_pct_24h = spot.get("change_pct")
        else:
            notes.append(f"Binance spot {spot.get('error')}")
    except Exception as e:
        notes.append(f"spot: {e}")

    try:
        depth = fetch_depth_imbalance()
        if depth and "error" not in depth:
            ctx.depth_imbalance_pct = depth.get("imbalance_pct")
    except Exception as e:
        notes.append(f"depth: {e}")

    try:
        fut = fetch_futures_bundle()
        ctx.funding_rate = fut.get("funding")
        ctx.open_interest = fut.get("oi")
        ctx.mark_price = fut.get("mark")
        ctx.index_price = fut.get("index")
        ctx.basis_pct = fut.get("basis_pct")
        ctx.oi_change_pct_1h = fut.get("oi_change_pct")
        ctx.taker_buy_sell_ratio = fut.get("taker_ratio")
        ctx.long_short_ratio = fut.get("long_short")
        ctx.top_trader_long_short = fut.get("top_trader")
        ctx.liq_long_usd = fut.get("liq_long")
        ctx.liq_short_usd = fut.get("liq_short")
        for key in ("prem_error", "oi_error", "liq_error"):
            if key in fut:
                notes.append(f"Binance {key}")
    except Exception as e:
        notes.append(f"futures: {e}")

    try:
        fg = fetch_fear_greed()
        ctx.fear_greed = fg.get("value")
        ctx.fear_greed_label = fg.get("label")
    except Exception as e:
        notes.append(f"fng: {e}")

    try:
        tech = fetch_technical_4h()
        if tech and "error" not in tech:
            ctx.rsi_4h = tech.get("rsi_4h")
            ctx.ema20_4h = tech.get("ema20_4h")
    except Exception as e:
        notes.append(f"tech: {e}")

    try:
        from optionflow.structure_context import collect_structure_context

        struct = collect_structure_context(deribit_spot)
        ctx.structure_notes = struct.notes_fa[:2]
    except Exception as e:
        notes.append(f"structure: {e}")

    ctx.news_hint = _fetch_news_hint()
    ctx.fetch_notes = notes
    ctx.summary_lines_fa = _summary_lines_fa(ctx, deribit_spot)
    return ctx
