from __future__ import annotations

import logging
import threading
from typing import Any

from app.storage import data_dir
from optionflow.patterns.history import (
    BACKTEST_INTERVALS,
    expected_sync_utc_day_str,
    history_data_dir,
    record_daily_sync_success,
)
from optionflow.patterns.seed_history import seed_btc_history

logger = logging.getLogger("optionflow.history.jobs")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "progress_pct": 0,
    "message": "",
    "interval": "",
    "error": "",
}


def history_download_state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set_progress(pct: int, message: str, interval: str = "") -> None:
    with _lock:
        _state["progress_pct"] = max(0, min(100, pct))
        _state["message"] = message
        if interval:
            _state["interval"] = interval


def start_history_download(*, interval: str | None = None, days: int = 730) -> bool:
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True,
            progress_pct=0,
            message="شروع دانلود…",
            interval=interval or "all",
            error="",
        )

    ivs = (interval,) if interval else BACKTEST_INTERVALS

    def _work() -> None:
        try:
            base = data_dir()

            def on_iv(iv: str, pct: int, msg: str) -> None:
                label = iv
                if msg and msg != "تمام":
                    _set_progress(pct, f"{label}: {msg}", iv)
                else:
                    _set_progress(pct, f"در حال دانلود {label}… ({pct}٪)", iv)

            seed_btc_history(base, days=days, intervals=ivs, on_interval_progress=on_iv)
            utc_day = expected_sync_utc_day_str()
            record_daily_sync_success(history_data_dir(base), utc_day=utc_day, intervals=ivs)
            _set_progress(100, "دانلود تمام شد.")
        except Exception as e:
            logger.exception("history download failed")
            with _lock:
                _state["error"] = str(e)[:300]
                _state["message"] = "خطا در دانلود"
        finally:
            with _lock:
                _state["running"] = False

    threading.Thread(target=_work, name="btc-history-dl", daemon=True).start()
    return True
