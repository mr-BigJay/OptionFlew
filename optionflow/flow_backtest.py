"""بک‌تست جهت جریان از معامله‌های تاریخی دریبیت، در برابر کندل واقعی."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.patterns.history import fetch_klines_range
from optionflow.patterns.ohlc import OhlcBar

# ارزش خرید کال + فروش پوت در برابر خرید پوت + فروش کال.
UP_RATIO = 1.15
DOWN_RATIO = 0.87


@dataclass(frozen=True)
class FlowBacktest:
    as_of: datetime
    lookback_hours: float
    forward_hours: float
    spot: float
    end_price: float
    direction: str
    matched: bool | None
    trade_count: int
    buyer_call: float
    buyer_put: float
    seller_call: float
    seller_put: float
    eff_buyer_call: float
    eff_buyer_put: float
    eff_seller_call: float
    eff_seller_put: float
    chart_png: bytes | None


def flow_direction(bull_usd: float, bear_usd: float) -> str:
    if bear_usd <= 0:
        return "up" if bull_usd > 0 else "flat"
    ratio = bull_usd / bear_usd
    if ratio >= UP_RATIO:
        return "up"
    if ratio <= DOWN_RATIO:
        return "down"
    return "flat"


def _matched(direction: str, spot: float, end_price: float) -> bool | None:
    if direction == "flat" or spot <= 0 or end_price <= 0:
        return None
    moved = (end_price - spot) / spot
    if abs(moved) < 0.001:
        return False
    if direction == "up":
        return moved > 0
    return moved < 0


def run_flow_backtest(
    as_of: datetime,
    *,
    lookback_hours: float = 2.0,
    forward_hours: float = 4.0,
) -> FlowBacktest:
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    else:
        as_of = as_of.astimezone(timezone.utc)
    lookback_hours = min(6.0, max(1.0, float(lookback_hours)))
    forward_hours = min(24.0, max(1.0, float(forward_hours)))
    if as_of > datetime.now(timezone.utc) - timedelta(minutes=5):
        raise ValueError("زمان تحلیل باید در گذشته باشد.")

    start = as_of - timedelta(hours=lookback_hours)
    end = as_of + timedelta(hours=forward_hours)
    start_ms = int(start.timestamp() * 1000)
    as_of_ms = int(as_of.timestamp() * 1000)

    with DeribitClient(timeout=45.0) as client:
        trades = client.fetch_option_trades(
            start_ms=start_ms,
            end_ms=as_of_ms,
            max_trades=30_000,
        )
    if not trades:
        raise ValueError("در این بازه معاملهٔ آپشن از دریبیت نیامد.")

    analysis = analyze_trades(
        trades,
        spot=None,
        window_label=f"{lookback_hours:g} ساعت قبل از لحظه",
        window_hours=lookback_hours,
    )
    contracts = analysis.contracts
    effective = analysis.effective_usd
    bull = effective.buyer_call + effective.seller_put
    bear = effective.buyer_put + effective.seller_call
    direction = flow_direction(bull, bear)

    interval = "15m" if forward_hours <= 12 else "1h"
    bars = fetch_klines_range(interval, start, end)
    if len(bars) < 3:
        raise ValueError("کندل قیمت برای این بازه نیامد.")
    spot = _price_at(bars, as_of)
    end_price = bars[-1].close
    chart = _render(bars, as_of, spot, end_price, direction)

    return FlowBacktest(
        as_of=as_of,
        lookback_hours=lookback_hours,
        forward_hours=forward_hours,
        spot=spot,
        end_price=end_price,
        direction=direction,
        matched=_matched(direction, spot, end_price),
        trade_count=analysis.trade_count,
        buyer_call=contracts.buyer_call,
        buyer_put=contracts.buyer_put,
        seller_call=contracts.seller_call,
        seller_put=contracts.seller_put,
        eff_buyer_call=effective.buyer_call,
        eff_buyer_put=effective.buyer_put,
        eff_seller_call=effective.seller_call,
        eff_seller_put=effective.seller_put,
        chart_png=chart,
    )


def _price_at(bars: list[OhlcBar], as_of: datetime) -> float:
    prior = [bar for bar in bars if bar.ts <= as_of]
    if prior:
        return prior[-1].close
    return bars[0].open


def _render(
    bars: list[OhlcBar],
    as_of: datetime,
    spot: float,
    end_price: float,
    direction: str,
) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=100, layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    xs = [mdates.date2num(bar.ts) for bar in bars]
    bar_w = (xs[1] - xs[0]) * 0.65 if len(xs) > 1 else 0.01
    for bar, x in zip(bars, xs):
        up = bar.close >= bar.open
        color = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [bar.low, bar.high], color=color, linewidth=0.8)
        ax.add_patch(
            Rectangle(
                (x - bar_w / 2, min(bar.open, bar.close)),
                bar_w,
                max(abs(bar.close - bar.open), spot * 0.00002),
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )
    mark = mdates.date2num(as_of)
    ax.axvline(mark, color="#ffb74d", linewidth=1.0, linestyle="--")
    ax.axhline(spot, color="#42a5f5", linewidth=1.0, alpha=0.8)
    ax.scatter([xs[-1]], [end_price], s=36, c="#ff9800", zorder=5)
    title = {"up": "پیش‌بینی: بالا", "down": "پیش‌بینی: پایین", "flat": "پیش‌بینی: بدون جهت"}
    ax.set_title(
        f"BTCUSDT — {title[direction]} — {spot:,.0f} → {end_price:,.0f}",
        color="#eceff1",
        fontsize=11,
    )
    ax.tick_params(colors="#b0bec5", labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    for spine in ax.spines.values():
        spine.set_color("#37474f")
    ax.grid(True, color="#263238", linewidth=0.5, alpha=0.7)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
