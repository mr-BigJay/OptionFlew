"""مسیر گزارش: حق‌بیمهٔ واقعی، باند سررسید، و فقط یک مقصد A تا B."""

from __future__ import annotations

import math
from datetime import datetime

from optionflow.expiry_compass import ExpiryBand, PriorCompass
from optionflow.path_v2 import PathV2

SHIFT_PCT = 0.0035


def path_quality(path: PathV2 | None) -> tuple[str, float, int]:
    """امتیاز و اطمینان از خودِ حق‌بیمه و وجود مقصد، نه از تعداد معامله."""
    if path is None or (path.bull_premium <= 0 and path.bear_premium <= 0):
        return "neutral", 0.0, 30
    ratio = path.bull_premium / max(path.bear_premium, 1e-9)
    score = round(max(-10.0, min(10.0, math.log(ratio) * 6)), 1)
    if path.side == "up":
        bias = "bullish"
    elif path.side == "down":
        bias = "bearish"
    else:
        bias = "neutral"
    if path.target is None:
        confidence = 35
    elif path.side == "pin":
        confidence = 55
    else:
        confidence = int(min(80, 48 + abs(math.log(max(ratio, 1e-9))) * 35))
    return bias, score, confidence


def headline_fa(bias: str, score: float, confidence: int) -> str:
    if bias == "bullish":
        lead = "تمایل کوتاه‌مدت به صعود"
    elif bias == "bearish":
        lead = "تمایل کوتاه‌مدت به نزول"
    else:
        lead = "بازار خنثی"
    return f"{lead} — امتیاز {score} — اطمینان {confidence}%"


def classify_level_shift(
    prior: PriorCompass | None,
    *,
    spot: float,
    band_low: int | None,
    down_mid: int | None,
    up_mid: int | None,
) -> str:
    """down/up فقط وقتی باند و سطح همان سمت هر دو جابه‌جا شده باشند."""
    if prior is None or prior.band_low is None or band_low is None or spot <= 0:
        return "unknown"
    thresh = spot * SHIFT_PCT
    band_delta = band_low - prior.band_low
    if (
        down_mid is not None
        and prior.down_zone_mid is not None
        and band_delta <= -thresh
        and down_mid - prior.down_zone_mid <= -thresh
    ):
        return "down"
    if (
        up_mid is not None
        and prior.up_zone_mid is not None
        and band_delta >= thresh
        and up_mid - prior.up_zone_mid >= thresh
    ):
        return "up"
    return "flat"


def _level(name: str, strike: int | None) -> str:
    if strike is None:
        return f"{name}: در این پنجره سطح دور از قیمت دیده نشد."
    return f"{name}: {strike:,} دلار."


def _hours_fa(hours: float) -> str:
    if hours >= 48:
        return f"{hours / 24:.1f} روز"
    return f"{hours:.1f} ساعت"


def format_path_paragraph(
    *,
    path: PathV2 | None,
    spot: float,
    window_label: str,
    bands: list[ExpiryBand],
    shift: str,
) -> str:
    spot_i = int(round(spot))
    lines = [
        "**سناریوی اصلی BTC**",
        f"قیمت فعلی: {spot_i:,} دلار. پنجرهٔ جریان: {window_label}.",
    ]
    if path is not None and (path.bull_premium > 0 or path.bear_premium > 0):
        lines.append(
            "حق‌بیمهٔ صعودی (خریدار کال + فروشندهٔ پوت) "
            f"{path.bull_premium:,.0f} دلار، حق‌بیمهٔ نزولی "
            f"(خریدار پوت + فروشندهٔ کال) {path.bear_premium:,.0f} دلار."
        )
    if bands:
        primary = bands[0]
        lines.append(
            f"**باند سررسید**\nنزدیک‌ترین سررسید {primary.expiry}، "
            f"حدود {_hours_fa(primary.hours_left)} مانده. "
            f"باند حرکت این سررسید {primary.band_low:,} تا {primary.band_high:,} است."
        )
        extra = bands[1:]
        if extra:
            bits = [
                f"{band.expiry} ({band.band_low:,} تا {band.band_high:,})"
                for band in extra
            ]
            lines.append("سررسیدهای بعد جدا مانده‌اند: " + "؛ ".join(bits) + ".")
    else:
        lines.append("**باند سررسید**\nباند نوسان ضمنی این لحظه در دسترس نبود.")

    lines.append(
        "**سطح‌ها**\n"
        + _level("سقف فروشندهٔ کال", None if path is None else path.scg)
        + " "
        + _level("آهنربای خریدار کال", None if path is None else path.bcg)
        + " "
        + _level("حمایت خریدار پوت", None if path is None else path.bps)
        + " "
        + _level("حمایت فروشندهٔ پوت", None if path is None else path.sps)
    )

    if shift == "down":
        lines.append(
            "**جابه‌جایی**\nباند و حمایت نسبت به گزارش قبل هر دو پایین‌تر رفته‌اند."
        )
    elif shift == "up":
        lines.append(
            "**جابه‌جایی**\nباند و سقف نسبت به گزارش قبل هر دو بالاتر رفته‌اند."
        )
    elif shift == "flat":
        lines.append(
            "**جابه‌جایی**\nباند و سطح نسبت به گزارش قبل با هم به یک سمت نرفته‌اند."
        )
    else:
        lines.append(
            "**جابه‌جایی**\nگزارش قبلی برای مقایسه نیست. این سطح ثبت شد."
        )

    target = None if path is None else path.target
    if target is None or path is None:
        lines.append(
            "**حرکت**\nمقصد مشخص نیست. میانگین استرایک یا درصد ثابت به‌جای مسیر گذاشته نشد."
        )
        lines.append("**جمع‌بندی**\nتا یک سمت از حق‌بیمه سنگین‌تر شود و سطحش از قیمت فاصله داشته باشد، خط A تا B رسم نمی‌شود.")
        return "\n\n".join(lines)

    if path.side == "pin":
        why = "گاما نزدیک قیمت جمع است و حق‌بیمه یک‌طرفه نیست؛ مسیر آرام به آهنرباست."
    elif path.side == "up":
        why = "حق‌بیمهٔ صعودی سنگین‌تر است؛ مقصد سقف فروشندهٔ کال است، نه میانگین استرایک."
    else:
        why = "حق‌بیمهٔ نزولی سنگین‌تر است؛ مقصد حمایت پوت است، نه دیوار کال دورتر."
    lines.append(f"**حرکت**\nاز {spot_i:,} به {target:,}.\n{why}")
    lines.append(
        f"**جمع‌بندی**\nمسیر همین یک قدم است: A در {spot_i:,} و B در {target:,}."
    )
    return "\n\n".join(lines)
