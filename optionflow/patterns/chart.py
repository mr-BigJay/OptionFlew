from __future__ import annotations

import io
import logging
from typing import Any

from optionflow.patterns.indicators import rsi
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.chart")

FORWARD_BARS_DEFAULT = {
    "5m": 36,
    "15m": 24,
    "1h": 18,
    "4h": 12,
    "1d": 8,
}


def render_pattern_chart(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    signal_index: int | None = None,
    forward_bars: int | None = None,
    outcome_success: bool | None = None,
) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
    except ImportError:
        return None

    if not bars:
        return None

    fwd = forward_bars
    if fwd is None and signal_index is not None:
        fwd = FORWARD_BARS_DEFAULT.get(hit.timeframe, 18)

    if hit.category == "divergence":
        return _render_divergence(
            bars,
            hit,
            signal_index=signal_index,
            forward_bars=fwd or 0,
            outcome_success=outcome_success,
        )
    return _render_price_pattern(
        bars,
        hit,
        signal_index=signal_index,
        forward_bars=fwd or 0,
        outcome_success=outcome_success,
    )


def _slice_range(
    bars: list[OhlcBar],
    hit: PatternHit,
    signal_index: int | None,
    forward_bars: int,
) -> tuple[int, int, int | None]:
    """Return start_idx, end_idx (exclusive), signal_idx in slice coordinates."""
    n = len(bars)
    sig = signal_index if signal_index is not None else n - 1
    sig = max(0, min(sig, n - 1))
    meta = hit.meta

    if hit.category == "triangle":
        wo = meta.get("window_offset", max(0, n - 120))
        i0 = wo + meta.get("start_i", 0)
        i1 = wo + meta.get("end_i", sig)
        start = max(0, min(i0, sig) - 15)
        end = min(n, max(i1, sig) + forward_bars + 1)
    elif hit.category == "flag":
        ps = meta.get("pole_start", max(0, sig - 30))
        start = max(0, ps - 8)
        end = min(n, sig + forward_bars + 1)
    else:
        start = max(0, sig - 60)
        end = min(n, sig + forward_bars + 1)

    return start, end, sig


def _candle_widths(xs: list[float]) -> list[float]:
    if len(xs) < 2:
        return [0.012] * len(xs)
    widths: list[float] = []
    for i in range(len(xs)):
        if i == 0:
            w = (xs[1] - xs[0]) * 0.65
        elif i == len(xs) - 1:
            w = (xs[i] - xs[i - 1]) * 0.65
        else:
            w = min(xs[i + 1] - xs[i], xs[i] - xs[i - 1]) * 0.65
        widths.append(max(w, 1e-6))
    return widths


def _draw_candles(ax: Any, slice_bars: list[OhlcBar], xs: list[float]) -> None:
    from matplotlib.patches import Rectangle

    widths = _candle_widths(xs)
    for bar, x, bar_w in zip(slice_bars, xs, widths):
        o, h, l, c = bar.open, bar.high, bar.low, bar.close
        color = "#26a69a" if c >= o else "#ef5350"
        ax.plot([x, x], [l, h], color=color, linewidth=0.9, solid_capstyle="round")
        body_h = abs(c - o)
        if body_h < (h - l) * 0.001 and h != l:
            body_h = (h - l) * 0.01
        elif body_h == 0:
            body_h = max(c * 0.00003, 1.0)
        ax.add_patch(
            Rectangle(
                (x - bar_w / 2, min(o, c)),
                bar_w,
                body_h,
                facecolor=color,
                edgecolor=color,
                linewidth=0.6,
            )
        )


def _style_axes(ax: Any, title: str) -> None:
    import matplotlib.dates as mdates

    ax.set_title(title, color="#eceff1", fontsize=10)
    ax.tick_params(colors="#90a4ae", labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    for spine in ax.spines.values():
        spine.set_color("#37474f")
    ax.grid(True, color="#263238", alpha=0.45)


def _mark_signal_and_forward(
    ax: Any,
    xs: list[float],
    slice_bars: list[OhlcBar],
    sig_global: int,
    start: int,
    forward_bars: int,
    outcome_success: bool | None,
) -> None:
    if forward_bars <= 0 or sig_global < start:
        return
    sig_local = sig_global - start
    if sig_local < 0 or sig_local >= len(xs):
        return
    x_sig = xs[sig_local]
    x_end = xs[-1]
    if outcome_success is True:
        fill = "#2ecc7133"
        edge = "#66bb6a"
    elif outcome_success is False:
        fill = "#e74c3c33"
        edge = "#ef5350"
    else:
        fill = "#ffffff12"
        edge = "#78909c"
    ax.axvspan(x_sig, x_end, facecolor=fill, edgecolor="none", zorder=0.5, alpha=0.35)
    ax.axvline(x_sig, color=edge, linewidth=1.2, linestyle=":", alpha=0.9, zorder=4)


def _render_price_pattern(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    signal_index: int | None,
    forward_bars: int,
    outcome_success: bool | None,
) -> bytes | None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    start, end, sig = _slice_range(bars, hit, signal_index, forward_bars)
    slice_bars = bars[start:end]
    if len(slice_bars) < 5:
        return None

    fig, ax = plt.subplots(figsize=(8.5, 4.4), dpi=120, layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(b.ts) for b in slice_bars]
    _draw_candles(ax, slice_bars, xs)

    meta = hit.meta
    if hit.category == "triangle":
        wo = meta.get("window_offset", max(0, len(bars) - 120))
        su, iu = meta["upper_slope"], meta["upper_intercept"]
        sl, il = meta["lower_slope"], meta["lower_intercept"]
        i0, i1 = meta["start_i"], meta["end_i"]
        g0, g1 = wo + i0, wo + i1
        if 0 <= g0 < len(bars) and 0 <= g1 < len(bars):
            x0 = mdates.date2num(bars[g0].ts)
            x1 = mdates.date2num(bars[g1].ts)
            y_u0, y_u1 = su * i0 + iu, su * i1 + iu
            y_l0, y_l1 = sl * i0 + il, sl * i1 + il
            ax.plot([x0, x1], [y_u0, y_u1], color="#ffb74d", linewidth=2, label="مقاومت")
            ax.plot([x0, x1], [y_l0, y_l1], color="#81c784", linewidth=2, label="حمایت")
            if sig is not None:
                j = wo + min(i1, max(i0, sig - wo)) if sig >= wo else i1
                j = min(max(j, i0), i1)
                last_x = mdates.date2num(bars[sig].ts)
                last_y = bars[sig].close
                y_u = su * j + iu
                y_l = sl * j + il
                d = meta.get("kind")
                if d == "ascending":
                    ty = y_u * 1.001
                    ax.annotate(
                        "",
                        xy=(last_x, ty),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=1.8),
                    )
                elif d == "descending":
                    ty = y_l * 0.999
                    ax.annotate(
                        "",
                        xy=(last_x, ty),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#ef5350", lw=1.8),
                    )
                else:
                    mid_y = (y_u + y_l) / 2
                    ax.annotate(
                        "",
                        xy=(last_x, mid_y),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#ff9800", lw=1.8),
                    )

    elif hit.category == "flag":
        ps, pe = meta["pole_start"], meta["pole_end"]
        fh, fl = meta["flag_high"], meta["flag_low"]
        if 0 <= ps < len(bars) and 0 <= pe < len(bars):
            x_p0 = mdates.date2num(bars[ps].ts)
            x_p1 = mdates.date2num(bars[pe].ts)
            ax.plot(
                [x_p0, x_p1],
                [bars[ps].close, bars[pe].close],
                color="#ff9800",
                linewidth=2.5,
                label="Pole",
            )
            x_f_end = xs[-1]
            ax.plot([x_p1, x_f_end], [fh, fh], color="#42a5f5", linewidth=1.5, linestyle="--")
            ax.plot([x_p1, x_f_end], [fl, fl], color="#42a5f5", linewidth=1.5, linestyle="--")
            if sig is not None:
                last_x = mdates.date2num(bars[sig].ts)
                last_y = bars[sig].close
                if meta.get("direction") == "up":
                    ax.annotate(
                        "",
                        xy=(last_x, fh * 1.002),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=1.8),
                    )
                else:
                    ax.annotate(
                        "",
                        xy=(last_x, fl * 0.998),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#ef5350", lw=1.8),
                    )

    if sig is not None:
        _mark_signal_and_forward(ax, xs, slice_bars, sig, start, forward_bars, outcome_success)

    _style_axes(ax, f"BTCUSDT {hit.timeframe} — {hit.title_fa}")
    ax.set_ylabel("USDT", color="#90a4ae", fontsize=8)
    ax.margins(x=0.02)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _render_divergence(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    signal_index: int | None,
    forward_bars: int,
    outcome_success: bool | None,
) -> bytes | None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    meta = hit.meta
    ia, ib = meta["pivot_a"][0], meta["pivot_b"][0]
    sig = signal_index if signal_index is not None else ib
    start = max(0, min(ia, ib, sig) - 25)
    end = min(len(bars), max(ia, ib, sig) + forward_bars + 1)
    slice_bars = bars[start:end]
    if len(slice_bars) < 10:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(8.5, 5.2), dpi=120, height_ratios=[2.2, 1], layout="constrained"
    )
    fig.patch.set_facecolor("#0d1117")
    for ax in (ax1, ax2):
        ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(b.ts) for b in slice_bars]
    _draw_candles(ax1, slice_bars, xs)

    pa, pb = meta["pivot_a"], meta["pivot_b"]
    direction = meta.get("direction")
    x_a = mdates.date2num(bars[pa[0]].ts)
    x_b = mdates.date2num(bars[pb[0]].ts)
    ax1.scatter([x_a, x_b], [pa[1], pb[1]], c="#ff9800", s=55, zorder=6, edgecolors="#fff", linewidths=0.4)
    ax1.plot([x_a, x_b], [pa[1], pb[1]], color="#ff9800", linestyle="--", linewidth=1.2, alpha=0.85)

    rsi_y: list[float] = []
    for i in range(start, end):
        v = rs[i] if i < len(rs) else None
        rsi_y.append(float("nan") if v is None else v)
    ax2.plot(xs, rsi_y, color="#ce93d8", linewidth=1.3)
    ra, rb = meta["rsi_a"], meta["rsi_b"]
    ax2.scatter(
        [x_a, x_b],
        [ra, rb],
        c="#ff9800",
        s=45,
        zorder=5,
        edgecolors="#fff",
        linewidths=0.4,
    )
    ax2.plot([x_a, x_b], [ra, rb], color="#ff9800", linestyle="--", linewidth=1.0, alpha=0.85)
    ax2.axhline(70, color="#455a64", linewidth=0.6, linestyle=":")
    ax2.axhline(30, color="#455a64", linewidth=0.6, linestyle=":")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI(14)", color="#90a4ae", fontsize=8)

    if sig is not None and 0 <= sig < len(bars):
        _mark_signal_and_forward(ax1, xs, slice_bars, sig, start, forward_bars, outcome_success)
        ax2.axvline(mdates.date2num(bars[sig].ts), color="#78909c", linewidth=0.8, linestyle=":")

    _style_axes(ax1, f"BTCUSDT {hit.timeframe} — {hit.title_fa}")
    ax1.set_ylabel("USDT", color="#90a4ae", fontsize=8)
    for ax in (ax1, ax2):
        ax.tick_params(colors="#90a4ae", labelsize=6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
