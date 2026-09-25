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


def spread_label_ys(ys: list[float], min_gap: float) -> list[float]:
    """برچسب‌های نزدیک را در محور قیمت از هم دور می‌کند تا روی هم ننشینند."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    prev: float | None = None
    for i in order:
        y = ys[i]
        if prev is not None and y < prev + min_gap:
            y = prev + min_gap
        out[i] = y
        prev = y
    return out


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
    # هفتاد درصد کندل‌های قدیمی حذف می‌شود تا انتهای نمودار جا برای باند و مسیر داشته باشد.
    keep = max(3, int(len(candles) * 0.30))
    candles = candles[-keep:]

    spot = float(plan.spot)
    b = float(plan.b)
    c = float(plan.c)
    draw_path = plan.first_confident and b > 0

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

    zone_lo = float(plan.zone_low) if plan.zone_low else None
    zone_hi = float(plan.zone_high) if plan.zone_high else None
    has_zone = zone_lo is not None and zone_hi is not None and zone_hi >= zone_lo
    if has_zone and zone_hi == zone_lo:
        pad_z = max(spot * 0.0015, 50.0)
        zone_lo, zone_hi = zone_lo - pad_z, zone_hi + pad_z
    # مقصد تصویر وسط زون است. اگر سهم افقی را از فاصلهٔ قیمت بگیریم،
    # حرکت کوتاه تا زون ناپدید می‌شود و فلش نقطه‌چین به سطح مقابل کل مسیر را می‌گیرد.
    dest = b if draw_path else spot
    # زون خودش مقصد است. فلش به سطح مقابل، مسیر را عوض‌شده نشان می‌دهد.
    draw_second = bool(
        draw_path and plan.two_legs and not has_zone and abs(c - dest) > spot * 0.01
    )
    forward = bar_days * forward_bars
    t_b = last_x + forward * (0.72 if draw_second else 1.0)
    t_c = last_x + forward

    ax.axhline(spot, color="#42a5f5", linewidth=1.0, linestyle="-", alpha=0.55, zorder=4)
    if plan.band_low:
        ax.axhline(plan.band_low, color="#ef5350", linewidth=1.4, linestyle="--", alpha=0.95, zorder=4)
    if plan.band_high:
        ax.axhline(plan.band_high, color="#66bb6a", linewidth=1.4, linestyle="--", alpha=0.9, zorder=4)
    if has_zone:
        ax.axhspan(zone_lo, zone_hi, color="#fdd835", alpha=0.45, zorder=1)
        ax.axhline(zone_lo, color="#fdd835", linewidth=1.3, zorder=4)
        ax.axhline(zone_hi, color="#fdd835", linewidth=1.3, zorder=4)
    if draw_path and not has_zone:
        ax.axhline(b, color="#ffb74d", linewidth=1.2, linestyle="--", alpha=0.85, zorder=4)
    if draw_path and abs(dest - spot) > spot * 0.0015:
        ax.plot(
            [last_x, t_b],
            [spot, dest],
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
    if draw_second:
        ax.axhline(c, color="#ce93d8", linewidth=1.2, linestyle="--", alpha=0.85, zorder=4)
        ax.plot(
            [t_b, t_c],
            [dest, c],
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
    extras = [spot]
    if draw_path:
        extras.append(dest)
        if draw_second:
            extras.append(c)
    for level in (plan.band_low, plan.band_high, plan.zone_low, plan.zone_high):
        if level:
            extras.append(float(level))
    ax.set_ylim(min(y_min, *extras) - pad, max(y_max, *extras) + pad)

    x_end = (t_c if draw_path else last_x + bar_days * 4) + bar_days * 2
    ax.set_xlim(xs[0] - bar_days * 2, x_end)

    label_x = xs[-1] + (x_end - xs[-1]) * 0.04
    labels: list[tuple[float, str, str]] = [(spot, f"Spot {spot:,.0f}", "#90caf9")]
    if plan.band_low:
        labels.append((float(plan.band_low), f"Band {plan.band_low:,.0f}", "#ef9a9a"))
    if plan.band_high:
        labels.append((float(plan.band_high), f"Band {plan.band_high:,.0f}", "#a5d6a7"))
    if has_zone:
        labels.append(
            ((zone_lo + zone_hi) / 2.0, f"Zone {zone_lo:,.0f}-{zone_hi:,.0f}", "#ffe082")
        )
    if draw_second:
        labels.append((c, f"C {c:,.0f}", "#e1bee7"))
    y_span = max(y_max, *extras) - min(y_min, *extras)
    placed = spread_label_ys([y for y, _t, _c in labels], max(y_span * 0.045, spot * 0.004))
    for (y_val, label, color), text_y in zip(labels, placed):
        ax.annotate(
            label,
            xy=(label_x, y_val),
            xytext=(label_x, text_y),
            textcoords="data",
            va="center",
            ha="left",
            color=color,
            fontsize=8,
            fontfamily="monospace",
            annotation_clip=False,
            arrowprops=(
                {"arrowstyle": "-", "color": color, "lw": 0.6}
                if abs(text_y - y_val) > spot * 0.001
                else None
            ),
        )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.tick_params(colors="#b0bec5", labelsize=7, axis="x", rotation=25)
    plt.setp(ax.get_xticklabels(), ha="right")
    for spine in ax.spines.values():
        spine.set_color("#37474f")
    ax.grid(True, color="#263238", linewidth=0.6, alpha=0.7)
    ax.set_title(
        (
            f"BTCUSDT {interval} — مسیر سناریو (Spot → B → C)"
            if draw_path
            else f"BTCUSDT {interval} — مقصد اول نامشخص"
        ),
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
