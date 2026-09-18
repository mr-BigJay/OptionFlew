from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from optionflow.patterns.chart import render_pattern_chart
from optionflow.patterns.divergence import detect_rsi_divergence
from optionflow.patterns.flag import detect_flag
from optionflow.patterns.history import (
    INTERVAL_MS,
    load_cached_bars,
    history_data_dir,
    slice_with_warmup,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.triangle import detect_triangle
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.backtest")

CATEGORIES = ("triangle", "flag", "divergence")
STRIDE_BY_TF = {"5m": 6, "15m": 2, "1h": 1, "4h": 1, "1d": 1}
DEDUPE_BARS = {"5m": 48, "15m": 20, "1h": 16, "4h": 8, "1d": 4}
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
    return None


def evaluate_outcome(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    timeframe: str,
) -> tuple[bool | None, str]:
    direction = expected_direction(hit)
    if not direction:
        return None, "جهت پیش‌بینی مشخص نشد."
    fwd = FORWARD_BARS.get(timeframe, 12)
    if idx + fwd >= len(bars):
        return None, "کندل کافی بعد از سیگнал برای ارزیابی نبود."
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
    )

    if not bars:
        result.error = "کش این تایم‌فریم خالی است — نصب/دانلود تاریخچه را اجرا کنید."
        return result
    if scan_end < scan_start or not full:
        result.error = "بازهٔ انتخابی خارج از دادهٔ ذخیره‌شده است."
        return result

    raw_hits = replay_category(
        full,
        category=category,
        timeframe=timeframe,
        scan_start=scan_start,
        scan_end=scan_end,
        stride=stride,
        on_progress=on_progress,
    )

    chart_dir.mkdir(parents=True, exist_ok=True)
    for n, (idx, hit) in enumerate(raw_hits):
        ts = full[idx].ts
        success, outcome_fa = evaluate_outcome(full, idx, hit, timeframe)
        finding = BacktestFinding.from_hit(
            hit, idx, ts, success=success, outcome_fa=outcome_fa
        )
        if success is True:
            result.success_count += 1
        elif success is False:
            result.fail_count += 1
        if n < max_charts:
            sig_ix = hit.meta.get("confirm_index", idx)
            png = render_pattern_chart(
                full,
                hit,
                signal_index=sig_ix,
                forward_bars=FORWARD_BARS.get(timeframe, 18),
                outcome_success=success,
            )
            if png:
                fname = f"{chart_prefix}bt_{category}_{timeframe}_{idx}_{hit.pattern_id}.png"
                (chart_dir / fname).write_bytes(png)
                finding.chart_file = fname
        result.findings.append(finding)

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
