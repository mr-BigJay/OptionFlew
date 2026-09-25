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
    {
        "scenario_id": "spline",
        "title_fa": "Spline",
        "description_fa": (
            "LuxAlgo Spline Quantile Channel · رگرسیون spline روی close · "
            "باند ۵٪/۵۰٪/۹۵٪ · ورود از باند پایین/بالا وقتی شیب میانه هم‌جهت است · "
            "TP پیش‌فرض روی میانه کانال."
        ),
        "detector_type": "spline",
        "timeframes": ["15m", "1h"],
        "params": {
            "lookback": 100,
            "knots": 3,
            "irls_iters": 50,
            "forecast_bars": 20,
            "upper_q": 0.95,
            "mid_q": 0.5,
            "lower_q": 0.05,
            "atr_len": 14,
            "stop_atr_mult": 0.5,
            "touch_buffer_pct": 0.05,
            "tp_target": "mid",
            "tp_rr": 1.5,
            "long_trades": True,
            "short_trades": True,
            "max_hold_bars": 48,
        },
    },
    {
        "scenario_id": "nabzbours",
        "title_fa": "نبض‌بورس",
        "description_fa": (
            "RSI + MACD + VWAP + EMA · جهت روی ۱۵m · ورود ۵m · "
            "خروج با هشدار RSI و تأیید MACD (۳m اگر کش باشد). مستقل از بقیه."
        ),
        "detector_type": "nabzbours",
        "timeframes": ["5m"],
        "params": {
            "higher_timeframe": "15m",
            "entry_timeframe": "5m",
            "exit_timeframe": "3m",
            "require_higher_tf": True,
            "ema_length": 50,
            "rsi_period": 14,
            "rsi_slope_bars": 2,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "use_vwap": True,
            "use_ema": True,
            "use_rsi": True,
            "use_macd": True,
            "use_divergence": True,
            "score_vwap": 1,
            "score_ema": 1,
            "score_rsi": 1,
            "score_macd": 1,
            "score_divergence": 1,
            "min_score": 4,
            "pivot_left": 5,
            "pivot_right": 5,
            "atr_len": 14,
            "stop_atr_mult": 1.0,
            "tp_rr": 1.5,
            "max_hold_bars": 48,
            "long_trades": True,
            "short_trades": True,
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
