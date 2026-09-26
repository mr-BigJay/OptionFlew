from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.backtest_store import (
    cancel_backtest_run,
    create_backtest_run,
    fail_backtest_run,
    finish_backtest_run,
    get_backtest_run,
    update_backtest_progress,
)
from app.storage import data_dir
from optionflow.patterns.backtest import (
    BacktestCancelled,
    parse_user_datetime,
    run_backtest,
)
from optionflow.patterns.service import patterns_data_dir

logger = logging.getLogger("optionflow.backtest.jobs")

_lock = threading.Lock()
_running: set[int] = set()
_cancel_requested: set[int] = set()


def start_backtest_job(
    *,
    category: str,
    timeframe: str,
    date_from: str,
    date_to: str,
    target_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    entry_on_early: bool = False,
    skip_four_touches: bool = False,
) -> int:
    start = parse_user_datetime(date_from)
    end = parse_user_datetime(date_to, end_of_day=True)
    run_id = create_backtest_run(
        category=category,
        timeframe=timeframe,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
        target_profit_pct=target_profit_pct,
        stop_loss_pct=stop_loss_pct,
        entry_on_early=entry_on_early,
        skip_four_touches=skip_four_touches,
    )

    def _work() -> None:
        with _lock:
            _running.add(run_id)
        try:

            def should_cancel() -> bool:
                with _lock:
                    return run_id in _cancel_requested

            def on_progress(done: int, total: int) -> None:
                if should_cancel():
                    raise BacktestCancelled()
                pct = int(done * 100 / total) if total else 0
                update_backtest_progress(run_id, pct, done)

            base = data_dir()
            charts = patterns_data_dir(base)
            prefix = f"run{run_id}_"

            result = run_backtest(
                data_base=base,
                chart_dir=charts,
                category=category,
                timeframe=timeframe,
                start=start,
                end=end,
                chart_prefix=prefix,
                on_progress=on_progress,
                target_profit_pct=target_profit_pct,
                stop_loss_pct=stop_loss_pct,
                entry_on_early=entry_on_early,
                skip_four_touches=skip_four_touches,
                should_cancel=should_cancel,
            )
            with _lock:
                if run_id in _cancel_requested:
                    return
            finish_backtest_run(run_id, result.to_dict())
        except BacktestCancelled:
            logger.info("backtest job %s cancelled", run_id)
            cancel_backtest_run(run_id)
        except Exception as e:
            logger.exception("backtest job %s failed", run_id)
            with _lock:
                if run_id not in _cancel_requested:
                    fail_backtest_run(run_id, str(e))
        finally:
            with _lock:
                _running.discard(run_id)
                _cancel_requested.discard(run_id)

    threading.Thread(target=_work, name=f"backtest-{run_id}", daemon=True).start()
    return run_id


def request_cancel_backtest(run_id: int) -> bool:
    """توقف job فعال یا علامت‌گذاری run گیرکرده (running بدون thread)."""
    run = get_backtest_run(run_id)
    if not run or run.get("status") != "running":
        return False
    with _lock:
        _cancel_requested.add(run_id)
        active = run_id in _running
    if not cancel_backtest_run(run_id):
        with _lock:
            _cancel_requested.discard(run_id)
        return False
    if not active:
        with _lock:
            _cancel_requested.discard(run_id)
    return True


def is_run_active(run_id: int) -> bool:
    with _lock:
        return run_id in _running
