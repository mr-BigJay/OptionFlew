from __future__ import annotations

import io
import logging
from typing import Any

from optionflow.scenario_chart import fetch_btcusdt_klines

logger = logging.getLogger("optionflow.paper.chart")


def _pick_interval(timeframe: str) -> str:
    tf = (timeframe or "").strip().lower()
    if tf in ("5m", "15m", "1h", "4h", "1d"):
        return tf
    return "15m"


def render_paper_position_chart(pos: dict[str, Any], *, mark: float | None = None) -> bytes | None:
    """چارت BTCUSDT با خطوط ورود، SL، TP و مارک."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None

    interval = _pick_interval(str(pos.get("timeframe") or ""))
    try:
        candles = fetch_btcusdt_klines(interval=interval, limit=120)
    except Exception as e:
        logger.warning("klines for paper chart: %s", e)
        return None
    if len(candles) < 5:
        return None

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

    ax.axhline(entry, color="#fbbf24", linewidth=1.2, linestyle="-", label=f"Entry {entry:,.0f}")
    ax.axhline(sl, color="#f87171", linewidth=1.0, linestyle="--", label=f"SL {sl:,.0f}")
    ax.axhline(tp, color="#34d399", linewidth=1.0, linestyle="--", label=f"TP {tp:,.0f}")
    if mark is not None and mark > 0:
        ax.axhline(mark, color="#60a5fa", linewidth=1.0, linestyle=":", label=f"Mark {mark:,.0f}")

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
