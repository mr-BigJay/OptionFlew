"""ربات نبض‌بورس — جدا از استراتژی‌های scalp."""

from optionflow.nabzbours.strategy import (
    DEFAULT_CONFIG,
    detect_nabzbours,
    evaluate_entry,
    merge_config,
    pairs_for_engine,
    resample_minutes,
    scan_backtest,
    summarize_trades,
)

SCENARIO = {
    "scenario_id": "nabzbours",
    "title_fa": "نبض‌بورس",
    "description_fa": (
        "RSI + MACD + VWAP + EMA · جهت روی ۱۵m · ورود ۵m · "
        "خروج با هشدار RSI و تأیید MACD (۳m اگر کش باشد). مستقل از بقیه."
    ),
    "detector_type": "nabzbours",
    "timeframes": ["5m"],
    "params": dict(DEFAULT_CONFIG),
}

__all__ = [
    "SCENARIO",
    "DEFAULT_CONFIG",
    "detect_nabzbours",
    "evaluate_entry",
    "merge_config",
    "pairs_for_engine",
    "resample_minutes",
    "scan_backtest",
    "summarize_trades",
]
