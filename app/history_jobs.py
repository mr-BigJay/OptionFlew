from __future__ import annotations

import logging
import threading
from typing import Any

from app.storage import data_dir
from optionflow.patterns.history import BACKTEST_INTERVALS
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
            total = len(ivs)
            for n, iv in enumerate(ivs):
                with _lock:
                    _state["message"] = f"در حال دانلود {iv}…"
                    _state["interval"] = iv
                seed_btc_history(base, days=days, intervals=(iv,))
                with _lock:
                    _state["progress_pct"] = int((n + 1) * 100 / total)
            with _lock:
                _state["message"] = "دانلود تمام شد."
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
