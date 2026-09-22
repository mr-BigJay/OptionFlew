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
CHART_AFTER_RATIO = 3
DIVERGENCE_BEFORE_PAD = 24
HLine = tuple[float, str, str, str]  # price, color, linestyle, label


def chart_window_end(n: int, sig: int, start: int, *, tail_pad: int = 0) -> int:
    """کندل‌های بعد از سیگنال = CHART_AFTER_RATIO × قبل از سیگنال."""
    before = max(1, sig - start)
    return min(n, sig + CHART_AFTER_RATIO * before + 1 + tail_pad)


def render_pattern_chart(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    signal_index: int | None = None,
    forward_bars: int | None = None,
    outcome_success: bool | None = None,
    before_signal_pad: int | None = None,
    extra_hlines: list[HLine] | None = None,
) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
    except ImportError:
        return None

    if not bars:
        return None

    fwd = forward_bars
    sig = signal_index
    if sig is None and hit.meta.get("confirm_index") is not None:
        sig = hit.meta.get("confirm_index")
    if fwd is None and sig is not None:
        start, end, _ = _slice_range(bars, hit, sig, forward_bars=0)
        fwd = max(6, end - 1 - sig)
    if fwd is None and signal_index is not None:
        fwd = FORWARD_BARS_DEFAULT.get(hit.timeframe, 18)

    if hit.category == "divergence":
        pad = (
            before_signal_pad
            if before_signal_pad is not None
            else DIVERGENCE_BEFORE_PAD
        )
        return _render_divergence(
            bars,
            hit,
            signal_index=signal_index,
            forward_bars=fwd or 0,
            outcome_success=outcome_success,
            before_signal_pad=pad,
            extra_hlines=extra_hlines,
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

    if hit.category in ("triangle", "trendline", "channel"):
        wo = meta.get("window_offset", max(0, n - 120))
        i0 = wo + meta.get("start_i", 0)
        i1 = wo + meta.get("end_i", sig)
        early = meta.get("early_index")
        extra0 = early if isinstance(early, int) else i0
        start = max(0, min(i0, extra0, sig) - 8)
        exit_i = meta.get("exit_index") if hit.category == "trendline" else None
        if hit.category == "trendline":
            end = chart_window_end(n, sig, start, tail_pad=8)
            if isinstance(exit_i, int) and start <= exit_i < n:
                end = min(n, max(end, min(exit_i + 8, sig + 96)))
        elif isinstance(exit_i, int):
            end = min(n, max(chart_window_end(n, sig, start), exit_i + 8))
        else:
            end = chart_window_end(n, sig, start)
    elif hit.category == "flag":
        ps = meta.get("pole_start", max(0, sig - 30))
        start = max(0, ps - 8)
        end = chart_window_end(n, sig, start)
    elif hit.category == "ema50":
        from optionflow.patterns.ema50 import ema50_slice

        pb = meta.get("pullback_index", sig)
        early = meta.get("early_index", pb)
        start, end = ema50_slice(n, sig, int(pb), int(early))
    elif hit.category == "meaningful_behavior":
        entry = meta.get("entry_index", sig)
        if not isinstance(entry, int):
            entry = sig
        exit_i = meta.get("exit_index")
        start = max(0, entry - 48)
        if isinstance(exit_i, int):
            end = min(n, max(chart_window_end(n, entry, start), exit_i + 8))
        else:
            end = chart_window_end(n, entry, start)
    else:
        start = max(0, sig - 60)
        end = chart_window_end(n, sig, start)

    return start, end, sig


def chart_forward_bars(
    bars: list[OhlcBar], hit: PatternHit, sig_ix: int
) -> int:
    start, end, _ = _slice_range(bars, hit, sig_ix, forward_bars=0)
    return max(6, end - 1 - sig_ix)


def _visible_price_range(
    bars: list[OhlcBar],
    hit: PatternHit,
    start: int,
    end: int,
) -> tuple[float, float]:
    """محدودهٔ قیمت برای محور Y — فقط کندل‌ها + خط ساختار (مثل مثلث)، نه نقاط پرت."""
    slice_bars = bars[start:end]
    if not slice_bars:
        return 0.0, 1.0
    lo = min(b.low for b in slice_bars)
    hi = max(b.high for b in slice_bars)
    meta = hit.meta
    if hit.category in ("triangle", "trendline", "channel"):
        wo = int(meta.get("window_offset") or 0)
        i0 = int(meta.get("start_i", 0))
        i1 = int(meta.get("end_i", i0))
        g0, g1 = wo + i0, wo + i1
        if g1 >= start and g0 < end:
            li0 = max(i0, start - wo)
            li1 = min(i1, end - 1 - wo)
            if li1 >= li0:
                for sl, ic in (
                    (meta.get("upper_slope"), meta.get("upper_intercept")),
                    (meta.get("lower_slope"), meta.get("lower_intercept")),
                ):
                    if sl is None or ic is None:
                        continue
                    y0 = float(sl) * li0 + float(ic)
                    y1 = float(sl) * li1 + float(ic)
                    lo = min(lo, y0, y1)
                    hi = max(hi, y0, y1)
        for ti in (meta.get("touch_highs") or []) + (meta.get("touch_lows") or []):
            gi = wo + int(ti)
            if start <= gi < end:
                lo = min(lo, bars[gi].low)
                hi = max(hi, bars[gi].high)
    tp_px = meta.get("tp_px")
    if isinstance(tp_px, (int, float)):
        px = float(tp_px)
        lo = min(lo, px)
        hi = max(hi, px)
    entry_px = meta.get("entry_blended_px") or meta.get("entry_px")
    if isinstance(entry_px, (int, float)):
        px = float(entry_px)
        lo = min(lo, px)
        hi = max(hi, px)
    if hit.category == "meaningful_behavior":
        for item in (hit.meta or {}).get("dominant_strikes") or []:
            if isinstance(item, (list, tuple)) and item:
                try:
                    s = float(item[0])
                    lo = min(lo, s)
                    hi = max(hi, s)
                except (TypeError, ValueError):
                    pass
    return lo, hi


def _apply_price_ylim(
    ax: Any,
    bars: list[OhlcBar],
    hit: PatternHit,
    start: int,
    end: int,
    *,
    extra_top_frac: float = 0.0,
) -> None:
    lo, hi = _visible_price_range(bars, hit, start, end)
    span = hi - lo
    if span <= 0:
        span = max(abs(hi) * 0.002, 1.0)
    pad = span * 0.10
    top = hi + pad + span * extra_top_frac
    ax.set_ylim(lo - pad, top)


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


def _mark_trendline_path(
    ax: Any,
    xs: list[float],
    start: int,
    meta: dict[str, Any],
    outcome_success: bool | None,
) -> None:
    """سایه از ورود تا خروج (۰.۵٪ سود یا شکست معتبر) + درصد مسیر."""
    entry_i = meta.get("entry_index", meta.get("early_index"))
    exit_i = meta.get("exit_index")
    pct = meta.get("path_pct")
    if not isinstance(entry_i, int) or not isinstance(exit_i, int):
        return
    if entry_i < start or exit_i < start:
        return
    e_local = entry_i - start
    x_local = exit_i - start
    if e_local < 0 or e_local >= len(xs) or x_local < 0 or x_local >= len(xs):
        return
    x0, x1 = xs[e_local], xs[x_local]
    if x1 < x0:
        x0, x1 = x1, x0
    if outcome_success is True:
        fill, edge = "#2ecc7133", "#66bb6a"
    elif outcome_success is False:
        fill, edge = "#e74c3c33", "#ef5350"
    else:
        fill, edge = "#ffffff12", "#78909c"
    ax.axvspan(x0, x1, facecolor=fill, edgecolor="none", zorder=0.5, alpha=0.35)
    ax.axvline(x1, color=edge, linewidth=1.1, linestyle=":", alpha=0.85, zorder=4)
    if not isinstance(pct, (int, float)):
        return
    ax.text(
        (x0 + x1) / 2,
        1.02,
        f"{pct * 100:+.1f}%",
        color=edge,
        fontsize=9,
        ha="center",
        va="bottom",
        zorder=12,
        fontweight="bold",
        transform=ax.get_xaxis_transform(),
        bbox={
            "boxstyle": "round,pad=0.18",
            "facecolor": "#0d1117cc",
            "edgecolor": edge,
            "linewidth": 0.7,
        },
    )


def _mark_index_arrow(
    ax: Any,
    bars: list[OhlcBar],
    index: int,
    start: int,
    end: int,
    *,
    side: str | None,
    color: str,
) -> None:
    if index < start or index >= min(end, len(bars)):
        return
    import matplotlib.dates as mdates

    bar = bars[index]
    x = mdates.date2num(bar.ts)
    window = bars[start:end]
    span = max(b.high for b in window) - min(b.low for b in window)
    pad = max(span * 0.012, bar.high * 0.0004)
    if side == "low":
        y_tip, y_head = bar.low - pad, bar.low - pad * 2.4
    elif side == "high":
        y_tip, y_head = bar.high + pad, bar.high + pad * 2.4
    else:
        y_tip, y_head = bar.close + pad, bar.close + pad * 2.4
    ax.annotate(
        "",
        xy=(x, y_tip),
        xytext=(x, y_head),
        arrowprops=dict(
            arrowstyle="-|>", color=color, lw=1.6, mutation_scale=12
        ),
        zorder=9,
    )


def _mark_behavior_scenario(
    ax: Any,
    bars: list[OhlcBar],
    meta: dict[str, Any],
    start: int,
    end: int,
    xs: list[float],
) -> None:
    """مسیر پیش‌بینی spot + strikeهای فلو (هدف و پوشش)."""
    import matplotlib.dates as mdates

    entry_i = meta.get("entry_index")
    tp = meta.get("tp_px")
    direction = meta.get("direction")
    strikes: list[float] = []
    for item in meta.get("dominant_strikes") or []:
        if isinstance(item, (list, tuple)) and item:
            try:
                strikes.append(float(item[0]))
            except (TypeError, ValueError):
                continue

    up = direction == "up"
    down = direction == "down"
    target_col = "#66bb6a" if up else "#ef5350" if down else "#90caf9"

    for s in strikes:
        is_tp = isinstance(tp, (int, float)) and abs(float(tp) - s) < 1.0
        col = target_col if is_tp else "#78909c"
        ax.hlines(
            s,
            xs[0],
            xs[-1],
            colors=col,
            linestyles="--" if is_tp else ":",
            linewidth=1.3 if is_tp else 0.85,
            alpha=0.9 if is_tp else 0.45,
            zorder=4,
        )
        ax.text(
            xs[-1],
            s,
            f" {int(round(s)):,}",
            color=col,
            fontsize=7,
            va="center",
            ha="left",
            clip_on=False,
        )

    if not isinstance(entry_i, int) or entry_i < start or entry_i >= min(end, len(bars)):
        return
    if not isinstance(tp, (int, float)):
        return

    x0 = mdates.date2num(bars[entry_i].ts)
    y0 = float(bars[entry_i].close)
    x1 = xs[-1]
    y1 = float(tp)
    ax.plot(
        [x0, x1],
        [y0, y1],
        color=target_col,
        linewidth=2.4,
        linestyle="-",
        alpha=0.82,
        zorder=7,
        solid_capstyle="round",
    )
    ax.scatter(
        [x0],
        [y0],
        c="#fbbf24",
        s=72,
        zorder=9,
        edgecolors="#fff",
        linewidths=0.5,
        label="ورود",
    )
    ax.scatter(
        [x1],
        [y1],
        marker="v" if down else "^" if up else "o",
        c=target_col,
        s=95,
        zorder=10,
        edgecolors="#fff",
        linewidths=0.55,
    )
    arrow = "↓" if down else "↑" if up else "→"
    ax.text(
        (x0 + x1) / 2,
        (y0 + y1) / 2,
        f"مسیر spot {arrow}",
        color=target_col,
        fontsize=8,
        ha="center",
        va="center",
        zorder=11,
        bbox={
            "boxstyle": "round,pad=0.25",
            "facecolor": "#0d1117dd",
            "edgecolor": target_col,
            "linewidth": 0.8,
        },
    )


def _mark_early_entry(
    ax: Any,
    bars: list[OhlcBar],
    meta: dict[str, Any],
    start: int,
    end: int,
    *,
    color: str | None = None,
) -> None:
    """فلش تأیید اولیه؛ برای ترندلاین/کانال همرنگ نقطهٔ برخورد."""
    early_ix = meta.get("early_index")
    if not isinstance(early_ix, int) or early_ix < start or early_ix >= min(end, len(bars)):
        return
    import matplotlib.dates as mdates

    bar = bars[early_ix]
    x = mdates.date2num(bar.ts)
    window = bars[start:end]
    span = max(b.high for b in window) - min(b.low for b in window)
    pad = max(span * 0.012, bar.high * 0.0004)
    side = meta.get("early_side") or meta.get("side")
    if color is None:
        if side == "low":
            color = "#81c784"
        elif side == "high":
            color = "#ffb74d"
        else:
            color = "#fbbf24"
    if side == "low":
        y_tip = bar.low - pad
        y_head = bar.low - pad * 2.4
    else:
        y_tip = bar.high + pad
        y_head = bar.high + pad * 2.4
    ax.annotate(
        "",
        xy=(x, y_tip),
        xytext=(x, y_head),
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=1.6,
            mutation_scale=12,
        ),
        zorder=9,
    )
    ax.scatter(
        [x],
        [y_head],
        s=42,
        c=color,
        zorder=10,
        edgecolors="#fff8e1",
        linewidths=0.5,
    )


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
            for ti in meta.get("touch_highs") or []:
                gi = wo + int(ti)
                if 0 <= gi < len(bars):
                    ax.scatter(
                        [mdates.date2num(bars[gi].ts)],
                        [bars[gi].high],
                        c="#ffb74d",
                        s=36,
                        zorder=6,
                        edgecolors="#fff",
                        linewidths=0.4,
                    )
            for ti in meta.get("touch_lows") or []:
                gi = wo + int(ti)
                if 0 <= gi < len(bars):
                    ax.scatter(
                        [mdates.date2num(bars[gi].ts)],
                        [bars[gi].low],
                        c="#81c784",
                        s=36,
                        zorder=6,
                        edgecolors="#fff",
                        linewidths=0.4,
                    )
            if sig is not None:
                j = wo + min(i1, max(i0, sig - wo)) if sig >= wo else i1
                j = min(max(j, i0), i1)
                last_x = mdates.date2num(bars[sig].ts)
                last_y = bars[sig].close
                y_u = su * j + iu
                y_l = sl * j + il
                d = meta.get("direction") or (
                    "up"
                    if meta.get("kind") == "ascending"
                    else "down"
                    if meta.get("kind") == "descending"
                    else None
                )
                if d == "up":
                    ty = y_u * 1.001
                    ax.annotate(
                        "",
                        xy=(last_x, ty),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#66bb6a", lw=1.8),
                    )
                elif d == "down":
                    ty = y_l * 0.999
                    ax.annotate(
                        "",
                        xy=(last_x, ty),
                        xytext=(last_x, last_y),
                        arrowprops=dict(arrowstyle="->", color="#ef5350", lw=1.8),
                    )

    elif hit.category in ("trendline", "channel"):
        wo = meta.get("window_offset", max(0, len(bars) - 120))
        i0, i1 = meta["start_i"], meta["end_i"]
        g0, g1 = wo + i0, wo + i1
        g0 = max(start, min(g0, end - 1))
        g1 = max(start, min(g1, end - 1))
        if g1 >= g0 and 0 <= g0 < len(bars) and 0 <= g1 < len(bars):
            x0 = mdates.date2num(bars[g0].ts)
            x1 = mdates.date2num(bars[g1].ts)
            li0, li1 = g0 - wo, g1 - wo
            su, iu = meta.get("upper_slope"), meta.get("upper_intercept")
            sl, il = meta.get("lower_slope"), meta.get("lower_intercept")
            if su is not None and iu is not None:
                ax.plot(
                    [x0, x1],
                    [su * li0 + iu, su * li1 + iu],
                    color="#ffb74d",
                    linewidth=2,
                    label="مقاومت",
                )
            if sl is not None and il is not None:
                ax.plot(
                    [x0, x1],
                    [sl * li0 + il, sl * li1 + il],
                    color="#81c784",
                    linewidth=2,
                    label="حمایت",
                )
            touch_c = "#eceff1" if hit.category == "trendline" else None
            for ti in meta.get("touch_highs") or []:
                gi = wo + int(ti)
                if start <= gi < end:
                    ax.scatter(
                        [mdates.date2num(bars[gi].ts)],
                        [bars[gi].high],
                        c=touch_c or "#ffb74d",
                        s=36,
                        zorder=6,
                        edgecolors="#fff",
                        linewidths=0.4,
                    )
            for ti in meta.get("touch_lows") or []:
                gi = wo + int(ti)
                if start <= gi < end:
                    ax.scatter(
                        [mdates.date2num(bars[gi].ts)],
                        [bars[gi].low],
                        c=touch_c or "#81c784",
                        s=36,
                        zorder=6,
                        edgecolors="#fff",
                        linewidths=0.4,
                    )
        _mark_early_entry(
            ax, bars, meta, start, end, color="#fbbf24" if hit.category == "trendline" else None
        )
        if hit.category == "trendline":
            cf = meta.get("confirm_index")
            side = meta.get("side")
            if isinstance(cf, int):
                _mark_index_arrow(
                    ax, bars, cf, start, end, side=side, color="#42a5f5"
                )
        if hit.category == "trendline" and isinstance(meta.get("exit_index"), int):
            _mark_trendline_path(ax, xs, start, meta, outcome_success)
            exit_i = meta.get("exit_index")
            tp_px = meta.get("tp_px")
            if isinstance(exit_i, int) and start <= exit_i < min(end, len(bars)):
                import matplotlib.dates as mdates

                x_ex = mdates.date2num(bars[exit_i].ts)
                y_ex = tp_px if isinstance(tp_px, (int, float)) else bars[exit_i].close
                ax.scatter(
                    [x_ex],
                    [y_ex],
                    marker="^" if meta.get("side") == "low" else "v",
                    c="#66bb6a",
                    s=70,
                    zorder=11,
                    edgecolors="#fff",
                    linewidths=0.5,
                )

    elif hit.category == "ema50":
        from optionflow.patterns.indicators import ema as ema_fn

        closes = [b.close for b in bars]
        ema_vals = ema_fn(closes, 50)
        ys = [
            ema_vals[i] if ema_vals[i] is not None else float("nan")
            for i in range(start, end)
        ]
        ax.plot(xs, ys, color="#42a5f5", linewidth=1.7, label="EMA50", zorder=3)
        pb = meta.get("pullback_index")
        cf = meta.get("confirm_index")
        if isinstance(pb, int) and start <= pb < end:
            ax.scatter(
                [mdates.date2num(bars[pb].ts)],
                [bars[pb].low if meta.get("direction") == "up" else bars[pb].high],
                c="#81c784" if meta.get("direction") == "up" else "#ffb74d",
                s=40,
                zorder=6,
                edgecolors="#fff",
                linewidths=0.4,
            )
        sl = meta.get("sl_px")
        entry = meta.get("entry_px")
        x_left = xs[0]
        x_right = xs[-1]
        if isinstance(cf, int) and start <= cf < min(end, len(bars)):
            x_left = mdates.date2num(bars[cf].ts)
        if isinstance(entry, (int, float)):
            ax.hlines(
                entry,
                x_left,
                x_right,
                colors="#90caf9",
                linestyles="--",
                linewidth=1.0,
                alpha=0.85,
            )
        if isinstance(sl, (int, float)):
            ax.hlines(
                sl,
                x_left,
                x_right,
                colors="#ef5350",
                linestyles="--",
                linewidth=1.0,
                alpha=0.75,
            )
        _mark_early_entry(ax, bars, meta, start, end)
        if isinstance(meta.get("exit_index"), int):
            _mark_trendline_path(ax, xs, start, meta, outcome_success)

    elif hit.category == "scalp":
        import matplotlib.dates as mdates

        entry_px = meta.get("entry_px")
        stop_px = meta.get("stop_px")
        tp_px = meta.get("tp_px")
        ei = meta.get("entry_index", sig)
        if isinstance(ei, int) and start <= ei < min(end, len(bars)):
            x_e = mdates.date2num(bars[ei].ts)
            ax.scatter(
                [x_e],
                [bars[ei].close],
                c="#fbbf24",
                s=55,
                zorder=8,
                edgecolors="#fff",
                linewidths=0.5,
                label="ورود",
            )
        x0, x1 = xs[0], xs[-1]
        if isinstance(entry_px, (int, float)):
            ax.hlines(
                float(entry_px),
                x0,
                x1,
                colors="#90caf9",
                linestyles="--",
                linewidth=1.0,
                alpha=0.9,
                label="ورود",
            )
        if isinstance(stop_px, (int, float)):
            ax.hlines(
                float(stop_px),
                x0,
                x1,
                colors="#ef5350",
                linestyles="--",
                linewidth=1.0,
                alpha=0.85,
                label="استاپ",
            )
        if isinstance(tp_px, (int, float)):
            ax.hlines(
                float(tp_px),
                x0,
                x1,
                colors="#66bb6a",
                linestyles="--",
                linewidth=1.1,
                alpha=0.85,
                label="TP",
            )
        if isinstance(meta.get("exit_index"), int):
            _mark_trendline_path(ax, xs, start, meta, outcome_success)

    elif hit.category == "meaningful_behavior":
        _mark_behavior_scenario(ax, bars, meta, start, end, xs)
        if isinstance(meta.get("exit_index"), int):
            _mark_trendline_path(ax, xs, start, meta, outcome_success)

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

    path_drawn = hit.category in (
        "trendline",
        "ema50",
        "meaningful_behavior",
        "scalp",
    ) and isinstance(hit.meta.get("exit_index"), int)
    if sig is not None and not path_drawn:
        _mark_signal_and_forward(ax, xs, slice_bars, sig, start, forward_bars, outcome_success)

    _style_axes(ax, f"BTCUSDT {hit.timeframe} — {hit.title_fa}")
    ax.set_ylabel("USDT", color="#90a4ae", fontsize=8)
    ax.margins(x=0.02)
    extra_top = 0.08 if isinstance(hit.meta.get("path_pct"), (int, float)) else 0.0
    _apply_price_ylim(ax, bars, hit, start, end, extra_top_frac=extra_top)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _style_rsi_pane(ax: Any, xs: list[float], rsi_y: list[float], *, period: int = 14) -> None:
    """ظاهر نزدیک RSI پیش‌فرض TradingView."""
    ax.set_facecolor("#0d1117")
    ax.axhspan(30, 70, facecolor=(126 / 255, 87 / 255, 194 / 255, 0.35), zorder=0)
    ax.axhline(70, color="#787B86", linewidth=0.8, zorder=1)
    ax.axhline(50, color=(120 / 255, 123 / 255, 134 / 255, 0.5), linewidth=0.6, zorder=1)
    ax.axhline(30, color="#787B86", linewidth=0.8, zorder=1)
    ax.set_ylim(0, 100)
    ax.set_yticks([30, 50, 70])
    if len(xs) == len(rsi_y) and xs:
        import numpy as np

        y = np.array(rsi_y, dtype=float)
        x = np.array(xs, dtype=float)
        mid = 50.0
        over = np.ma.masked_where(y <= 70, y)
        under = np.ma.masked_where(y >= 30, y)
        ax.fill_between(x, mid, over, where=y > 70, color=(0, 1, 0, 0.12), interpolate=True, zorder=2)
        ax.fill_between(x, under, mid, where=y < 30, color=(1, 0, 0, 0.12), interpolate=True, zorder=2)
    ax.plot(xs, rsi_y, color="#7E57C2", linewidth=1.6, zorder=3, label="RSI")
    ax.set_ylabel(f"RSI({period})", color="#787B86", fontsize=8)


def _render_divergence(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    signal_index: int | None,
    forward_bars: int,
    outcome_success: bool | None,
    before_signal_pad: int = DIVERGENCE_BEFORE_PAD,
    extra_hlines: list[HLine] | None = None,
) -> bytes | None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    meta = hit.meta
    ia, ib = meta["pivot_a"][0], meta["pivot_b"][0]
    early_ix = meta.get("early_index")
    final_ix = meta.get("final_index")
    sig = signal_index if signal_index is not None else meta.get("confirm_index", ib)
    idxs = [ia, ib, sig]
    if isinstance(early_ix, int):
        idxs.append(early_ix)
    if isinstance(final_ix, int):
        idxs.append(final_ix)
    sig_ix = sig if isinstance(sig, int) else ib
    start = max(0, min(idxs) - before_signal_pad)
    end = chart_window_end(len(bars), sig_ix, start)
    slice_bars = bars[start:end]
    if len(slice_bars) < 10:
        return None

    from optionflow.patterns.divergence import RSI_PERIOD

    closes = [b.close for b in bars]
    rs = rsi(closes, RSI_PERIOD)

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
    line_color = "#ef5350" if direction == "down" else "#66bb6a"
    price_pts_x = [x_a, x_b]
    price_pts_y = [pa[1], pb[1]]
    rsi_pts_y = [meta["rsi_a"], meta["rsi_b"]]
    mid = meta.get("pivot_mid")
    if isinstance(mid, (list, tuple)) and len(mid) == 2:
        xm = mdates.date2num(bars[mid[0]].ts)
        price_pts_x.insert(1, xm)
        price_pts_y.insert(1, mid[1])
        rm = rs[mid[0]] if mid[0] < len(rs) and rs[mid[0]] is not None else float("nan")
        rsi_pts_y.insert(1, float(rm))
    if direction == "down":
        ax1.scatter(price_pts_x, price_pts_y, c="#ef5350", s=55, zorder=6, edgecolors="#fff", linewidths=0.4)
        ax1.plot([x_a, x_b], [pa[1], pb[1]], color="#ef5350", linestyle="--", linewidth=1.2, alpha=0.9)
    else:
        ax1.scatter(price_pts_x, price_pts_y, c="#66bb6a", s=55, zorder=6, edgecolors="#fff", linewidths=0.4)
        ax1.plot([x_a, x_b], [pa[1], pb[1]], color="#66bb6a", linestyle="--", linewidth=1.2, alpha=0.9)

    rsi_y: list[float] = []
    for i in range(start, end):
        v = rs[i] if i < len(rs) else None
        rsi_y.append(float("nan") if v is None else float(v))
    _style_rsi_pane(ax2, xs, rsi_y, period=RSI_PERIOD)
    ax2.scatter(
        [x_a, x_b],
        [meta["rsi_a"], meta["rsi_b"]],
        c=line_color,
        s=48,
        zorder=6,
        edgecolors="#fff",
        linewidths=0.4,
    )
    if isinstance(mid, (list, tuple)) and len(mid) == 2:
        ax2.scatter(
            [price_pts_x[1]],
            [rsi_pts_y[1]],
            c="#fbbf24",
            s=40,
            zorder=6,
            edgecolors="#fff",
            linewidths=0.4,
        )
    ax2.plot([x_a, x_b], [meta["rsi_a"], meta["rsi_b"]], color=line_color, linestyle="--", linewidth=1.2, alpha=0.9)

    _mark_early_entry(ax1, bars, meta, start, end)

    if extra_hlines:
        for price, color, ls, label in extra_hlines:
            ax1.axhline(price, color=color, linewidth=1.1, linestyle=ls, label=label)

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
