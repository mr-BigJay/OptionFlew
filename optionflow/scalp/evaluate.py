from __future__ import annotations

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def evaluate_scalp_path(
    bars: list[OhlcBar],
    hit: PatternHit,
    *,
    bar_index: int | None = None,
) -> tuple[bool | None, str]:
    """ارزیابی با اولویت استاپ قبل از TP در هر کندل."""
    meta = hit.meta or {}
    direction = meta.get("direction")
    if direction not in ("up", "down"):
        return None, "جهت معامله مشخص نیست."

    entry_px = meta.get("entry_px")
    stop_px = meta.get("stop_px")
    tp_px = meta.get("tp_px")
    if not all(isinstance(x, (int, float)) and x > 0 for x in (entry_px, stop_px, tp_px)):
        return None, "سطوح ورود/استاپ/TP ناقص است."

    entry_px = float(entry_px)
    stop_px = float(stop_px)
    tp_px = float(tp_px)

    entry_i = meta.get("entry_index")
    if not isinstance(entry_i, int):
        entry_i = bar_index if isinstance(bar_index, int) else len(bars) - 1
    entry_i = max(0, min(entry_i, len(bars) - 1))

    max_hold = meta.get("max_hold_bars")
    if not isinstance(max_hold, int) or max_hold < 1:
        max_hold = 24
    end_i = min(len(bars) - 1, entry_i + max_hold)

    exit_i: int | None = None
    exit_px: float | None = None
    reason = ""

    for i in range(entry_i + 1, end_i + 1):
        b = bars[i]
        if direction == "up":
            if b.low <= stop_px:
                exit_i, exit_px, reason = i, stop_px, "برخورد استاپ"
                break
            if b.high >= tp_px:
                exit_i, exit_px, reason = i, tp_px, "رسیدن به TP"
                break
        else:
            if b.high >= stop_px:
                exit_i, exit_px, reason = i, stop_px, "برخورد استاپ"
                break
            if b.low <= tp_px:
                exit_i, exit_px, reason = i, tp_px, "رسیدن به TP"
                break

    if exit_i is None:
        exit_i = end_i
        exit_px = float(bars[exit_i].close)
        reason = "پایان مهلت نگه‌داری"

    if direction == "up":
        pct = (exit_px - entry_px) / entry_px
        win = reason == "رسیدن به TP"
    else:
        pct = (entry_px - exit_px) / entry_px
        win = reason == "رسیدن به TP"

    meta["entry_index"] = entry_i
    meta["entry_px"] = entry_px
    meta["exit_index"] = exit_i
    meta["exit_px"] = exit_px
    meta["path_pct"] = pct
    meta["exit_reason"] = reason
    note = (
        f"{reason} · {pct * 100:+.2f}٪ "
        f"({entry_px:,.0f} → {exit_px:,.0f})"
    )
    if reason == "برخورد استاپ":
        return False, note
    if reason == "رسیدن به TP":
        return True, note
    return False, note
