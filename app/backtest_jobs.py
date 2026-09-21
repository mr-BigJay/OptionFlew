from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.backtest_store import (
    create_backtest_run,
    fail_backtest_run,
    finish_backtest_run,
    update_backtest_progress,
)
from app.storage import data_dir
from optionflow.patterns.backtest import parse_user_datetime, run_backtest
from optionflow.patterns.service import patterns_data_dir

logger = logging.getLogger("optionflow.backtest.jobs")

_lock = threading.Lock()
_running: set[int] = set()


def start_backtest_job(
    *,
    category: str,
    timeframe: str,
    date_from: str,
    date_to: str,
    target_profit_pct: float | None = None,
) -> int:
    start = parse_user_datetime(date_from)
    end = parse_user_datetime(date_to, end_of_day=True)
    run_id = create_backtest_run(
        category=category,
        timeframe=timeframe,
        from_iso=start.isoformat().replace("+00:00", "Z"),
        to_iso=end.isoformat().replace("+00:00", "Z"),
        target_profit_pct=target_profit_pct,
    )

    def _work() -> None:
        with _lock:
            _running.add(run_id)
        try:
            base = data_dir()
            charts = patterns_data_dir(base)
            prefix = f"run{run_id}_"

            def on_progress(done: int, total: int) -> None:
                pct = int(done * 100 / total) if total else 0
                update_backtest_progress(run_id, pct, done)

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
            )
            finish_backtest_run(run_id, result.to_dict())
        except Exception as e:
            logger.exception("backtest job %s failed", run_id)
            fail_backtest_run(run_id, str(e))
        finally:
            with _lock:
                _running.discard(run_id)

    threading.Thread(target=_work, name=f"backtest-{run_id}", daemon=True).start()
    return run_id


def is_run_active(run_id: int) -> bool:
    with _lock:
        return run_id in _running
