from __future__ import annotations

import time
from typing import Any

import httpx

BINANCE_SPOT = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"
FEAR_GREED = "https://api.alternative.me/fng/"


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0)


def fetch_spot_ticker() -> dict[str, Any]:
    with _client() as c:
        r = c.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": "BTCUSDT"})
        if r.status_code != 200:
            return {"error": r.status_code}
        d = r.json()
        return {
            "price": float(d["lastPrice"]),
            "volume": float(d.get("volume", 0)),
            "quote_volume": float(d.get("quoteVolume", 0)),
            "change_pct": float(d.get("priceChangePercent", 0)),
        }


def fetch_depth_imbalance(limit: int = 20) -> dict[str, Any]:
    with _client() as c:
        r = c.get(
            f"{BINANCE_SPOT}/api/v3/depth",
            params={"symbol": "BTCUSDT", "limit": limit},
        )
        if r.status_code != 200:
            return {"error": r.status_code}
        d = r.json()
        bid_usd = sum(float(p) * float(q) for p, q in d.get("bids", []))
        ask_usd = sum(float(p) * float(q) for p, q in d.get("asks", []))
        total = bid_usd + ask_usd
        if total <= 0:
            return {}
        return {
            "bid_usd": bid_usd,
            "ask_usd": ask_usd,
            "imbalance_pct": (bid_usd - ask_usd) / total * 100.0,
        }


def fetch_futures_bundle() -> dict[str, Any]:
    out: dict[str, Any] = {}
    with _client() as c:
        prem = c.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
        if prem.status_code == 200:
            data = prem.json()
            out["funding"] = float(data.get("lastFundingRate", 0))
            out["mark"] = float(data.get("markPrice", 0))
            out["index"] = float(data.get("indexPrice", 0))
            if out["index"]:
                out["basis_pct"] = (out["mark"] - out["index"]) / out["index"] * 100.0
        else:
            out["prem_error"] = prem.status_code

        oi = c.get(f"{BINANCE_FAPI}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"})
        if oi.status_code == 200:
            out["oi"] = float(oi.json().get("openInterest", 0))
        else:
            out["oi_error"] = oi.status_code

        oih = c.get(
            f"{BINANCE_FAPI}/futures/data/openInterestHist",
            params={"symbol": "BTCUSDT", "period": "1h", "limit": 2},
        )
        if oih.status_code == 200:
            rows = oih.json()
            if len(rows) >= 2:
                a = float(rows[-2]["sumOpenInterest"])
                b = float(rows[-1]["sumOpenInterest"])
                if a > 0:
                    out["oi_change_pct"] = (b - a) / a * 100.0

        for key, path, field in (
            ("taker_ratio", "takerlongshortRatio", "buySellRatio"),
            ("long_short", "globalLongShortAccountRatio", "longShortRatio"),
            ("top_trader", "topLongShortAccountRatio", "longShortRatio"),
        ):
            r = c.get(
                f"{BINANCE_FAPI}/futures/data/{path}",
                params={"symbol": "BTCUSDT", "period": "1h", "limit": 1},
            )
            if r.status_code == 200 and r.json():
                out[key] = float(r.json()[0].get(field, 0))

        liq = c.get(
            f"{BINANCE_FAPI}/fapi/v1/forceOrders",
            params={"symbol": "BTCUSDT", "limit": 50},
        )
        if liq.status_code == 200:
            long_usd = short_usd = 0.0
            for row in liq.json():
                p = float(row.get("price", 0))
                q = float(row.get("origQty", 0))
                usd = p * q
                if row.get("side", "").upper() == "SELL":
                    long_usd += usd
                elif row.get("side", "").upper() == "BUY":
                    short_usd += usd
            out["liq_long"] = long_usd
            out["liq_short"] = short_usd
        else:
            out["liq_error"] = liq.status_code
    return out


def fetch_fear_greed() -> dict[str, Any]:
    try:
        r = httpx.get(FEAR_GREED, params={"limit": 1}, timeout=15.0)
        if r.status_code != 200:
            return {}
        row = r.json().get("data", [{}])[0]
        return {
            "value": int(row.get("value", 0)),
            "label": str(row.get("value_classification", "")),
        }
    except Exception:
        return {}


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses <= 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def fetch_technical_4h() -> dict[str, Any]:
    end = int(time.time() * 1000)
    start = end - 120 * 4 * 3600 * 1000
    r = httpx.get(
        f"{BINANCE_SPOT}/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "4h", "startTime": start, "endTime": end},
        timeout=25.0,
    )
    if r.status_code != 200:
        return {"error": r.status_code}
    closes = [float(row[4]) for row in r.json()]
    if len(closes) < 21:
        return {}
    ema20 = closes[-20]
    k = 2 / 21
    for price in closes[-19:]:
        ema20 = price * k + ema20 * (1 - k)
    return {"rsi_4h": _rsi(closes), "ema20_4h": ema20, "last_close": closes[-1]}


def deribit_option_stats(books: list[dict[str, Any]]) -> dict[str, Any]:
    call_oi = put_oi = 0.0
    vol_sum = 0.0
    iv_samples: list[float] = []
    for row in books:
        oi = float(row.get("open_interest") or 0)
        vol = float(row.get("volume") or 0)
        vol_sum += vol
        name = row.get("instrument_name", "")
        parts = name.split("-")
        if len(parts) < 4:
            continue
        if parts[3].upper().startswith("C"):
            call_oi += oi
        else:
            put_oi += oi
        mp = row.get("mark_iv")
        if mp is not None:
            try:
                iv_samples.append(float(mp))
            except (TypeError, ValueError):
                pass
    out: dict[str, Any] = {
        "call_oi": call_oi,
        "put_oi": put_oi,
        "volume": vol_sum,
    }
    if put_oi > 0:
        out["put_call_oi"] = call_oi / put_oi
    if iv_samples:
        out["avg_iv"] = sum(iv_samples) / len(iv_samples)
    return out
