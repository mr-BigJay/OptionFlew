from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from optionflow.scenario_narrative import ScenarioPlan

logger = logging.getLogger("optionflow.chart")

ReportChartKind = Literal["4h", "daily"]

BINANCE_KLINES_PRIMARY = "https://api.binance.com/api/v3/klines"
BINANCE_KLINES_MIRROR = "https://data-api.binance.vision/api/v3/klines"


def chart_settings_for_report(report_kind: ReportChartKind) -> tuple[str, int, int]:
    """بازه و تعداد کندل: 4h گزارش → چارت 1h؛ daily → چارت 4h.

    عدد وسط کندل‌های قبل از قیمت فعلی است (فضای مسیر جلو جداست).
    """
    if report_kind == "daily":
        return "4h", 180, 14
    return "1h", 180, 20


@dataclass
class _Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


def _parse_candles(raw: list[list[Any]]) -> list[_Candle]:
    out: list[_Candle] = []
    for k in raw:
        out.append(
            _Candle(
                ts=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
            )
        )
    return out


def fetch_btcusdt_klines(
    *,
    interval: str = "15m",
    limit: int = 160,
) -> list[_Candle]:
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
    last_err: Exception | None = None
    for url in (BINANCE_KLINES_PRIMARY, BINANCE_KLINES_MIRROR):
        try:
            r = httpx.get(url, params=params, timeout=45.0)
            r.raise_for_status()
            return _parse_candles(r.json())
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return []


def render_btcusdt_scenario_chart(
    plan: ScenarioPlan,
    *,
    report_kind: ReportChartKind = "4h",
    interval: str | None = None,
    candle_limit: int | None = None,
    forward_bars: int | None = None,
) -> bytes | None:
    """چارت واقعی BTCUSDT + مسیر دقیق Spot→B→C (قیمت‌ها از سناریو)."""
    default_interval, default_limit, default_forward = chart_settings_for_report(report_kind)
    interval = interval or default_interval
    candle_limit = candle_limit or default_limit
    forward_bars = forward_bars if forward_bars is not None else default_forward

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        logger.warning("matplotlib not installed; skip scenario chart")
        return None

    try:
        candles = fetch_btcusdt_klines(interval=interval, limit=candle_limit)
    except Exception as e:
        logger.warning("Binance klines failed: %s", e)
        return None

    if len(candles) < 3:
        return None

    spot = float(plan.spot)
    b = float(plan.b)
    c = float(plan.c)

    fig_w = 8.0
    fig_h = 4.6
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100, layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(candle.ts) for candle in candles]
    bar_w = (xs[1] - xs[0]) * 0.65 if len(xs) > 1 else 0.01

    for candle, x in zip(candles, xs):
        o, h, l, cl = candle.open, candle.high, candle.low, candle.close
        up = cl >= o
        color = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.9, solid_capstyle="round")
        body_h = max(abs(cl - o), spot * 0.00002)
        ax.add_patch(
            Rectangle(
                (x - bar_w / 2, min(o, cl)),
                bar_w,
                body_h,
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )

    last_x = xs[-1]
    bar_days = xs[-1] - xs[-2] if len(xs) > 1 else 15 / (24 * 60)

    d1 = abs(spot - b)
    d2 = abs(b - c)
    total = d1 + d2
    frac1 = (d1 / total) if total > 0 else 0.5
    t_b = last_x + bar_days * forward_bars * frac1
    t_c = last_x + bar_days * forward_bars

    ax.axhline(spot, color="#42a5f5", linewidth=1.0, linestyle="-", alpha=0.55)
    ax.axhline(b, color="#ffb74d", linewidth=1.2, linestyle="--", alpha=0.85)
    ax.axhline(c, color="#ce93d8", linewidth=1.2, linestyle="--", alpha=0.85)

    ax.plot(
        [last_x, t_b],
        [spot, b],
        color="#ff9800",
        linewidth=2.4,
        linestyle="-",
        marker="o",
        markersize=7,
        markerfacecolor="#ff9800",
        markeredgecolor="#ffffff",
        markeredgewidth=0.8,
        zorder=5,
    )
    ax.plot(
        [t_b, t_c],
        [b, c],
        color="#ff9800",
        linewidth=2.4,
        linestyle=(0, (1.2, 2.4)),
        alpha=0.38,
        solid_capstyle="round",
        zorder=4,
    )
    ax.plot(
        [t_c],
        [c],
        linestyle="none",
        marker="o",
        markersize=7,
        markerfacecolor="#ff9800",
        markeredgecolor="#ffffff",
        markeredgewidth=0.8,
        alpha=0.55,
        zorder=5,
    )

    ax.scatter([last_x], [spot], s=80, c="#42a5f5", edgecolors="white", linewidths=1, zorder=6)

    y_min = min(candle.low for candle in candles)
    y_max = max(candle.high for candle in candles)
    pad = max(spot * 0.002, 80.0)
    ax.set_ylim(min(y_min, spot, b, c) - pad, max(y_max, spot, b, c) + pad)

    x_end = t_c + bar_days * 2
    ax.set_xlim(xs[0] - bar_days * 2, x_end)

    label_x = xs[-1] + (x_end - xs[-1]) * 0.02
    for y_val, label, color in (
        (spot, f"Spot {spot:,.2f}", "#90caf9"),
        (b, f"B {b:,.0f}", "#ffcc80"),
        (c, f"C {c:,.0f}", "#e1bee7"),
    ):
        ax.annotate(
            label,
            xy=(label_x, y_val),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            ha="left",
            color=color,
            fontsize=8,
            fontfamily="monospace",
            annotation_clip=False,
        )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.tick_params(colors="#b0bec5", labelsize=7, axis="x", rotation=25)
    plt.setp(ax.get_xticklabels(), ha="right")
    for spine in ax.spines.values():
        spine.set_color("#37474f")
    ax.grid(True, color="#263238", linewidth=0.6, alpha=0.7)
    ax.set_title(
        f"BTCUSDT {interval} — مسیر سناریو (Spot → B → C)",
        color="#eceff1",
        fontsize=11,
        pad=10,
    )
    ax.set_ylabel("USDT", color="#b0bec5", fontsize=9)

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        pad_inches=0.05,
    )
    plt.close(fig)
    buf.seek(0)
    return buf.read()
