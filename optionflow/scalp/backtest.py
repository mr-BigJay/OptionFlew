from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from optionflow.patterns.backtest import (
    BacktestCancelled,
    BacktestFinding,
    BacktestResult,
    _check_cancel,
    _shift_hit_bar_indices,
    parse_user_datetime,
)
from optionflow.patterns.chart import chart_forward_bars, render_pattern_chart
from optionflow.patterns.history import load_cached_bars, history_data_dir, slice_with_warmup
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit
from optionflow.scalp.detect import detect_scalp_scenario
from optionflow.scalp.evaluate import evaluate_scalp_path
from optionflow.scalp.four_h_rr import scan_4hrr_backtest
from optionflow.scalp.scenarios import BACKTEST_TIMEFRAMES

logger = logging.getLogger("optionflow.scalp.backtest")

STRIDE_BY_TF = {"5m": 4, "15m": 2, "1h": 1, "4h": 1}
DEDUPE_BARS = {"5m": 36, "15m": 16, "1h": 12, "4h": 6}
WINDOW = 220

ProgressFn = Callable[[int, int], None]
CancelFn = Callable[[], bool]


def _replay_scalp(
    bars: list[OhlcBar],
    *,
    scenario: dict,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    stride: int,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> list[tuple[int, PatternHit]]:
    dedupe = DEDUPE_BARS.get(timeframe, 12)
    params = scenario.get("params") or {}
    last_key: dict[str, int] = {}
    out: list[tuple[int, PatternHit]] = []
    total = max(1, len(range(scan_start, scan_end + 1, stride)))
    done = 0

    for i in range(scan_start, scan_end + 1, stride):
        _check_cancel(should_cancel)
        lo = max(0, i + 1 - WINDOW)
        chunk = bars[lo : i + 1]
        hit = detect_scalp_scenario(chunk, timeframe, scenario, params)
        done += 1
        if on_progress and (
            done == 1 or done == total or done % max(1, total // 40) == 0
        ):
            on_progress(done, total)
        if hit is None:
            continue
        _shift_hit_bar_indices(hit, lo)
        meta = hit.meta
        sk = meta.get("setup_key") or hit.pattern_id
        prev = last_key.get(sk)
        if prev is not None and i - prev < dedupe:
            continue
        last_key[sk] = i
        out.append((i, hit))
    if on_progress:
        on_progress(total, total)
    return out


def run_scalp_backtest(
    *,
    data_base: Path,
    chart_dir: Path,
    scenario: dict,
    timeframe: str,
    start: datetime,
    end: datetime,
    chart_prefix: str = "",
    max_charts: int = 120,
    on_progress: ProgressFn | None = None,
    should_cancel: CancelFn | None = None,
) -> BacktestResult:
    scenario_id = scenario["scenario_id"]
    if timeframe not in BACKTEST_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")

    hist_dir = history_data_dir(data_base)
    bars = load_cached_bars(hist_dir, timeframe)
    full, scan_start, scan_end = slice_with_warmup(bars, start, end)
    stride = STRIDE_BY_TF.get(timeframe, 2)
    result = BacktestResult(
        category=f"scalp:{scenario_id}",
        timeframe=timeframe,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
        bars_total=len(full),
        bars_scanned=0,
        stride=stride,
    )
    if scan_end <= scan_start:
        result.error = "بازهٔ انتخابی کندل کافی ندارد."
        return result

    detector = scenario.get("detector_type") or scenario_id
    if detector == "four_h_rr":
        bars_4h = load_cached_bars(hist_dir, "4h")
        if not bars_4h:
            result.error = "کش 4h موجود نیست — از بکتست الگو دانلود کنید."
            return result
        pairs = scan_4hrr_backtest(
            full,
            bars_4h,
            scenario=scenario,
            params=scenario.get("params") or {},
            start=start,
            end=end,
            timeframe=timeframe,
        )
        if on_progress:
            on_progress(1, 1)
    else:
        pairs = _replay_scalp(
            full,
            scenario=scenario,
            timeframe=timeframe,
            scan_start=scan_start,
            scan_end=scan_end,
            stride=stride,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
    result.bars_scanned = max(1, (scan_end - scan_start + 1) // stride)
    charts_left = max_charts
    for sig_ix, hit in pairs:
        _check_cancel(should_cancel)
        ok, note = evaluate_scalp_path(full, hit, bar_index=sig_ix)
        ts = full[sig_ix].ts
        finding = BacktestFinding.from_hit(
            hit,
            sig_ix,
            ts,
            success=ok,
            outcome_fa=note,
        )
        if charts_left > 0:
            fwd = chart_forward_bars(full, hit, sig_ix)
            png = render_pattern_chart(
                full,
                hit,
                signal_index=sig_ix,
                forward_bars=fwd,
                outcome_success=ok,
            )
            if png:
                fname = f"{chart_prefix}scalp_{scenario_id}_{timeframe}_{sig_ix}.png"
                (chart_dir / fname).write_bytes(png)
                finding.chart_file = fname
                charts_left -= 1
        if ok is True:
            result.success_count += 1
        elif ok is False:
            result.fail_count += 1
        result.findings.append(finding)

    return result
