from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from optionflow.patterns.dedupe import backtest_dedupe_key
from optionflow.patterns.chart import render_pattern_chart, chart_forward_bars
from optionflow.patterns.divergence import (
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    RANGE_UPPER,
    RSI_PERIOD,
    detect_rsi_divergence,
)
from optionflow.patterns.flag import detect_flag
from optionflow.patterns.history import (
    INTERVAL_MS,
    load_cached_bars,
    history_data_dir,
    slice_with_warmup,
)
from optionflow.patterns.indicators import rsi
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import (
    detect_channel,
    detect_trendline,
    evaluate_trendline_path,
)
from optionflow.patterns.ema50 import detect_ema50, evaluate_ema50_path
from optionflow.patterns.three_rp import detect_three_rp_at
from optionflow.patterns.triangle import detect_triangle
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.backtest")

CATEGORIES = (
    "triangle",
    "flag",
    "divergence",
    "trendline",
    "channel",
    "ema50",
    "three_rp",
)
STRIDE_BY_TF = {"1m": 30, "5m": 6, "15m": 2, "1h": 1, "4h": 1, "1d": 1}
STRIDE_HEAVY = {"1m": 60, "5m": 12, "15m": 4, "1h": 2, "4h": 1, "1d": 1}
HEAVY_STRIDE_CATEGORIES = frozenset({"divergence", "trendline", "channel", "ema50"})
DEDUPE_BARS = {"1m": 120, "5m": 48, "15m": 20, "1h": 24, "4h": 8, "1d": 4}
DEDUPE_BARS_HEAVY = {"1m": 240, "5m": 96, "15m": 48, "1h": 36, "4h": 16, "1d": 8}
FORWARD_BARS = {"1m": 60, "5m": 36, "15m": 24, "1h": 18, "4h": 12, "1d": 8}
MIN_MOVE_PCT = {"1m": 0.006, "5m": 0.008, "15m": 0.012, "1h": 0.015, "4h": 0.02, "1d": 0.025}
BACKTEST_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")

ProgressFn = Callable[[int, int], None]
CancelFn = Callable[[], bool]


class BacktestCancelled(Exception):
    """کاربر یا سیستم بکتست را متوقف کرد."""


def _check_cancel(should_cancel: CancelFn | None) -> None:
    if should_cancel and should_cancel():
        raise BacktestCancelled()


@dataclass
class BacktestFinding:
    category: str
    pattern_id: str
    timeframe: str
    detected_at: str
    title_fa: str
    status_fa: str
    summary_fa: str
    forecast_fa: str
    bar_index: int
    chart_file: str = ""
    success: bool | None = None
    outcome_fa: str = ""

    @staticmethod
    def from_hit(
        hit: PatternHit,
        bar_index: int,
        ts: datetime,
        *,
        success: bool | None,
        outcome_fa: str,
    ) -> BacktestFinding:
        return BacktestFinding(
            category=hit.category,
            pattern_id=hit.pattern_id,
            timeframe=hit.timeframe,
            detected_at=ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            title_fa=hit.title_fa,
            status_fa=hit.status_fa,
            summary_fa=hit.summary_fa,
            forecast_fa=hit.forecast_fa,
            bar_index=bar_index,
            success=success,
            outcome_fa=outcome_fa,
        )


@dataclass
class BacktestResult:
    category: str
    timeframe: str
    from_iso: str
    to_iso: str
    bars_total: int
    bars_scanned: int
    stride: int
    findings: list[BacktestFinding] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    error: str = ""
    target_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    entry_on_early: bool = False

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "timeframe": self.timeframe,
            "from_iso": self.from_iso,
            "to_iso": self.to_iso,
            "bars_total": self.bars_total,
            "bars_scanned": self.bars_scanned,
            "stride": self.stride,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "findings": [asdict(f) for f in self.findings],
            "error": self.error,
            "target_profit_pct": self.target_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "entry_on_early": self.entry_on_early,
        }


def _detector(category: str):
    return {
        "triangle": lambda bars, tf: detect_triangle(
            bars, tf, require_breakout=True
        ),
        "flag": detect_flag,
        "divergence": lambda bars, tf: detect_rsi_divergence(
            bars, tf, allow_early=False
        ),
        "trendline": lambda bars, tf: detect_trendline(
            bars, tf, allow_early=False
        ),
        "channel": lambda bars, tf: detect_channel(
            bars, tf, allow_early=False
        ),
        "ema50": lambda bars, tf: detect_ema50(
            bars, tf, allow_early=False
        ),
    }[category]


def expected_direction(hit: PatternHit) -> str | None:
    if hit.category == "divergence":
        return hit.meta.get("direction")
    if hit.category == "flag":
        return hit.meta.get("direction")
    if hit.category == "triangle":
        explicit = hit.meta.get("direction")
        if explicit in ("up", "down"):
            return explicit
        return None
    if hit.category in ("trendline", "channel", "ema50", "three_rp"):
        explicit = hit.meta.get("direction")
        if explicit in ("up", "down"):
            return explicit
        return None
    return None


def divergence_entry_index(
    hit: PatternHit,
    fallback: int | None = None,
    *,
    entry_on_early: bool = False,
) -> int | None:
    """ورود واگرایی: final_index (پیش‌فرض) یا early_index با entry_on_early."""
    meta = hit.meta
    if entry_on_early:
        ei = meta.get("early_index")
        if isinstance(ei, int):
            return ei
    if meta.get("stage") == "confirmed":
        fi = meta.get("final_index")
        if isinstance(fi, int):
            return fi
    for key in ("early_index", "confirm_index"):
        v = meta.get(key)
        if isinstance(v, int):
            return v
    return fallback


def entry_price_for_hit(
    bars: list[OhlcBar], idx: int, hit: PatternHit
) -> float | None:
    meta = hit.meta
    blended = meta.get("entry_blended_px")
    if hit.category == "divergence":
        if isinstance(blended, (int, float)) and blended > 0:
            return float(blended)
        ei = divergence_entry_index(
            hit,
            fallback=idx,
            entry_on_early=bool(meta.get("_backtest_entry_on_early")),
        )
        if ei is not None and 0 <= ei < len(bars):
            return float(bars[ei].close)
    if isinstance(blended, (int, float)) and blended > 0:
        return float(blended)
    if hit.category == "ema50":
        ep = meta.get("entry_px")
        if isinstance(ep, (int, float)) and ep > 0:
            return float(ep)
    if hit.category == "trendline":
        ei = meta.get("entry_index", meta.get("early_index"))
        if isinstance(ei, int) and 0 <= ei < len(bars):
            return float(bars[ei].close)
    if hit.category == "three_rp":
        ep = meta.get("entry_px")
        if isinstance(ep, (int, float)) and ep > 0:
            return float(ep)
    if 0 <= idx < len(bars):
        return float(bars[idx].close)
    return None


def _stop_loss_px(entry_px: float, direction: str, stop_pct: float) -> float:
    move = stop_pct / 100.0
    if direction == "up":
        return entry_px * (1 - move)
    return entry_px * (1 + move)


def evaluate_divergence_target_profit(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    target_pct: float,
    *,
    timeframe: str,
    stop_loss_pct: float | None = None,
    entry_on_early: bool = False,
) -> tuple[bool | None, str]:
    """هدف سود در پنجرهٔ محدود؛ شکست کف/سقف واگرایی (pivot B) = رد."""
    direction = expected_direction(hit)
    if direction not in ("up", "down"):
        return None, "جهت پیش‌بینی مشخص نشد."
    entry_i = divergence_entry_index(
        hit, fallback=idx, entry_on_early=entry_on_early
    )
    if entry_i is None:
        return None, "اندیس ورود واگرایی مشخص نیست."
    entry_i = max(0, min(entry_i, len(bars) - 1))
    entry_px = bars[entry_i].close
    if entry_px <= 0:
        return None, "قیمت ورود نامعتبر است."
    pivot_b = hit.meta.get("pivot_b")
    if not isinstance(pivot_b, (list, tuple)) or len(pivot_b) < 2:
        return None, "pivot واگرایی برای ارزیابی ناقص است."
    struct_px = float(pivot_b[1])
    move = target_pct / 100.0
    max_fwd = FORWARD_BARS.get(timeframe, 24)
    start = entry_i + 1
    if start >= len(bars):
        return None, "کندل کافی بعد از ورود برای ارزیابی نبود."
    scan_end = min(len(bars), entry_i + 1 + max_fwd)
    tp_px = entry_px * (1 + move) if direction == "up" else entry_px * (1 - move)
    sl_px: float | None = None
    if stop_loss_pct is not None and stop_loss_pct >= 0.1:
        sl_px = _stop_loss_px(entry_px, direction, stop_loss_pct)
    exit_i: int | None = None
    exit_px: float | None = None
    reason = ""
    for i in range(start, scan_end):
        b = bars[i]
        if direction == "up":
            if sl_px is not None and b.low <= sl_px:
                exit_i, exit_px, reason = i, sl_px, f"استاپ {stop_loss_pct:g}٪"
                break
            if b.low < struct_px:
                exit_i, exit_px, reason = i, b.close, "شکست کف واگرایی"
                break
            if b.high >= tp_px:
                exit_i, exit_px, reason = i, tp_px, f"بستن در سود {target_pct:g}٪"
                break
        else:
            if sl_px is not None and b.high >= sl_px:
                exit_i, exit_px, reason = i, sl_px, f"استاپ {stop_loss_pct:g}٪"
                break
            if b.high > struct_px:
                exit_i, exit_px, reason = i, b.close, "شکست سقف واگرایی"
                break
            if b.low <= tp_px:
                exit_i, exit_px, reason = i, tp_px, f"بستن در سود {target_pct:g}٪"
                break
    hit.meta["entry_index"] = entry_i
    hit.meta["tp_px"] = tp_px
    if sl_px is not None:
        hit.meta["sl_px"] = sl_px
    hit.meta["target_profit_pct"] = target_pct
    if stop_loss_pct is not None:
        hit.meta["stop_loss_pct"] = stop_loss_pct
    if exit_i is None:
        return (
            False,
            f"در {max_fwd} کندل بعد از ورود ({entry_px:,.0f}) "
            f"نه سود {target_pct:g}٪ و نه شکست ساختار دیده شد.",
        )
    if direction == "up":
        pct = (exit_px - entry_px) / entry_px if exit_px else 0.0
    else:
        pct = (entry_px - exit_px) / entry_px if exit_px else 0.0
    hit.meta["exit_index"] = exit_i
    hit.meta["path_pct"] = pct
    hit.meta["exit_reason"] = reason
    ok = reason.startswith("بستن در سود")
    note = (
        f"{reason} — ورود {entry_px:,.0f} → ~{exit_px:,.0f} "
        f"({pct * 100:+.2f}٪)"
    )
    return ok, note


def evaluate_target_profit(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    target_pct: float,
    *,
    stop_loss_pct: float | None = None,
    timeframe: str = "15m",
) -> tuple[bool | None, str]:
    direction = expected_direction(hit)
    if direction not in ("up", "down"):
        return None, "جهت پیش‌بینی مشخص نشد."
    entry = entry_price_for_hit(bars, idx, hit)
    if entry is None or entry <= 0:
        return None, "قیمت ورود مشخص نیست."
    move = target_pct / 100.0
    exit_i: int | None = None
    exit_px: float | None = None
    if hit.category == "three_rp":
        mode = hit.meta.get("entry_mode")
        if mode in ("mid_touch", "next_open"):
            start_i = int(hit.meta.get("entry_index", idx))
        else:
            start_i = idx + 1
    else:
        start_i = idx + 1
    max_fwd = FORWARD_BARS.get(timeframe, 24)
    scan_end = min(len(bars), start_i + max_fwd)
    sl_px: float | None = None
    if stop_loss_pct is not None and stop_loss_pct >= 0.1:
        sl_px = _stop_loss_px(entry, direction, stop_loss_pct)
    for i in range(start_i, scan_end):
        b = bars[i]
        if direction == "up":
            if sl_px is not None and b.low <= sl_px:
                exit_i, exit_px = i, sl_px
                hit.meta["exit_index"] = exit_i
                hit.meta["sl_px"] = sl_px
                hit.meta["target_profit_pct"] = target_pct
                return (
                    False,
                    f"استاپ {stop_loss_pct:g}٪ — ورود {entry:,.0f} → ~{exit_px:,.0f}",
                )
            target = entry * (1 + move)
            if b.high >= target:
                exit_i, exit_px = i, target
                break
        else:
            if sl_px is not None and b.high >= sl_px:
                exit_i, exit_px = i, sl_px
                hit.meta["exit_index"] = exit_i
                hit.meta["sl_px"] = sl_px
                hit.meta["target_profit_pct"] = target_pct
                return (
                    False,
                    f"استاپ {stop_loss_pct:g}٪ — ورود {entry:,.0f} → ~{exit_px:,.0f}",
                )
            target = entry * (1 - move)
            if b.low <= target:
                exit_i, exit_px = i, target
                break
    if exit_i is None or exit_px is None:
        return (
            False,
            f"در {max_fwd} کندل بعد از ورود هدف سود {target_pct:g}٪ "
            f"(ورود {entry:,.0f}) محقق نشد.",
        )
    hit.meta["exit_index"] = exit_i
    hit.meta["target_profit_pct"] = target_pct
    if sl_px is not None:
        hit.meta["sl_px"] = sl_px
        hit.meta["stop_loss_pct"] = stop_loss_pct
    note = (
        f"هدف سود {target_pct:g}٪ محقق شد — "
        f"ورود {entry:,.0f} → ~{exit_px:,.0f}"
    )
    return True, note


def _chart_forward_bars(
    bars: list[OhlcBar], hit: PatternHit, sig_ix: int
) -> int:
    return chart_forward_bars(bars, hit, sig_ix)


def evaluate_outcome(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    timeframe: str,
    *,
    target_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    entry_on_early: bool = False,
) -> tuple[bool | None, str]:
    if entry_on_early:
        hit.meta["_backtest_entry_on_early"] = True
    if hit.category == "trendline":
        tp = None
        if target_profit_pct is not None and target_profit_pct >= 0.1:
            tp = target_profit_pct / 100.0
        sl = None
        if stop_loss_pct is not None and stop_loss_pct >= 0.1:
            sl = stop_loss_pct / 100.0
        return evaluate_trendline_path(
            bars,
            idx,
            hit,
            take_profit_pct=tp,
            stop_loss_pct=sl,
            timeframe=timeframe,
            entry_on_early=entry_on_early,
        )
    if (
        hit.category == "divergence"
        and target_profit_pct is not None
        and target_profit_pct >= 0.1
    ):
        return evaluate_divergence_target_profit(
            bars,
            idx,
            hit,
            target_profit_pct,
            timeframe=timeframe,
            stop_loss_pct=stop_loss_pct,
            entry_on_early=entry_on_early,
        )
    if target_profit_pct is not None and target_profit_pct >= 0.1:
        return evaluate_target_profit(
            bars,
            idx,
            hit,
            target_profit_pct,
            stop_loss_pct=stop_loss_pct,
            timeframe=timeframe,
        )
    if hit.category == "ema50":
        return evaluate_ema50_path(bars, idx, hit)
    if hit.category == "three_rp":
        mode = hit.meta.get("entry_mode", "next_open")
        entry = hit.meta.get("entry_px")
        if isinstance(entry, (int, float)) and entry > 0:
            entry_px = float(entry)
        else:
            entry_px = bars[idx].close
        fwd = FORWARD_BARS.get(timeframe, 12)
        entry_i = int(hit.meta.get("entry_index", idx + 1))
        if mode == "next_open":
            if entry_i + fwd > len(bars):
                return None, "کندل کافی بعد از سیگنال برای ارزیابی نبود."
            future = bars[entry_i : entry_i + fwd]
        elif mode == "close_third":
            if idx + fwd >= len(bars):
                return None, "کندل کافی بعد از سیگنال برای ارزیابی نبود."
            future = bars[idx + 1 : idx + 1 + fwd]
        else:
            if idx + fwd > len(bars):
                return None, "کندل کافی بعد از ورود برای ارزیابی نبود."
            future = bars[idx : idx + fwd]
        move = MIN_MOVE_PCT.get(timeframe, 0.015)
        direction = expected_direction(hit)
        if direction == "up":
            peak = max(b.high for b in future)
            ok = peak >= entry_px * (1 + move)
            note = (
                f"هدف صعود {move*100:.1f}٪ — حداکثر {peak:,.0f} vs ورود {entry_px:,.0f}"
            )
            return ok, note
        if direction == "down":
            trough = min(b.low for b in future)
            ok = trough <= entry_px * (1 - move)
            note = (
                f"هدف نزول {move*100:.1f}٪ — حداقل {trough:,.0f} vs ورود {entry_px:,.0f}"
            )
            return ok, note
        return None, "جهت پیش‌بینی مشخص نشد."
    direction = expected_direction(hit)
    if not direction:
        return None, "جهت پیش‌بینی مشخص نشد."
    fwd = FORWARD_BARS.get(timeframe, 12)
    if idx + fwd >= len(bars):
        return None, "کندل کافی بعد از سیگнал برای ارزیابی نبود."
    blended = hit.meta.get("entry_blended_px")
    if isinstance(blended, (int, float)) and blended > 0:
        entry = float(blended)
    else:
        entry = bars[idx].close
    future = bars[idx + 1 : idx + 1 + fwd]
    move = MIN_MOVE_PCT.get(timeframe, 0.015)
    if direction == "up":
        peak = max(b.high for b in future)
        ok = peak >= entry * (1 + move)
        note = (
            f"هدف صعود {move*100:.1f}٪ — حداکثر {peak:,.0f} vs ورود {entry:,.0f}"
        )
        return ok, note
    trough = min(b.low for b in future)
    ok = trough <= entry * (1 - move)
    note = (
        f"هدف نزول {move*100:.1f}٪ — حداقل {trough:,.0f} vs ورود {entry:,.0f}"
    )
    return ok, note


def _dedupe_window(category: str, timeframe: str) -> int:
    if category in HEAVY_STRIDE_CATEGORIES:
        return DEDUPE_BARS_HEAVY.get(timeframe, DEDUPE_BARS.get(timeframe, 12))
    return DEDUPE_BARS.get(timeframe, 12)


def _should_skip_dedupe(
    last_key: dict[str, int], hit: PatternHit, bar_index: int, dedupe: int
) -> bool:
    key = backtest_dedupe_key(hit)
    prev = last_key.get(key)
    if prev is not None and bar_index - prev < dedupe:
        return True
    last_key[key] = bar_index
    return False


def _divergence_window_bars() -> int:
    return LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + RSI_PERIOD + 40


def _shift_hit_bar_indices(hit: PatternHit, offset: int) -> None:
    if offset <= 0:
        return
    meta = hit.meta
    for key in (
        "confirm_index",
        "early_index",
        "final_index",
        "entry_index",
        "break_index",
        "pullback_index",
        "window_offset",
        "signal_index",
        "bar_first",
        "bar_middle",
    ):
        v = meta.get(key)
        if isinstance(v, int):
            meta[key] = v + offset
    for key in ("pivot_a", "pivot_b", "pivot_mid"):
        t = meta.get(key)
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            meta[key] = (int(t[0]) + offset, t[1])
    if hit.category not in ("trendline", "channel"):
        for key in ("touch_highs", "touch_lows", "hi_idx", "lo_idx"):
            lst = meta.get(key)
            if isinstance(lst, list):
                meta[key] = [
                    int(x) + offset for x in lst if isinstance(x, (int, float))
                ]


def _replay_divergence(
    bars: list[OhlcBar],
    *,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> list[tuple[int, PatternHit]]:
    """ریپلی واگرایی: RSI یک‌بار + پنجرهٔ محدود (سریع‌تر از bars[:i+1] روی کل سری)."""
    dedupe = _dedupe_window("divergence", timeframe)
    win = _divergence_window_bars()
    closes = [b.close for b in bars]
    rs_full = rsi(closes, RSI_PERIOD)
    last_key: dict[str, int] = {}
    out: list[tuple[int, PatternHit]] = []
    total = max(1, len(range(scan_start, scan_end + 1, stride)))
    done = 0

    for i in range(scan_start, scan_end + 1, stride):
        _check_cancel(should_cancel)
        lo = max(0, i + 1 - win)
        chunk = bars[lo : i + 1]
        rs_chunk = rs_full[lo : i + 1]
        hit = detect_rsi_divergence(
            chunk,
            timeframe,
            allow_early=False,
            rs=rs_chunk,
        )
        done += 1
        if on_progress and (
            done == 1 or done == total or done % max(1, total // 40) == 0
        ):
            on_progress(done, total)
        if hit is None:
            continue
        _shift_hit_bar_indices(hit, lo)
        if _should_skip_dedupe(last_key, hit, i, dedupe):
            continue
        out.append((i, hit))
    if on_progress:
        on_progress(total, total)
    return out


def _replay_window_bars(category: str) -> int:
    return {
        "trendline": 132,
        "channel": 132,
        "ema50": 200,
        "triangle": 260,
        "flag": 260,
    }.get(category, 220)


def _replay_stride(category: str, timeframe: str, stride: int | None) -> int:
    if stride is not None:
        return stride
    if category in HEAVY_STRIDE_CATEGORIES:
        return STRIDE_HEAVY.get(timeframe, STRIDE_BY_TF.get(timeframe, 1))
    return STRIDE_BY_TF.get(timeframe, 1)


def _replay_three_rp(
    bars: list[OhlcBar],
    *,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> list[tuple[int, PatternHit]]:
    """هر کندل در بازه یک‌بار — همان منطق Enhanced الگوها (بدون پنجرهٔ لغزان)."""
    if timeframe != "1h":
        return []
    last_key: set[str] = set()
    out: list[tuple[int, PatternHit]] = []
    lo = max(2, scan_start)
    total = max(1, len(range(lo, scan_end + 1, stride)))
    done = 0

    for i in range(lo, scan_end + 1, stride):
        _check_cancel(should_cancel)
        hit = detect_three_rp_at(bars, timeframe, i)
        done += 1
        if on_progress and (
            done == 1 or done == total or done % max(1, total // 40) == 0
        ):
            on_progress(done, total)
        if hit is None:
            continue
        key = backtest_dedupe_key(hit)
        if key in last_key:
            continue
        last_key.add(key)
        out.append((i, hit))
    if on_progress:
        on_progress(total, total)
    return out


def _replay_sliding_window(
    bars: list[OhlcBar],
    *,
    category: str,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> list[tuple[int, PatternHit]]:
    dedupe = _dedupe_window(category, timeframe)
    detect = _detector(category)
    win = _replay_window_bars(category)
    last_key: dict[str, int] = {}
    out: list[tuple[int, PatternHit]] = []
    total = max(1, len(range(scan_start, scan_end + 1, stride)))
    done = 0

    for i in range(scan_start, scan_end + 1, stride):
        _check_cancel(should_cancel)
        lo = max(0, i + 1 - win)
        chunk = bars[lo : i + 1]
        hit = detect(chunk, timeframe)
        done += 1
        if on_progress and (
            done == 1 or done == total or done % max(1, total // 40) == 0
        ):
            on_progress(done, total)
        if hit is None:
            continue
        _shift_hit_bar_indices(hit, lo)
        if _should_skip_dedupe(last_key, hit, i, dedupe):
            continue
        out.append((i, hit))
    if on_progress:
        on_progress(total, total)
    return out


def replay_category(
    bars: list[OhlcBar],
    *,
    category: str,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int | None = None,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> list[tuple[int, PatternHit]]:
    st = _replay_stride(category, timeframe, stride)
    if category == "three_rp":
        st = 1
        return _replay_three_rp(
            bars,
            timeframe=timeframe,
            scan_start=scan_start,
            scan_end=scan_end,
            stride=st,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
    if category == "divergence":
        return _replay_divergence(
            bars,
            timeframe=timeframe,
            scan_start=scan_start,
            scan_end=scan_end,
            stride=st,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
    return _replay_sliding_window(
        bars,
        category=category,
        timeframe=timeframe,
        scan_start=scan_start,
        scan_end=scan_end,
        stride=st,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )


def run_backtest(
    *,
    data_base: Path,
    chart_dir: Path,
    category: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    stride: int | None = None,
    max_charts: int = 200,
    chart_prefix: str = "",
    on_progress: ProgressFn | None = None,
    target_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    entry_on_early: bool = False,
    should_cancel: CancelFn | None = None,
) -> BacktestResult:
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    if timeframe not in BACKTEST_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if category == "three_rp" and timeframe != "1h":
        result = BacktestResult(
            category=category,
            timeframe=timeframe,
            from_iso=start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            to_iso=end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            bars_total=0,
            bars_scanned=0,
            stride=1,
            target_profit_pct=target_profit_pct,
            stop_loss_pct=stop_loss_pct,
            entry_on_early=entry_on_early,
        )
        result.error = "۳BRP فقط روی تایم‌فریم ۱ ساعت قابل بکتست است."
        return result

    hist_dir = history_data_dir(data_base)
    bars = load_cached_bars(hist_dir, timeframe)
    full, scan_start, scan_end = slice_with_warmup(bars, start, end)
    result = BacktestResult(
        category=category,
        timeframe=timeframe,
        from_iso=start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        to_iso=end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        bars_total=len(full),
        bars_scanned=max(0, scan_end - scan_start + 1) if scan_end >= scan_start else 0,
        stride=stride or STRIDE_BY_TF.get(timeframe, 1),
        target_profit_pct=target_profit_pct,
        stop_loss_pct=stop_loss_pct,
        entry_on_early=entry_on_early,
    )

    if not bars:
        result.error = "کش این تایم‌فریم خالی است — نصب/دانلود تاریخچه را اجرا کنید."
        return result
    if scan_end < scan_start or not full:
        result.error = "بازهٔ انتخابی خارج از دادهٔ ذخیره‌شده است."
        return result

    stride_val = _replay_stride(category, timeframe, stride)
    result.stride = stride_val

    scan_pct = 42

    def scan_progress(done: int, total: int) -> None:
        if on_progress and total:
            on_progress(int(done * scan_pct / total), 100)

    _check_cancel(should_cancel)

    raw_hits = replay_category(
        full,
        category=category,
        timeframe=timeframe,
        scan_start=scan_start,
        scan_end=scan_end,
        stride=stride_val,
        on_progress=scan_progress if on_progress else None,
        should_cancel=should_cancel,
    )

    n_findings = max(1, len(raw_hits))
    chart_limit = max_charts
    if category in ("trendline", "channel", "ema50") and chart_limit > 48:
        chart_limit = 48

    chart_dir.mkdir(parents=True, exist_ok=True)
    for n, (idx, hit) in enumerate(raw_hits):
        _check_cancel(should_cancel)

        def _phase(fraction: float) -> None:
            if on_progress:
                on_progress(
                    scan_pct
                    + int(fraction * (100 - scan_pct) / n_findings),
                    100,
                )

        _phase(float(n) + 0.05)
        entry_ix = idx
        if hit.category == "divergence":
            dei = divergence_entry_index(
                hit, fallback=idx, entry_on_early=entry_on_early
            )
            if isinstance(dei, int):
                entry_ix = dei
        elif hit.category == "three_rp":
            ei = hit.meta.get("entry_index")
            if isinstance(ei, int):
                entry_ix = ei
        ts = full[entry_ix].ts
        success, outcome_fa = evaluate_outcome(
            full,
            entry_ix,
            hit,
            timeframe,
            target_profit_pct=target_profit_pct,
            stop_loss_pct=stop_loss_pct,
            entry_on_early=entry_on_early,
        )
        _phase(float(n) + 0.45)
        finding = BacktestFinding.from_hit(
            hit, entry_ix, ts, success=success, outcome_fa=outcome_fa
        )
        if success is True:
            result.success_count += 1
        elif success is False:
            result.fail_count += 1
        if n < chart_limit:
            _phase(float(n) + 0.55)
            if hit.category in ("trendline", "ema50", "channel"):
                sig_ix = hit.meta.get("entry_index", hit.meta.get("early_index", idx))
            elif hit.category == "three_rp":
                sig_ix = hit.meta.get(
                    "entry_index",
                    hit.meta.get("signal_index", idx),
                )
            else:
                sig_ix = hit.meta.get("confirm_index", idx)
            if not isinstance(sig_ix, int):
                sig_ix = idx
            fwd = _chart_forward_bars(full, hit, sig_ix)
            png = render_pattern_chart(
                full,
                hit,
                signal_index=sig_ix,
                forward_bars=fwd,
                outcome_success=success,
            )
            _phase(float(n) + 0.92)
            if png:
                fname = f"{chart_prefix}bt_{category}_{timeframe}_{idx}_{hit.pattern_id}.png"
                (chart_dir / fname).write_bytes(png)
                finding.chart_file = fname
        result.findings.append(finding)
        _phase(float(n) + 1.0)

    if on_progress:
        on_progress(100, 100)

    return result


def parse_user_datetime(s: str, end_of_day: bool = False) -> datetime:
    s = s.strip()
    if "T" in s:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    dt = datetime.fromisoformat(s + "T00:00:00").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt
