from __future__ import annotations

import io
import logging
from typing import Any

from app.pattern_store import get_pattern_event_by_key
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import WINDOW, detect_channel, detect_trendline
from optionflow.scenario_chart import fetch_btcusdt_klines

logger = logging.getLogger("optionflow.paper.chart")


def _pick_interval(timeframe: str) -> str:
    tf = (timeframe or "").strip().lower()
    if tf in ("5m", "15m", "1h", "4h", "1d"):
        return tf
    return "15m"


def _pattern_meta(pos: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    if str(pos.get("source_type") or "") != "pattern":
        return None, None
    sk = str(pos.get("source_key") or "")
    cat = sk.split(":", 1)[0] if ":" in sk else ""
    if cat not in ("trendline", "channel"):
        return cat or None, None
    ev = get_pattern_event_by_key(sk)
    if not ev:
        return cat, None
    meta = ev.get("meta")
    return cat, meta if isinstance(meta, dict) else None


def _klines_to_bars(candles) -> list[OhlcBar]:
    return [
        OhlcBar(c.ts, c.open, c.high, c.low, c.close, 0.0)
        for c in candles
    ]


def _redetect_meta(bars: list[OhlcBar], interval: str, category: str) -> dict[str, Any] | None:
    """ترندلاین روی همان پنجرهٔ کندل فعلی (هم‌تراز با قیمت)."""
    if category == "trendline":
        hit = detect_trendline(bars, interval, allow_early=True)
    elif category == "channel":
        hit = detect_channel(bars, interval, allow_early=True)
    else:
        return None
    if not hit or not hit.meta:
        return None
    return dict(hit.meta)


def _trendline_slice(n: int, meta: dict[str, Any]) -> tuple[int, int]:
    """برش چارت: فقط یک‌سوم کندل‌های قبل از شروع ترندلاین."""
    local_start = int(meta.get("start_i") or 0)
    local_start = max(0, min(local_start, n - 1))
    pad = max(5, local_start // 3)
    chart_start = max(0, local_start - pad)
    return chart_start, n


def _slice_index(chart_start: int, wi: int, slice_len: int) -> int | None:
    if wi < chart_start or wi >= chart_start + slice_len:
        return None
    return wi - chart_start


def _line_at(meta: dict[str, Any], wi: int, *, upper: bool) -> float | None:
    if upper:
        s, ic = meta.get("upper_slope"), meta.get("upper_intercept")
    else:
        s, ic = meta.get("lower_slope"), meta.get("lower_intercept")
    if s is None or ic is None:
        return None
    return float(s) * wi + float(ic)


def _draw_trendline_overlay(
    ax,
    candles,
    xs,
    meta: dict[str, Any],
    *,
    chart_start: int,
    category: str,
) -> None:
    import matplotlib.dates as mdates

    slice_len = len(candles)
    wi_left = chart_start
    wi_right = chart_start + slice_len - 1
    di0, di1 = 0, slice_len - 1
    if slice_len < 2:
        return

    def plot_seg(upper: bool, color: str, label: str) -> None:
        y0 = _line_at(meta, wi_left, upper=upper)
        y1 = _line_at(meta, wi_right, upper=upper)
        if y0 is None or y1 is None:
            return
        ax.plot(
            [xs[di0], xs[di1]],
            [y0, y1],
            color=color,
            linewidth=2.2,
            label=label,
            zorder=5,
        )

    if category == "trendline":
        side = meta.get("side")
        if side == "low":
            plot_seg(False, "#81c784", "ترندلاین حمایت")
        else:
            plot_seg(True, "#ffb74d", "ترندلاین مقاومت")
    else:
        plot_seg(True, "#ffb74d", "مقاومت")
        plot_seg(False, "#81c784", "حمایت")

    touch_c = "#eceff1" if category == "trendline" else None
    for ti in meta.get("touch_highs") or []:
        di = _slice_index(chart_start, int(ti), slice_len)
        if di is not None:
            ax.scatter(
                [mdates.date2num(candles[di].ts)],
                [candles[di].high],
                c=touch_c or "#ffb74d",
                s=40,
                zorder=6,
                edgecolors="#fff",
                linewidths=0.4,
            )
    for ti in meta.get("touch_lows") or []:
        di = _slice_index(chart_start, int(ti), slice_len)
        if di is not None:
            ax.scatter(
                [mdates.date2num(candles[di].ts)],
                [candles[di].low],
                c=touch_c or "#81c784",
                s=40,
                zorder=6,
                edgecolors="#fff",
                linewidths=0.4,
            )


def render_paper_position_chart(pos: dict[str, Any], *, mark: float | None = None) -> bytes | None:
    """چارت BTCUSDT با خطوط ورود، SL، TP، مارک و ترندلاین الگو."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None

    interval = _pick_interval(str(pos.get("timeframe") or ""))
    win_n = WINDOW.get(interval, 120)
    try:
        candles_all = fetch_btcusdt_klines(interval=interval, limit=win_n)
    except Exception as e:
        logger.warning("klines for paper chart: %s", e)
        return None
    if len(candles_all) < 5:
        return None

    category, meta = _pattern_meta(pos)
    bars_all = _klines_to_bars(candles_all)
    draw_meta = meta
    if category in ("trendline", "channel"):
        fresh = _redetect_meta(bars_all, interval, category)
        if fresh:
            draw_meta = fresh
    chart_start = 0
    if draw_meta and category in ("trendline", "channel"):
        chart_start, chart_end = _trendline_slice(len(candles_all), draw_meta)
        candles = candles_all[chart_start:chart_end]
    else:
        candles = candles_all

    if len(candles) < 5:
        candles = candles_all
        chart_start = 0

    entry = float(pos["entry_price"])
    sl = float(pos["sl_price"])
    tp = float(pos["tp_price"])
    direction = str(pos.get("direction") or "long")
    title = str(pos.get("signal_title") or "پوزیشن")[:60]

    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=110, layout="constrained")
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    xs = [mdates.date2num(c.ts) for c in candles]
    bar_w = (xs[1] - xs[0]) * 0.65 if len(xs) > 1 else 0.01
    for c, x in zip(candles, xs):
        color = "#34d399" if c.close >= c.open else "#f87171"
        ax.plot([x, x], [c.low, c.high], color=color, linewidth=0.8, alpha=0.9)
        body_lo = min(c.open, c.close)
        body_hi = max(c.open, c.close)
        ax.add_patch(
            Rectangle(
                (x - bar_w / 2, body_lo),
                bar_w,
                max(body_hi - body_lo, (c.high - c.low) * 0.02),
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
        )

    if draw_meta and category in ("trendline", "channel"):
        _draw_trendline_overlay(
            ax, candles, xs, draw_meta, chart_start=chart_start, category=category
        )

    ax.axhline(entry, color="#fbbf24", linewidth=1.2, linestyle="-", label=f"Entry {entry:,.0f}")
    ax.axhline(sl, color="#f87171", linewidth=1.0, linestyle="--", label=f"SL {sl:,.0f}")
    ax.axhline(tp, color="#34d399", linewidth=1.0, linestyle="--", label=f"TP {tp:,.0f}")
    if mark is not None and mark > 0:
        ax.axhline(mark, color="#60a5fa", linewidth=1.0, linestyle=":", label=f"Mark {mark:,.0f}")

    y_vals: list[float] = [entry, sl, tp]
    if mark is not None and mark > 0:
        y_vals.append(mark)
    for c in candles:
        y_vals.extend([c.high, c.low])
    if draw_meta and category in ("trendline", "channel"):
        for wi in range(chart_start, chart_start + len(candles)):
            for upper in (True, False):
                y = _line_at(draw_meta, wi, upper=upper)
                if y is not None:
                    y_vals.append(y)
    lo, hi = min(y_vals), max(y_vals)
    span = max(hi - lo, hi * 0.001, 1.0)
    pad = span * 0.08
    ax.set_ylim(lo - pad, hi + pad)

    side = "Long" if direction == "long" else "Short"
    ax.set_title(f"{title} · {side} · {interval}", color="#e2e8f0", fontsize=10)
    ax.tick_params(colors="#94a3b8", labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.grid(True, alpha=0.12, color="#64748b")
    ax.legend(loc="upper left", fontsize=7, facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
