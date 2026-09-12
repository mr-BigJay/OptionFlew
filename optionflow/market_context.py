from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

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
    fetch_notes: list[str] = field(default_factory=list)


def _parse_instrument(name: str) -> tuple[str, float, str]:
    parts = name.split("-")
    expiry = parts[1]
    strike = float(parts[2])
    opt = "call" if parts[3].startswith("C") else "put"
    return expiry, strike, opt


def _fetch_binance_context() -> dict[str, Any]:
    out: dict[str, Any] = {}
    with httpx.Client(timeout=20.0) as client:
        spot = client.get(f"{BINANCE_SPOT}/api/v3/ticker/price", params={"symbol": "BTCUSDT"})
        if spot.status_code == 200:
            out["spot"] = float(spot.json()["price"])
        else:
            out["spot_error"] = spot.status_code

        prem = client.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
        if prem.status_code == 200:
            data = prem.json()
            out["funding"] = float(data.get("lastFundingRate", 0))
            out["mark"] = float(data.get("markPrice", 0))
        else:
            out["funding_error"] = prem.status_code

        oi = client.get(f"{BINANCE_FAPI}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"})
        if oi.status_code == 200:
            out["oi"] = float(oi.json().get("openInterest", 0))
        else:
            out["oi_error"] = oi.status_code

        liq = client.get(
            f"{BINANCE_FAPI}/fapi/v1/forceOrders",
            params={"symbol": "BTCUSDT", "limit": 100},
        )
        if liq.status_code == 200:
            long_usd = 0.0
            short_usd = 0.0
            for row in liq.json():
                p = float(row.get("price", 0))
                q = float(row.get("origQty", 0))
                usd = p * q
                side = row.get("side", "").upper()
                if side == "SELL":
                    long_usd += usd
                elif side == "BUY":
                    short_usd += usd
            out["liq_long"] = long_usd
            out["liq_short"] = short_usd
        else:
            out["liq_error"] = liq.status_code
    return out


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
            return "۴۸ ساعت آینده: رویداد مهم دلاری در تقویim دیده نشد."
        return "اخبار نزدیک: " + "؛ ".join(hits[:2])
    except Exception:
        return None


def collect_market_context(deribit_spot: float) -> MarketContext:
    ctx = MarketContext()
    notes: list[str] = []

    try:
        books = _fetch_deribit_book()
    except Exception as e:
        notes.append(f"Deribit OI: {e}")
        books = []

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
        b = _fetch_binance_context()
        ctx.binance_spot = b.get("spot")
        ctx.funding_rate = b.get("funding")
        ctx.open_interest = b.get("oi")
        ctx.liq_long_usd = b.get("liq_long")
        ctx.liq_short_usd = b.get("liq_short")
        for key in ("spot_error", "funding_error", "oi_error", "liq_error"):
            if key in b:
                notes.append(f"Binance {key}={b[key]} (VPS/IP may work)")
    except Exception as e:
        notes.append(f"Binance: {e}")

    ctx.news_hint = _fetch_news_hint()
    ctx.fetch_notes = notes
    return ctx
