from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pivot:
    index: int
    price: float
    kind: str  # high | low


def zigzag_pivots(
    highs: list[float],
    lows: list[float],
    *,
    pct: float,
) -> list[Pivot]:
    """پیوت ساده بر اساس درصد برگشت."""
    if len(highs) < 5:
        return []
    pivots: list[Pivot] = []
    last_pivot_i = 0
    last_pivot_price = (highs[0] + lows[0]) / 2
    direction = 0  # 1 up leg, -1 down leg
    extreme_i = 0
    extreme_price = highs[0]

    for i in range(1, len(highs)):
        hi, lo = highs[i], lows[i]
        if direction >= 0:
            if hi >= extreme_price:
                extreme_price = hi
                extreme_i = i
            elif (extreme_price - lo) / max(extreme_price, 1e-9) >= pct:
                pivots.append(Pivot(extreme_i, extreme_price, "high"))
                direction = -1
                extreme_price = lo
                extreme_i = i
        if direction <= 0:
            if lo <= extreme_price:
                extreme_price = lo
                extreme_i = i
            elif (hi - extreme_price) / max(extreme_price, 1e-9) >= pct:
                pivots.append(Pivot(extreme_i, extreme_price, "low"))
                direction = 1
                extreme_price = hi
                extreme_i = i

    if len(pivots) >= 2 and pivots[-1].index < len(highs) - 3:
        if direction == 1:
            pivots.append(Pivot(extreme_i, extreme_price, "high"))
        elif direction == -1:
            pivots.append(Pivot(extreme_i, extreme_price, "low"))
    return pivots
