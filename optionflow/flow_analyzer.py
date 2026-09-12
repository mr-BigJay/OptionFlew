from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FlowBucket:
    buyer_call: float = 0.0
    buyer_put: float = 0.0
    seller_call: float = 0.0
    seller_put: float = 0.0

    @property
    def total(self) -> float:
        return self.buyer_call + self.buyer_put + self.seller_call + self.seller_put


@dataclass(frozen=True)
class EffectiveBucket:
    buyer_call: float = 0.0
    buyer_put: float = 0.0
    seller_call: float = 0.0
    seller_put: float = 0.0


@dataclass
class FlowAnalysis:
    spot: float
    trade_count: int
    window_label: str
    contracts: FlowBucket
    effective_usd: EffectiveBucket
    window_hours: float = 4.0
    call_buy_by_strike: dict[float, float] = field(default_factory=dict)
    put_buy_by_strike: dict[float, float] = field(default_factory=dict)
    call_sell_by_strike: dict[float, float] = field(default_factory=dict)
    put_sell_by_strike: dict[float, float] = field(default_factory=dict)


def parse_instrument(name: str) -> tuple[float, str]:
    parts = name.split("-")
    if len(parts) < 4:
        raise ValueError(f"Unexpected instrument: {name}")
    strike = float(parts[2])
    opt = "call" if parts[3].upper().startswith("C") else "put"
    return strike, opt


def _contracts(trade: dict[str, Any]) -> float:
    return float(trade.get("contracts") or trade.get("amount") or 0)


def analyze_trades(
    trades: list[dict[str, Any]],
    *,
    spot: float | None = None,
    window_label: str = "۲ ساعت اخیر",
    window_hours: float = 4.0,
) -> FlowAnalysis:
    if not trades and spot is None:
        raise ValueError("No trades and no spot price provided")

    idx_spot = spot if spot is not None else float(trades[0]["index_price"])
    bc = bp = sc = sp = 0.0
    ebc = ebp = esc = esp = 0.0
    call_buy: dict[float, float] = defaultdict(float)
    put_buy: dict[float, float] = defaultdict(float)
    call_sell: dict[float, float] = defaultdict(float)
    put_sell: dict[float, float] = defaultdict(float)

    for t in trades:
        strike, opt = parse_instrument(t["instrument_name"])
        direction = t["direction"]
        c = _contracts(t)
        # USD notional of underlying exposure (approx. delta-neutral weighting baseline)
        usd = c * float(t.get("index_price") or idx_spot)

        if direction == "buy" and opt == "call":
            bc += c
            ebc += usd
            call_buy[strike] += c
        elif direction == "buy" and opt == "put":
            bp += c
            ebp += usd
            put_buy[strike] += c
        elif direction == "sell" and opt == "call":
            sc += c
            esc += usd
            call_sell[strike] += c
        elif direction == "sell" and opt == "put":
            sp += c
            esp += usd
            put_sell[strike] += c

    contracts = FlowBucket(
        buyer_call=bc, buyer_put=bp, seller_call=sc, seller_put=sp
    )
    effective = EffectiveBucket(
        buyer_call=ebc, buyer_put=ebp, seller_call=esc, seller_put=esp
    )

    return FlowAnalysis(
        spot=idx_spot,
        trade_count=len(trades),
        window_label=window_label,
        window_hours=window_hours,
        contracts=contracts,
        effective_usd=effective,
        call_buy_by_strike=dict(call_buy),
        put_buy_by_strike=dict(put_buy),
        call_sell_by_strike=dict(call_sell),
        put_sell_by_strike=dict(put_sell),
    )


def weighted_strike_center(strikes: dict[float, float]) -> float | None:
    if not strikes:
        return None
    total = sum(strikes.values())
    if total <= 0:
        return None
    return sum(k * v for k, v in strikes.items()) / total


def weighted_strike_center_near_spot(
    strikes: dict[float, float],
    spot: float,
    *,
    half_range_pct: float = 0.025,
) -> float | None:
    """Volume-weighted strike center; far OTM strikes decay (short-horizon levels)."""
    if not strikes or spot <= 0:
        return None
    half = max(half_range_pct, 0.005)
    total_w = 0.0
    weighted = 0.0
    for strike, vol in strikes.items():
        if vol <= 0:
            continue
        dist_pct = abs(strike - spot) / spot
        w = vol / (1.0 + (dist_pct / half) ** 2)
        weighted += strike * w
        total_w += w
    if total_w <= 0:
        return None
    return weighted / total_w


def top_strikes(strikes: dict[float, float], n: int = 3) -> list[tuple[float, float]]:
    return sorted(strikes.items(), key=lambda x: -x[1])[:n]
