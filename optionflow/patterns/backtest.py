from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

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
from optionflow.patterns.triangle import detect_triangle
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.backtest")

CATEGORIES = ("triangle", "flag", "divergence", "trendline", "channel", "ema50")
STRIDE_BY_TF = {"5m": 6, "15m": 2, "1h": 1, "4h": 1, "1d": 1}
STRIDE_DIVERGENCE = {"5m": 12, "15m": 4, "1h": 2, "4h": 1, "1d": 1}
DEDUPE_BARS = {"5m": 48, "15m": 20, "1h": 24, "4h": 8, "1d": 4}
FORWARD_BARS = {"5m": 36, "15m": 24, "1h": 18, "4h": 12, "1d": 8}
MIN_MOVE_PCT = {"5m": 0.008, "15m": 0.012, "1h": 0.015, "4h": 0.02, "1d": 0.025}
BACKTEST_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")

ProgressFn = Callable[[int, int], None]


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
    if hit.category in ("trendline", "channel", "ema50"):
        explicit = hit.meta.get("direction")
        if explicit in ("up", "down"):
            return explicit
        return None
    return None


def entry_price_for_hit(
    bars: list[OhlcBar], idx: int, hit: PatternHit
) -> float | None:
    meta = hit.meta
    blended = meta.get("entry_blended_px")
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
    if 0 <= idx < len(bars):
        return float(bars[idx].close)
    return None


def evaluate_target_profit(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    target_pct: float,
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
    for i in range(idx + 1, len(bars)):
        b = bars[i]
        if direction == "up":
            target = entry * (1 + move)
            if b.high >= target:
                exit_i, exit_px = i, target
                break
        else:
            target = entry * (1 - move)
            if b.low <= target:
                exit_i, exit_px = i, target
                break
    if exit_i is None or exit_px is None:
        return (
            False,
            f"تا پایان داده هدف سود {target_pct:g}٪ (ورود {entry:,.0f}) محقق نشد.",
        )
    hit.meta["exit_index"] = exit_i
    hit.meta["target_profit_pct"] = target_pct
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
) -> tuple[bool | None, str]:
    if target_profit_pct is not None and target_profit_pct >= 0.1:
        return evaluate_target_profit(bars, idx, hit, target_profit_pct)
    if hit.category == "trendline":
        return evaluate_trendline_path(bars, idx, hit)
    if hit.category == "ema50":
        return evaluate_ema50_path(bars, idx, hit)
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
    ):
        v = meta.get(key)
        if isinstance(v, int):
            meta[key] = v + offset
    for key in ("pivot_a", "pivot_b", "pivot_mid"):
        t = meta.get(key)
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            meta[key] = (int(t[0]) + offset, t[1])


def _replay_divergence(
    bars: list[OhlcBar],
    *,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int,
    on_progress: ProgressFn | None = None,
) -> list[tuple[int, PatternHit]]:
    """ریپلی واگرایی: RSI یک‌بار + پنجرهٔ محدود (سریع‌تر از bars[:i+1] روی کل سری)."""
    dedupe = DEDUPE_BARS.get(timeframe, 12)
    win = _divergence_window_bars()
    closes = [b.close for b in bars]
    rs_full = rsi(closes, RSI_PERIOD)
    last_key: dict[str, int] = {}
    out: list[tuple[int, PatternHit]] = []
    total = max(1, len(range(scan_start, scan_end + 1, stride)))
    done = 0

    for i in range(scan_start, scan_end + 1, stride):
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
        prev = last_key.get(hit.pattern_id)
        if prev is not None and i - prev < dedupe:
            continue
        last_key[hit.pattern_id] = i
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
) -> list[tuple[int, PatternHit]]:
    if category == "divergence":
        st = stride or STRIDE_DIVERGENCE.get(timeframe, STRIDE_BY_TF.get(timeframe, 1))
        return _replay_divergence(
            bars,
            timeframe=timeframe,
            scan_start=scan_start,
            scan_end=scan_end,
            stride=st,
            on_progress=on_progress,
        )
    stride = stride or STRIDE_BY_TF.get(timeframe, 1)
    dedupe = DEDUPE_BARS.get(timeframe, 12)
    detect = _detector(category)
    last_key: dict[str, int] = {}
    out: list[tuple[int, PatternHit]] = []
    indices = range(scan_start, scan_end + 1, stride)
    total = max(1, len(list(range(scan_start, scan_end + 1, stride))))
    done = 0

    for i in range(scan_start, scan_end + 1, stride):
        hit = detect(bars[: i + 1], timeframe)
        done += 1
        if on_progress and (done == 1 or done == total or done % max(1, total // 50) == 0):
            on_progress(done, total)
        if hit is None:
            continue
        prev = last_key.get(hit.pattern_id)
        if prev is not None and i - prev < dedupe:
            continue
        last_key[hit.pattern_id] = i
        out.append((i, hit))
    if on_progress:
        on_progress(total, total)
    return out


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
) -> BacktestResult:
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    if timeframe not in BACKTEST_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")

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
    )

    if not bars:
        result.error = "کش این تایم‌فریم خالی است — نصب/دانلود تاریخچه را اجرا کنید."
        return result
    if scan_end < scan_start or not full:
        result.error = "بازهٔ انتخابی خارج از دادهٔ ذخیره‌شده است."
        return result

    stride_val = stride or (
        STRIDE_DIVERGENCE.get(timeframe, STRIDE_BY_TF.get(timeframe, 1))
        if category == "divergence"
        else STRIDE_BY_TF.get(timeframe, 1)
    )
    result.stride = stride_val

    def scan_progress(done: int, total: int) -> None:
        if on_progress and total:
            on_progress(int(done * 72 / total), 100)

    raw_hits = replay_category(
        full,
        category=category,
        timeframe=timeframe,
        scan_start=scan_start,
        scan_end=scan_end,
        stride=stride_val,
        on_progress=scan_progress if on_progress else None,
    )

    chart_cap = min(len(raw_hits), max_charts)
    chart_cap = max(chart_cap, 1)

    chart_dir.mkdir(parents=True, exist_ok=True)
    for n, (idx, hit) in enumerate(raw_hits):
        ts = full[idx].ts
        success, outcome_fa = evaluate_outcome(
            full,
            idx,
            hit,
            timeframe,
            target_profit_pct=target_profit_pct,
        )
        finding = BacktestFinding.from_hit(
            hit, idx, ts, success=success, outcome_fa=outcome_fa
        )
        if success is True:
            result.success_count += 1
        elif success is False:
            result.fail_count += 1
        if n < max_charts:
            if hit.category in ("trendline", "ema50"):
                sig_ix = hit.meta.get("entry_index", hit.meta.get("early_index", idx))
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
            if png:
                fname = f"{chart_prefix}bt_{category}_{timeframe}_{idx}_{hit.pattern_id}.png"
                (chart_dir / fname).write_bytes(png)
                finding.chart_file = fname
        result.findings.append(finding)
        if on_progress and n < max_charts:
            on_progress(72 + int((n + 1) * 28 / chart_cap), 100)
        elif on_progress and n == len(raw_hits) - 1:
            on_progress(100, 100)

    if on_progress and not raw_hits:
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
