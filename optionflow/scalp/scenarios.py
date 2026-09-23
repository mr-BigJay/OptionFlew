from __future__ import annotations

import json
from typing import Any

BUILTIN: list[dict[str, Any]] = [
    {
        "scenario_id": "range_break",
        "title_fa": "شکست فشردگی رنج",
        "description_fa": (
            "رنج باریک نسبت به ATR؛ ورود روی بسته شدن خارج از رنج. "
            "استاپ پشت طرف مقابل رنج؛ TP بر اساس نسبت R."
        ),
        "detector_type": "range_break",
        "timeframes": ["5m", "15m"],
        "params": {
            "range_bars": 12,
            "range_atr_mult": 1.25,
            "stop_atr_mult": 0.4,
            "tp_rr": 1.5,
            "max_hold_bars": 28,
        },
    },
    {
        "scenario_id": "sweep_reclaim",
        "title_fa": "سویپ نقدینگی و بازگشت",
        "description_fa": (
            "نفوذ زیر کف/بالای سقف کوتاه‌مدت و بسته شدن داخل محدوده — "
            "ورود روی تأیید؛ استاپ پشت اکسترمم سویپ."
        ),
        "detector_type": "sweep_reclaim",
        "timeframes": ["5m", "15m"],
        "params": {
            "swing_lookback": 18,
            "sweep_atr_mult": 0.35,
            "stop_atr_mult": 0.35,
            "tp_rr": 1.6,
            "max_hold_bars": 24,
        },
    },
    {
        "scenario_id": "impulse_pullback",
        "title_fa": "پول‌بک بعد از impulse",
        "description_fa": (
            "کندل impulse قوی و پول‌بک به نیمهٔ بدنه؛ "
            "ورود روی برگشت هم‌جهت؛ استاپ پشت اکسترمم پول‌بک."
        ),
        "detector_type": "impulse_pullback",
        "timeframes": ["5m", "15m", "1h"],
        "params": {
            "impulse_atr_mult": 1.35,
            "pullback_max_bars": 4,
            "stop_atr_mult": 0.45,
            "tp_rr": 1.4,
            "max_hold_bars": 32,
        },
    },
    {
        "scenario_id": "4hrr",
        "title_fa": "4HRR",
        "description_fa": (
            "اولین کندل 4H روز NY = Range · ستاپ 5m بعد از بسته شدن Range · "
            "Breakout با Close · بازگشت و Close داخل Range · استاپ اکسترمم Breakout · TP=2R · "
            "حداکثر یک معامله باز در هر لحظه."
        ),
        "detector_type": "four_h_rr",
        "timeframes": ["5m"],
        "params": {
            "tp_rr": 2.0,
        },
    },
    {
        "scenario_id": "bjorgum",
        "title_fa": "BjorGum",
        "description_fa": (
            "Bj Bot (3Commas): کراس MA · استاپ swing±ATR×RiskM · "
            "limit=R:R×ریسک · پیش‌فرض EMA21/50 · فقط 1h."
        ),
        "detector_type": "bjorgum",
        "timeframes": ["1h"],
        "params": {
            "ma_type_1": "EMA",
            "ma_type_2": "EMA",
            "ma_length_1": 21,
            "ma_length_2": 50,
            "atr_len": 14,
            "swing_lookback": 5,
            "risk_m": 1.0,
            "tp_rr": 1.0,
            "use_limit": True,
            "long_trades": True,
            "short_trades": True,
            "max_hold_bars": 120,
        },
    },
]

SCALP_TIMEFRAMES = ("5m", "15m", "1h")
BACKTEST_TIMEFRAMES = ("5m", "15m", "1h", "4h")


def builtin_by_id(scenario_id: str) -> dict[str, Any] | None:
    for row in BUILTIN:
        if row["scenario_id"] == scenario_id:
            return row
    return None


def merge_scenario_params(stored: dict[str, Any] | None) -> dict[str, Any]:
    sid = (stored or {}).get("scenario_id")
    out: dict[str, Any] = {}
    for b in BUILTIN:
        if b["scenario_id"] == sid:
            out = dict(b["params"])
            break
    custom = (stored or {}).get("params")
    if isinstance(custom, dict):
        out.update(custom)
    return out


def parse_json_list(raw: str | list | None) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []
