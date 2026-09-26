"""چارت زندهٔ v2: کندل به‌اضافهٔ یک خط مسیر. گزارش‌های قبلی اینجا ساخته نمی‌شوند."""

from __future__ import annotations

import json
import logging

from optionflow.path_v2 import PathV2, caption_fa, live_path_v2, path_line
from optionflow.patterns.chart_overlays import bar_unix, candles_payload
from optionflow.patterns.ohlc import load_btcusdt

logger = logging.getLogger("optionflow.v2")

V2_CANDLE_LIMIT = 120
V2_CANDLE_BARS = 96
V2_PATH_DISPLAY_HOURS = 36


def v2_chart_payload() -> dict:
    path: PathV2 | None = None
    try:
        path = live_path_v2()
    except Exception:
        logger.exception("v2 path failed")
    bars = []
    try:
        bars = load_btcusdt("1h", limit=V2_CANDLE_LIMIT)[-V2_CANDLE_BARS:]
    except Exception:
        logger.exception("v2 candles failed")
    line: list[dict] = []
    if path is not None and path.target is not None and bars:
        line = path_line(
            path.spot,
            path.target,
            bar_unix(bars[-1]),
            path.expiry_unix,
            drift="pin" if path.side == "pin" else "linear",
            max_display_seconds=V2_PATH_DISPLAY_HOURS * 3600,
        )
    return {
        "candles": candles_payload(bars),
        "line": line,
        "caption": caption_fa(path),
    }


def v2_payload_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
