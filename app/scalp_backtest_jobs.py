from __future__ import annotations

import logging
import threading

from app.scalp_backtest_store import (
    cancel_scalp_backtest_run,
    create_scalp_backtest_run,
    fail_scalp_backtest_run,
    finish_scalp_backtest_run,
    get_scalp_backtest_run,
    update_scalp_backtest_progress,
)
from app.scalp_store import get_scenario
from app.storage import data_dir
from optionflow.patterns.backtest import BacktestCancelled, parse_user_datetime
from optionflow.patterns.service import patterns_data_dir
from optionflow.scalp.backtest import run_scalp_backtest

logger = logging.getLogger("optionflow.scalp.backtest.jobs")

_lock = threading.Lock()
_running: set[int] = set()
_cancel_requested: set[int] = set()


def start_scalp_backtest_job(
    *,
    scenario_id: str,
    timeframe: str,
    date_from: str,
    date_to: str,
) -> int:
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise ValueError("scenario not found")
    start = parse_user_datetime(date_from)
    end = parse_user_datetime(date_to, end_of_day=True)
    run_id = create_scalp_backtest_run(
        scenario_id=scenario_id,
        timeframe=timeframe,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
    )

    def _work() -> None:
        with _lock:
            _running.add(run_id)
        try:
            sc = get_scenario(scenario_id)
            if not sc:
                fail_scalp_backtest_run(run_id, "سناریو پیدا نشد")
                return

            def should_cancel() -> bool:
                with _lock:
                    return run_id in _cancel_requested

            def on_progress(done: int, total: int) -> None:
                if should_cancel():
                    raise BacktestCancelled()
                pct = int(done * 100 / total) if total else 0
                update_scalp_backtest_progress(run_id, pct, done)

            base = data_dir()
            charts = patterns_data_dir(base)
            prefix = f"scalp_run{run_id}_"
            result = run_scalp_backtest(
                data_base=base,
                chart_dir=charts,
                scenario=sc,
                timeframe=timeframe,
                start=start,
                end=end,
                chart_prefix=prefix,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
            with _lock:
                if run_id in _cancel_requested:
                    return
            finish_scalp_backtest_run(run_id, result.to_dict())
        except BacktestCancelled:
            logger.info("scalp backtest %s cancelled", run_id)
            cancel_scalp_backtest_run(run_id)
        except Exception as e:
            logger.exception("scalp backtest %s failed", run_id)
            with _lock:
                if run_id not in _cancel_requested:
                    fail_scalp_backtest_run(run_id, str(e))
        finally:
            with _lock:
                _running.discard(run_id)
                _cancel_requested.discard(run_id)

    threading.Thread(
        target=_work, name=f"scalp-backtest-{run_id}", daemon=True
    ).start()
    return run_id


def request_cancel_scalp_backtest(run_id: int) -> bool:
    run = get_scalp_backtest_run(run_id)
    if not run or run.get("status") != "running":
        return False
    with _lock:
        _cancel_requested.add(run_id)
        active = run_id in _running
    if not cancel_scalp_backtest_run(run_id):
        with _lock:
            _cancel_requested.discard(run_id)
        return False
    if not active:
        with _lock:
            _cancel_requested.discard(run_id)
    return True
