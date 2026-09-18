from __future__ import annotations

import io
import logging
from typing import Any

from optionflow.patterns.indicators import rsi
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.chart")


def render_pattern_chart(bars: list[OhlcBar], hit: PatternHit) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None

    if hit.category == "divergence":
        return _render_divergence(bars, hit)
    return _render_price_pattern(bars, hit)


def _render_price_pattern(bars: list[OhlcBar], hit: PatternHit) -> bytes | None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    meta = hit.meta
    start = max(0, meta.get("pole_start", meta.get("start_i", 0) + meta.get("window_offset", 0)) - 15)
    if hit.category == "triangle":
        wo = meta.get("window_offset", len(bars) - 120)
        start = max(0, wo + meta.get("start_i", 0) - 10)
        end = min(len(bars), wo + meta.get("end_i", len(bars)) + 15)
    elif hit.category == "flag":
        start = max(0, meta.get("pole_start", 0) - 5)
        end = len(bars)
    else:
        end = len(bars)

    slice_bars = bars[start:end]
    if len(slice_bars) < 10:
        slice_bars = bars[-80:]
        start = len(bars) - len(slice_bars)

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110, layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(b.ts) for b in slice_bars]
    bar_w = (xs[1] - xs[0]) * 0.6 if len(xs) > 1 else 0.01
    for bar, x in zip(slice_bars, xs):
        o, h, l, c = bar.open, bar.high, bar.low, bar.close
        color = "#26a69a" if c >= o else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.8)
        ax.add_patch(
            Rectangle(
                (x - bar_w / 2, min(o, c)),
                bar_w,
                max(abs(c - o), c * 0.00002),
                facecolor=color,
                edgecolor=color,
            )
        )

    if hit.category == "triangle":
        su, iu = meta["upper_slope"], meta["upper_intercept"]
        sl, il = meta["lower_slope"], meta["lower_intercept"]
        wo = meta.get("window_offset", 0)
        i0 = meta["start_i"]
        i1 = meta["end_i"]
        x0 = mdates.date2num(bars[wo + i0].ts)
        x1 = mdates.date2num(bars[min(len(bars) - 1, wo + i1)].ts)
        y_u0 = su * i0 + iu
        y_u1 = su * i1 + iu
        y_l0 = sl * i0 + il
        y_l1 = sl * i1 + il
        ax.plot([x0, x1], [y_u0, y_u1], color="#ffb74d", linewidth=2, label="مقاومت")
        ax.plot([x0, x1], [y_l0, y_l1], color="#81c784", linewidth=2, label="حمایت")
        last_x = xs[-1]
        last_y = slice_bars[-1].close
        d = meta.get("kind")
        if d == "ascending":
            ty = y_u1 * 1.002
            ax.annotate("", xy=(last_x, ty), xytext=(last_x, last_y), arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=2))
        elif d == "descending":
            ty = y_l1 * 0.998
            ax.annotate("", xy=(last_x, ty), xytext=(last_x, last_y), arrowprops=dict(arrowstyle="->", color="#ef5350", lw=2))
        else:
            ty = (y_u1 + y_l1) / 2
            ax.annotate("", xy=(last_x, ty), xytext=(last_x, last_y), arrowprops=dict(arrowstyle="->", color="#ff9800", lw=2))

    elif hit.category == "flag":
        ps, pe = meta["pole_start"], meta["pole_end"]
        fh, fl = meta["flag_high"], meta["flag_low"]
        x_p0 = mdates.date2num(bars[ps].ts)
        x_p1 = mdates.date2num(bars[pe].ts)
        x_f1 = xs[-1]
        ax.plot([x_p0, x_p1], [bars[ps].close, bars[pe].close], color="#ff9800", linewidth=3, label="Pole")
        ax.plot([x_p1, x_f1], [fh, fh], color="#42a5f5", linewidth=1.5, linestyle="--")
        ax.plot([x_p1, x_f1], [fl, fl], color="#42a5f5", linewidth=1.5, linestyle="--")
        last_y = slice_bars[-1].close
        if meta["direction"] == "up":
            ax.annotate("", xy=(x_f1, fh * 1.003), xytext=(x_f1, last_y), arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=2))
        else:
            ax.annotate("", xy=(x_f1, fl * 0.997), xytext=(x_f1, last_y), arrowprops=dict(arrowstyle="->", color="#ef5350", lw=2))

    ax.set_title(
        f"BTCUSDT {hit.timeframe} — {hit.title_fa}",
        color="#eceff1",
        fontsize=10,
    )
    ax.tick_params(colors="#90a4ae", labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    for spine in ax.spines.values():
        spine.set_color("#37474f")
    ax.grid(True, color="#263238", alpha=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _render_divergence(bars: list[OhlcBar], hit: PatternHit) -> bytes | None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    meta = hit.meta
    ia, ib = meta["pivot_a"][0], meta["pivot_b"][0]
    start = max(0, min(ia, ib) - 20)
    end = min(len(bars), max(ia, ib) + 25)
    slice_bars = bars[start:end]
    closes = [b.close for b in bars[: end]]
    rs = rsi(closes)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), dpi=110, height_ratios=[2, 1], layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    for ax in (ax1, ax2):
        ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(b.ts) for b in slice_bars]
    ax1.plot(xs, [b.close for b in slice_bars], color="#90caf9", linewidth=1.2)
    pa, pb = meta["pivot_a"], meta["pivot_b"]
    ax1.scatter(
        [mdates.date2num(bars[pa[0]].ts), mdates.date2num(bars[pb[0]].ts)],
        [pa[1], pb[1]],
        c="#ff9800",
        s=60,
        zorder=5,
    )
    ax1.plot(
        [mdates.date2num(bars[pa[0]].ts), mdates.date2num(bars[pb[0]].ts)],
        [pa[1], pb[1]],
        color="#ff9800",
        linestyle="--",
        alpha=0.8,
    )

    rsi_slice = rs[start:end]
    ax2.plot(xs, [v if v is not None else float("nan") for v in rsi_slice], color="#ce93d8", linewidth=1.2)
    ra, rb = meta["rsi_a"], meta["rsi_b"]
    ax2.scatter(
        [mdates.date2num(bars[pa[0]].ts), mdates.date2num(bars[pb[0]].ts)],
        [ra, rb],
        c="#ff9800",
        s=50,
    )
    ax2.axhline(70, color="#455a64", linewidth=0.6)
    ax2.axhline(30, color="#455a64", linewidth=0.6)
    ax2.set_ylim(0, 100)

    direction = meta.get("direction")
    last_x = xs[-1]
    last_y = slice_bars[-1].close
    if direction == "up":
        ax1.annotate("", xy=(last_x, last_y * 1.01), xytext=(last_x, last_y), arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=2))
    else:
        ax1.annotate("", xy=(last_x, last_y * 0.99), xytext=(last_x, last_y), arrowprops=dict(arrowstyle="->", color="#ef5350", lw=2))

    ax1.set_title(f"BTCUSDT {hit.timeframe} — {hit.title_fa}", color="#eceff1", fontsize=10)
    for ax in (ax1, ax2):
        ax.tick_params(colors="#90a4ae", labelsize=6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax2.set_ylabel("RSI", color="#90a4ae", fontsize=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
