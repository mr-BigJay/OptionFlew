from __future__ import annotations

import math
from dataclasses import dataclass

from optionflow.flow_analyzer import (
    FlowAnalysis,
    top_strikes,
    weighted_strike_center_near_spot,
)
from optionflow.path_scenario import (
    MovementPath,
    effective_movement_path,
    infer_movement_paths,
    format_path_section,
)


@dataclass
class Guidance:
    bias: str
    score: float
    confidence_pct: int
    support_zone: int
    target_zone: int
    headline_fa: str
    sections_fa: list[str]
    metrics: dict[str, float]
    path_primary: MovementPath | None = None
    path_alternate: MovementPath | None = None


def _round_zone(price: float) -> int:
    """Keep strike-derived levels at full dollar precision (no 500-step rounding)."""
    return int(round(price))


def _dominance_ratio(a: float, b: float) -> float:
    if b <= 0:
        return a if a > 0 else 1.0
    return a / b


def _filter_strikes_near(
    strikes: dict[float, float],
    spot: float,
    low_pct: float,
    high_pct: float,
) -> dict[float, float]:
    lo, hi = spot * low_pct, spot * high_pct
    return {k: v for k, v in strikes.items() if lo <= k <= hi}


def build_guidance(
    main: FlowAnalysis,
    *,
    pre_event: FlowAnalysis | None = None,
) -> Guidance:
    c = main.contracts
    e = main.effective_usd

    bull_flow = c.buyer_call + c.seller_put
    bear_flow = c.buyer_put + c.seller_call
    ratio = _dominance_ratio(bull_flow, bear_flow)

    if ratio >= 1.25:
        bias = "bullish"
    elif ratio <= 0.8:
        bias = "bearish"
    else:
        bias = "neutral"

    spot = main.spot
    wh = main.window_hours

    if wh >= 20:
        call_hi, put_lo = 1.12, 0.88
        target_cap, support_floor = 1.12, 0.88
        decay = 0.04
    elif wh >= 4:
        call_hi, put_lo = 1.10, 0.90
        target_cap, support_floor = 1.085, 0.915
        decay = 0.035
    else:
        call_hi, put_lo = 1.08, 0.85
        target_cap, support_floor = 1.065, 0.935
        decay = 0.025

    call_strikes = _filter_strikes_near(main.call_buy_by_strike, spot, 1.0, call_hi)
    put_strikes = _filter_strikes_near(main.put_buy_by_strike, spot, put_lo, 1.0)

    call_target_center = weighted_strike_center_near_spot(
        call_strikes, spot, half_range_pct=decay
    )
    put_support_center = weighted_strike_center_near_spot(
        put_strikes, spot, half_range_pct=decay
    )

    if call_target_center is None:
        call_target_center = spot * 1.015
    if put_support_center is None:
        put_support_center = spot * 0.985

    target_zone = _round_zone(min(call_target_center, spot * target_cap))
    support_zone = _round_zone(max(put_support_center, spot * support_floor))
    if target_zone <= int(round(spot)):
        target_zone = int(round(spot * 1.01))
    if support_zone >= int(round(spot)):
        support_zone = int(round(spot * 0.99))

    path_primary, path_alternate = infer_movement_paths(
        main,
        support_zone=support_zone,
        target_zone=target_zone,
        spot=spot,
    )

    # Score: log-scaled flow imbalance + call-buy concentration
    bc_share = c.buyer_call / max(c.total, 1)
    score = round(min(20.0, max(-20.0, (math.log(ratio) * 8) + (bc_share - 0.25) * 20)), 1)

    confidence = 50
    t1 = int(80 * wh)
    t2 = int(220 * wh)
    if main.trade_count >= t1:
        confidence += 10
    if main.trade_count >= t2:
        confidence += 10
    if abs(score) >= 5:
        confidence += 10
    if pre_event is not None and pre_event.trade_count >= 30:
        confidence += 5
    confidence = min(85, confidence)

    if bias == "bullish":
        headline = f"ادامهٔ تمایل صعودی — امتیاز {score} — اطمینان {confidence}%"
    elif bias == "bearish":
        headline = f"تمایل محافظتی/نزولی در معاملات — امتیاز {score} — اطمینان {confidence}%"
    else:
        headline = f"بازار خنثی — امتیاز {score} — اطمینان {confidence}%"

    top_calls = top_strikes(main.call_buy_by_strike, 3)
    top_puts = top_strikes(main.put_buy_by_strike, 3)

    sections: list[str] = []

    sections.append(
        f"**قیمت لحظه‌ای (شاخص Deribit):** حدود {spot:,.0f} USDT — "
        f"بر اساس {main.trade_count:,} معاملهٔ آپشن در {main.window_label}."
    )

    sections.append(
        "**جمع‌بندی order flow (قرارداد):**\n"
        f"- خریدار کال: {c.buyer_call:,.1f} (Effective ~{e.buyer_call:,.0f} USD)\n"
        f"- خریدار پوت: {c.buyer_put:,.1f} (Effective ~{e.buyer_put:,.0f} USD)\n"
        f"- فروشنده کال: {c.seller_call:,.1f}\n"
        f"- فروشنده پوت: {c.seller_put:,.1f}"
    )

    if c.buyer_call >= max(c.buyer_put, c.seller_call, c.seller_put) * 1.15:
        sections.append(
            "در ریز معاملات **غلبهٔ خریداران کال** دیده می‌شود؛ "
            f"مرکز وزنی strikeهای خریداری‌شده حدود **{target_zone:,}** است "
            + (
                f"(بیشترین حجم روی {', '.join(f'{int(k):,}' for k, _ in top_calls)})."
                if top_calls
                else "."
            )
        )
    elif c.buyer_put >= max(c.buyer_call, c.seller_call) * 1.15:
        sections.append(
            "فشار **خرید پوت (محافظت/شرط بندی نزول)** غالب است؛ "
            f"تمرکز strikeها نزدیک **{support_zone:,}** "
            + (
                f"({', '.join(f'{int(k):,}' for k, _ in top_puts)})."
                if top_puts
                else "."
            )
        )

    sections.append(format_path_section(path_primary, path_alternate, main))

    sections.append(
        f"**سناریوی حمایت (از flow پوت):** واکنش یا «حمله» احتمالی به ناحیهٔ **{support_zone:,}** "
        f"— اگر این سطح در spot نگه داشته شود، برگشت به بالا با flow فعلی هم‌راستاتر است."
    )
    sections.append(
        f"**سناریوی هدف (از flow کال):** در صورت حفظ momentum، ناحیهٔ **{target_zone:,}** "
        "به‌عنوان مقاومت/هدف کوتاه‌مدت options محاسبه شده است."
    )

    if pre_event is not None:
        pe = pre_event.contracts
        sections.append(
            f"**پنجرهٔ قبل از رویداد ({pre_event.window_label}):** "
            f"خرید کال {pe.buyer_call:,.1f} vs خرید پوت {pe.buyer_put:,.1f}. "
            + (
                "قبل از خبر تمایل صعودی در آپشن‌ها قوی‌تر بود."
                if pe.buyer_call > pe.buyer_put * 1.2
                else (
                    "قبل از خبر hedging پوت غالب بود — احتمال volatility دوطرفه."
                    if pe.buyer_put > pe.buyer_call * 1.2
                    else "قبل از خبر flow متعادل بود."
                )
            )
        )

    sections.append(
        "**راهنمای عمل (نه سیگنال قطعی):** "
        + (
            f"ترجیحاً pullback به {support_zone:,} را برای entry محافظه‌کارانه watch کنید؛ "
            f"هدف partial روی {target_zone:,}؛ stop زیر {support_zone - 1000:,}."
            if bias == "bullish"
            else (
                f"تا زمانی که {support_zone:,} نشکند short aggressive نگیرید؛ "
                f"شکست آن می‌تواند acceleration نزولی بیاورد."
                if bias == "bearish"
                else "صبر برای break واضح flow یا سطح؛ range بین support و target محتمل است."
            )
        )
    )

    return Guidance(
        bias=bias,
        score=score,
        confidence_pct=confidence,
        support_zone=support_zone,
        target_zone=target_zone,
        headline_fa=headline,
        sections_fa=sections,
        metrics={
            "bull_flow": bull_flow,
            "bear_flow": bear_flow,
            "ratio": ratio,
            "buyer_call": c.buyer_call,
        },
        path_primary=path_primary,
        path_alternate=path_alternate,
    )


def format_report(main: FlowAnalysis, guidance: Guidance) -> str:
    lines = [
        "═" * 52,
        "  OptionFlow Guide — BTC (Deribit Options)",
        "═" * 52,
        "",
        guidance.headline_fa,
        "",
    ]
    for block in guidance.sections_fa:
        lines.append(block)
        lines.append("")
    lines.append("—" * 52)
    lines.append(
        "Disclaimer: خروجی آماری از flow عمومی است؛ جایگزین تحلیل انسانی یا dankbit نیست."
    )
    return "\n".join(lines)


def _sl_buffer(spot: float) -> int:
    return max(int(round(spot * 0.004)), 150)



def _scenario_tilt_title(p: MovementPath | None) -> str:
    if not p or not p.legs:
        return "سناریوی اصلی BTC"
    first = p.legs[0].direction
    if first == "down":
        return "سناریوی اصلی BTC: تمایل کوتاه‌مدت نزولی"
    if first == "up":
        return "سناریوی اصلی BTC: تمایل کوتاه‌مدت صعودی"
    return "سناریوی اصلی BTC"


def _direction_verdict(first_leg) -> str:
    lvl = first_leg.to_level
    if first_leg.direction == "up":
        return f"**از قیمت فعلی، احتمال حرکت صعودی به سمت {lvl:,} بیشتر است.**"
    return f"**از قیمت فعلی، احتمال حرکت نزولی به سمت {lvl:,} بیشتر است.**"


def _path_arrow(spot_disp: str, legs: tuple) -> str:
    parts = [spot_disp]
    for leg in legs:
        parts.append(f"{leg.to_level:,}")
    return " → ".join(parts)


def _format_structured_scenario(
    main: FlowAnalysis,
    guidance: Guidance,
    *,
    spot: float,
    support: int,
    target: int,
) -> str:
    """گزارش کوتاه: ابتدا جهت اول از spot، سپس مسیر، ورود، SL/TP."""
    p = effective_movement_path(
        main,
        support_zone=support,
        target_zone=target,
        spot=spot,
        primary=guidance.path_primary,
        alternate=guidance.path_alternate,
    )
    legs = p.legs
    if not legs:
        return "دادهٔ کافی برای تعیین جهت اول از قیمت فعلی در دسترس نیست."

    first = legs[0]
    second = legs[1] if len(legs) > 1 else None
    spot_disp = f"{spot:,.0f}"
    buf = _sl_buffer(spot)
    mid = int(round((min(support, target) + max(support, target)) / 2))
    title = _scenario_tilt_title(p)
    verdict = _direction_verdict(first)
    path_line = _path_arrow(spot_disp, legs)

    intro1 = f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است."
    if second:
        intro2 = (
            f"پس از رسیدن به {first.to_level:,}، مسیر بعدی با احتمال بیشتر به سمت "
            f"{second.to_level:,} ({'صعود' if second.direction == 'up' else 'نزول'}) دیده می‌شود. "
            f"مسیر احتمالی:"
        )
    else:
        intro2 = "مسیر احتمالی کوتاه‌مدت از همین نقطه:"

    if first.direction == "down" and second and second.direction == "up":
        entry = (
            f"ورود خرید فقط پس از واکنش صعودی معتبر در {first.to_level:,}. "
            f"بستن کندل ۱۵ دقیقه‌ای بالای این محدوده تأیید ورود است."
        )
        stop = first.to_level - buf
        goal = second.to_level
        invalid = (
            f"تثبیت زیر {first.to_level:,} بدون واکنش، سناریوی برگشت را باطل می‌کند. "
            f"ورود در میانهٔ مسیر ({mid:,}) بدون تأیید سطح ریسک بالاتری دارد."
        )
        summary = (
            f"جهت اول از {spot_disp} نزولی به {first.to_level:,} است؛ "
            f"واکنش در آنجا تعیین‌کنندهٔ حرکت به {second.to_level:,} خواهد بود."
        )
    elif first.direction == "up" and second and second.direction == "down":
        entry = (
            f"خرید به سمت {first.to_level:,}؛ خروج یا فروش محافظه‌کارانه نزدیک "
            f"{first.to_level:,} در صورت علائم برگشت به {second.to_level:,}."
        )
        stop = support - buf
        goal = first.to_level
        invalid = (
            f"شکست زیر {support - buf:,} تمایل صعودی اول را ضعیف می‌کند. "
            f"ورود در {mid:,} بدون تأیید توصیه نمی‌شود."
        )
        summary = (
            f"جهت اول صعودی به {first.to_level:,} است؛ "
            f"پس از آن flow اصلاح به {second.to_level:,} را ممکن می‌داند."
        )
    elif first.direction == "up":
        entry = (
            f"ورود خرید روی اصلاح یا پس از بستن ۱۵ دقیقه بالای {support:,} "
            f"با هدف {first.to_level:,}."
        )
        stop = support - buf
        goal = first.to_level
        invalid = f"تثبیت زیر {support:,} سناریوی صعود اول را باطل می‌کند."
        summary = f"از همین لحظه، حرکت اول به سمت {first.to_level:,} محتمل‌تر برآورد شده است."
    else:
        entry = (
            f"فروش/کوتاه فقط پس از تأیید نزول (۱۵ دقیقه زیر {support:,})؛ "
            f"خرید فقط بعد از واکنش در {first.to_level:,}."
        )
        stop = first.to_level - buf
        goal = second.to_level if second else target
        invalid = (
            f"تثبیت بالای {int(round(spot)) + buf:,} قبل از رسیدن به {first.to_level:,} "
            f"فشار نزولی اول را ضعیف می‌کند."
        )
        summary = f"از همین لحظه، حرکت اول به سمت {first.to_level:,} محتمل‌تر برآورد شده است."

    return (
        f"{title}\n\n"
        f"{verdict}\n\n"
        f"{intro1}\n\n"
        f"{intro2}\n\n"
        f"{path_line}\n\n"
        f"شرایط ورود:\n"
        f"{entry}\n\n"
        f"حد ضرر: {stop:,} دلار\n"
        f"هدف: {goal:,} دلار\n\n"
        f"{invalid}\n\n"
        f"جمع‌بندی:\n"
        f"{summary}"
    )


def format_simple_paragraph(main: FlowAnalysis, guidance: Guidance) -> str:
    """گزارش کوتاه: جهت اول از spot، مسیر، ورود، SL و هدف."""
    spot = round(main.spot, 2)
    return _format_structured_scenario(
        main,
        guidance,
        spot=spot,
        support=guidance.support_zone,
        target=guidance.target_zone,
    )
