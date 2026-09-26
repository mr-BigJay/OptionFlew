"""چارت زندهٔ v2: کندل به‌اضافهٔ یک خط مسیر. گزارش‌های قبلی اینجا ساخته نمی‌شوند."""

from __future__ import annotations

import json
import logging

from optionflow.path_v2 import PathV2, caption_fa, live_path_v2, path_line
from optionflow.patterns.chart_overlays import bar_unix, candles_payload
from optionflow.patterns.ohlc import load_btcusdt

logger = logging.getLogger("optionflow.v2")

V2_CANDLE_INTERVAL = "15m"
V2_CANDLE_LIMIT = 500
V2_CANDLE_BARS = 480
V2_PATH_MIN_HOURS = 72
V2_PATH_MAX_HOURS = 96


def v2_chart_payload() -> dict:
    path: PathV2 | None = None
    try:
        path = live_path_v2()
    except Exception:
        logger.exception("v2 path failed")
    bars = []
    try:
        bars = load_btcusdt(V2_CANDLE_INTERVAL, limit=V2_CANDLE_LIMIT)[
            -V2_CANDLE_BARS:
        ]
    except Exception:
        logger.exception("v2 candles failed")
    line: list[dict] = []
    near_line: list[dict] = []
    if path is not None and path.target is not None and bars:
        anchor = float(bars[-1].close)
        step_sec = 900
        if len(bars) >= 2:
            step_sec = max(60, bar_unix(bars[-1]) - bar_unix(bars[-2]))
        start_unix = bar_unix(bars[-1]) + step_sec
        drift = "pin" if path.side == "pin" else "linear"
        line = path_line(
            anchor,
            path.target,
            start_unix,
            path.expiry_unix,
            drift=drift,
            min_display_seconds=V2_PATH_MIN_HOURS * 3600,
            max_display_seconds=V2_PATH_MAX_HOURS * 3600,
        )
        _prepend_anchor(line, bar_unix(bars[-1]), anchor)
        near_target = _near_target(path)
        if near_target is not None and near_target != path.target:
            near_line = path_line(
                anchor,
                near_target,
                start_unix,
                path.expiry_unix,
                drift=drift,
                min_display_seconds=48 * 3600,
                max_display_seconds=72 * 3600,
            )
            _prepend_anchor(near_line, bar_unix(bars[-1]), anchor)
    return {
        "interval": V2_CANDLE_INTERVAL,
        "candles": candles_payload(bars),
        "line": line,
        "near_line": near_line,
        "caption": caption_fa(path),
    }


def _prepend_anchor(points: list[dict], time_unix: int, anchor: float) -> None:
    if not points:
        return
    head = {"time": time_unix, "value": round(anchor, 2)}
    if points[0]["time"] == time_unix:
        points[0] = head
    else:
        points.insert(0, head)


def _near_target(path: PathV2) -> int | None:
    """مقصد نزدیک‌تر (مثلاً bcg) وقتی هدف اصلی دورتر است."""
    if path.side == "up" and path.target == path.scg and path.bcg:
        return path.bcg
    if path.side == "down" and path.target == path.bps and path.sps:
        return path.sps
    if path.side == "pin" and path.bcg:
        return path.bcg
    return None


def v2_payload_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
