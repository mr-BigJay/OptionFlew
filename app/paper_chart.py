from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

from app.pattern_store import get_pattern_event_by_key
from optionflow.patterns.chart import DIVERGENCE_BEFORE_PAD, chart_forward_bars, render_pattern_chart
from optionflow.patterns.divergence import detect_rsi_divergence
from optionflow.patterns.ohlc import OhlcBar, load_btcusdt
from optionflow.patterns.trendline import WINDOW
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.paper.chart")

_PATTERN_LIMITS = {"5m": 220, "15m": 220, "1h": 200, "4h": 180, "1d": 120}


def _pick_interval(timeframe: str) -> str:
    tf = (timeframe or "").strip().lower()
    if tf in _PATTERN_LIMITS:
        return tf
    return "15m"


def _pattern_meta(pos: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    if str(pos.get("source_type") or "") != "pattern":
        return None, None, None
    sk = str(pos.get("source_key") or "")
    cat = sk.split(":", 1)[0] if ":" in sk else ""
    if cat not in ("trendline", "channel", "divergence"):
        return cat or None, None, None
    ev = get_pattern_event_by_key(sk)
    if not ev:
        return cat, None, None
    meta = ev.get("meta")
    return cat, meta if isinstance(meta, dict) else None, ev


def _parse_iso_ts(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _nearest_bar_index(bars: list[OhlcBar], ts: datetime) -> int:
    best_i = len(bars) - 1
    best_d = float("inf")
    for i, b in enumerate(bars):
        bt = b.ts
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        d = abs((bt - ts).total_seconds())
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _reanchor_meta(bars: list[OhlcBar], meta: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    """هم‌تراز کردن window_offset و اندیس‌ها با کندل‌های فعلی (زمان ثبت الگو)."""
    ts = _parse_iso_ts(str(ev.get("created_at") or ""))
    if ts is None or not bars:
        return dict(meta)
    idx = _nearest_bar_index(bars, ts)
    m = dict(meta)
    end_i = int(m.get("end_i") or len(bars) - 1)
    old_wo = int(m.get("window_offset") or 0)
    ref = m.get("confirm_index")
    if not isinstance(ref, int):
        ref = m.get("early_index")
    if not isinstance(ref, int):
        ref = old_wo + end_i
    shift = idx - ref
    m["window_offset"] = max(0, old_wo + shift)
    for key in (
        "confirm_index",
        "early_index",
        "entry_index",
        "final_index",
        "break_index",
        "pullback_index",
    ):
        v = m.get(key)
        if isinstance(v, int):
            m[key] = v + shift
    return m


def _pattern_hit_from_event(
    ev: dict[str, Any],
    meta: dict[str, Any],
    *,
    category: str,
    pos: dict[str, Any],
) -> PatternHit:
    return PatternHit(
        category=category,
        timeframe=str(ev.get("timeframe") or pos.get("timeframe") or "1h"),
        pattern_id=str(ev.get("pattern_id") or category),
        title_fa=str(ev.get("title_fa") or pos.get("signal_title") or category),
        status_fa=str(ev.get("status_fa") or ""),
        summary_fa=str(ev.get("summary_fa") or ""),
        forecast_fa=str(ev.get("forecast_fa") or ""),
        meta=meta,
    )


def _divergence_hit(
    bars: list[OhlcBar],
    interval: str,
    ev: dict[str, Any] | None,
    pos: dict[str, Any],
) -> PatternHit | None:
    meta = (ev or {}).get("meta") if ev else None
    if isinstance(meta, dict) and meta.get("pivot_a") and meta.get("pivot_b"):
        ia = int(meta["pivot_a"][0])
        ib = int(meta["pivot_b"][0])
        if 0 <= ia < len(bars) and 0 <= ib < len(bars):
            return PatternHit(
                category="divergence",
                timeframe=str((ev or {}).get("timeframe") or interval),
                pattern_id=str((ev or {}).get("pattern_id") or "rsi_div"),
                title_fa=str((ev or {}).get("title_fa") or pos.get("signal_title") or "واگرایی RSI"),
                status_fa=str((ev or {}).get("status_fa") or ""),
                summary_fa=str((ev or {}).get("summary_fa") or ""),
                forecast_fa=str((ev or {}).get("forecast_fa") or ""),
                meta=meta,
            )
    return detect_rsi_divergence(bars, interval, allow_early=True)


def _paper_hlines(pos: dict[str, Any], mark: float | None) -> list[tuple[float, str, str, str]]:
    entry = float(pos["entry_price"])
    sl = float(pos["sl_price"])
    tp = float(pos["tp_price"])
    lines: list[tuple[float, str, str, str]] = [
        (entry, "#fbbf24", "-", f"Entry {entry:,.0f}"),
        (sl, "#f87171", "--", f"SL {sl:,.0f}"),
        (tp, "#34d399", "--", f"TP {tp:,.0f}"),
    ]
    if mark is not None and mark > 0:
        lines.append((mark, "#60a5fa", ":", f"Mark {mark:,.0f}"))
    return lines


def _load_pattern_bars(interval: str) -> list[OhlcBar]:
    limit = _PATTERN_LIMITS.get(interval, 220)
    win = WINDOW.get(interval, 120)
    return load_btcusdt(interval, limit=max(limit, win + 40))


def render_paper_position_chart(pos: dict[str, Any], *, mark: float | None = None) -> bytes | None:
    """چارت پوزیشن الگو — همان رندر بخش الگوها + خطوط ورود/SL/TP."""
    interval = _pick_interval(str(pos.get("timeframe") or ""))
    category, meta, ev = _pattern_meta(pos)
    if ev and ev.get("timeframe"):
        interval = _pick_interval(str(ev["timeframe"]))

    try:
        bars_all = _load_pattern_bars(interval)
    except Exception as e:
        logger.warning("bars for paper chart: %s", e)
        return None
    if len(bars_all) < 10:
        return None

    hlines = _paper_hlines(pos, mark)

    if category == "divergence" and ev:
        hit = _divergence_hit(bars_all, interval, ev, pos)
        if hit:
            sig = hit.meta.get("confirm_index") or hit.meta["pivot_b"][0]
            half_pad = max(6, DIVERGENCE_BEFORE_PAD // 2)
            png = render_pattern_chart(
                bars_all,
                hit,
                signal_index=int(sig) if sig is not None else None,
                forward_bars=12,
                before_signal_pad=half_pad,
                extra_hlines=hlines,
            )
            if png:
                return png

    if category in ("trendline", "channel") and meta and ev:
        aligned = _reanchor_meta(bars_all, meta, ev)
        hit = _pattern_hit_from_event(ev, aligned, category=category, pos=pos)
        sig = hit.meta.get("confirm_index") or hit.meta.get("early_index")
        if not isinstance(sig, int):
            sig = len(bars_all) - 1
        fwd = chart_forward_bars(bars_all, hit, sig)
        png = render_pattern_chart(
            bars_all,
            hit,
            signal_index=sig,
            forward_bars=fwd,
            extra_hlines=hlines,
        )
        if png:
            return png

    return _render_fallback_chart(pos, mark=mark, interval=interval)


def _render_fallback_chart(
    pos: dict[str, Any],
    *,
    mark: float | None,
    interval: str,
) -> bytes | None:
    """چارت ساده برای گزارش/بدون متای الگو."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None

    try:
        candles = load_btcusdt(interval, limit=120)
    except Exception:
        return None
    if len(candles) < 5:
        return None

    entry = float(pos["entry_price"])
    sl = float(pos["sl_price"])
    tp = float(pos["tp_price"])
    direction = str(pos.get("direction") or "long")
    title = str(pos.get("signal_title") or "پوزیشن")[:60]

    fig, ax = plt.subplots(figsize=(8.5, 4.4), dpi=120, layout="constrained")
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

    for price, color, ls, label in _paper_hlines(pos, mark):
        ax.axhline(price, color=color, linewidth=1.1, linestyle=ls, label=label)

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
