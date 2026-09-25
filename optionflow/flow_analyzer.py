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


def top_strikes(strikes: dict[float, float], n: int = 3) -> list[tuple[float, float]]:
    return sorted(strikes.items(), key=lambda x: -x[1])[:n]


def top_strikes_near_spot(
    strikes: dict[float, float],
    spot: float,
    n: int = 2,
    *,
    pct_lo: float,
    pct_hi: float,
) -> list[tuple[float, float]]:
    if spot <= 0 or not strikes:
        return []
    lo, hi = spot * pct_lo, spot * pct_hi
    band = {k: v for k, v in strikes.items() if lo <= k <= hi and v > 0}
    if not band:
        return []
    return sorted(band.items(), key=lambda x: -x[1])[:n]


def dominant_strike_in_band(
    strikes: dict[float, float],
    spot: float,
    *,
    pct_lo: float,
    pct_hi: float,
    min_share: float = 0.35,
    cluster_share: float = 0.55,
    min_top_volume: float = 3.0,
) -> float | None:
    """Heaviest strike in the band, only when volume is actually concentrated.

    A smeared weighted center and a synthetic percent offset are not a target.
    Returns the strike price, or None when the book is empty, tiny, or diffuse.
    """
    if spot <= 0 or not strikes:
        return None
    lo, hi = spot * pct_lo, spot * pct_hi
    band = [(k, v) for k, v in strikes.items() if lo <= k <= hi and v > 0]
    if not band:
        return None
    band.sort(key=lambda item: -item[1])
    total = sum(v for _, v in band)
    if total <= 0:
        return None
    top_k, top_v = band[0]
    if top_v < min_top_volume:
        return None
    share = top_v / total
    if share >= min_share:
        return top_k
    if len(band) >= 2:
        second_k, second_v = band[1]
        near = abs(top_k - second_k) / spot <= 0.01
        if near and (top_v + second_v) / total >= cluster_share:
            return top_k
    return None


def directional_band(window_hours: float) -> tuple[float, float]:
    """(put floor, call cap) as multiples of spot. Same bands as guide.build_guidance."""
    if window_hours >= 20:
        return 0.88, 1.12
    if window_hours >= 4:
        return 0.915, 1.085
    return 0.935, 1.065


def confident_first_strike(main: FlowAnalysis, direction: str) -> int | None:
    """First destination only if buy-flow clusters on one strike in that direction."""
    if main.spot <= 0 or direction not in ("up", "down"):
        return None
    put_lo, call_hi = directional_band(main.window_hours)
    # Keep a small gap off spot so an at-the-money print is not treated as a destination.
    if direction == "up":
        strike = dominant_strike_in_band(
            main.call_buy_by_strike,
            main.spot,
            pct_lo=1.002,
            pct_hi=call_hi,
        )
    else:
        strike = dominant_strike_in_band(
            main.put_buy_by_strike,
            main.spot,
            pct_lo=put_lo,
            pct_hi=0.998,
        )
    if strike is None:
        return None
    level = int(round(strike))
    spot_i = int(round(main.spot))
    if direction == "up" and level <= spot_i:
        return None
    if direction == "down" and level >= spot_i:
        return None
    return level


def weighted_strike_center_near_spot(
    strikes: dict[float, float],
    spot: float,
    *,
    half_range_pct: float = 0.025,
) -> float | None:
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
