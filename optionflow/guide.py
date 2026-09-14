from __future__ import annotations

import math
from dataclasses import dataclass

from optionflow.flow_analyzer import (
    FlowAnalysis,
    top_strikes,
    top_strikes_near_spot,
    weighted_strike_center_near_spot,
)
from optionflow.path_scenario import MovementPath, infer_movement_paths, format_path_section


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


def _window_phrase(main: FlowAnalysis) -> str:
    if main.window_hours >= 20:
        return "در بازهٔ گزارش روزانه"
    if main.window_hours >= 4:
        return "در چند ساعت اخیر"
    return "در ساعات اخیر"


def _near_spot_strike_hint(main: FlowAnalysis, spot: float) -> str:
    """Only strikes close to spot — avoids 58k/170k style outliers in copy."""
    wh = main.window_hours
    put_hi = 1.02 if wh >= 20 else 1.01
    put_lo = 0.88 if wh >= 20 else 0.90
    call_lo = 0.98 if wh >= 20 else 0.99
    call_hi = 1.15 if wh >= 20 else 1.12
    top_p = top_strikes_near_spot(
        main.put_buy_by_strike, spot, 2, pct_lo=put_lo, pct_hi=put_hi
    )
    top_c = top_strikes_near_spot(
        main.call_buy_by_strike, spot, 2, pct_lo=call_lo, pct_hi=call_hi
    )
    bits: list[str] = []
    if top_p:
        bits.append("پوشش ریزش پرحجم نزدیک " + " و ".join(f"{int(k):,}" for k, _ in top_p))
    if top_c:
        bits.append("شرط رشد پرحجم نزدیک " + " و ".join(f"{int(k):,}" for k, _ in top_c))
    if not bits:
        return ""
    return " (" + "؛ ".join(bits) + ")"


def _single_scenario(
    main: FlowAnalysis,
    guidance: Guidance,
    *,
    spot: float,
    support: int,
    target: int,
    in_range: bool,
) -> str:
    p = guidance.path_primary
    lo, hi = min(support, target), max(support, target)
    pause_up = int(round(spot + (target - spot) * 0.42))
    pause_down = int(round(support + (spot - support) * 0.35))
    spot_s = f"{spot:,.0f}"

    if guidance.bias == "bullish":
        mood = "تمایل کوتاه‌مدت به بالا"
    elif guidance.bias == "bearish":
        mood = "تمایل کوتاه‌مدت به پایین"
    else:
        mood = "بازار متعادل"

    if in_range or (p and p.id == "range") or guidance.bias == "neutral":
        return (
            f"تک سناریو ({mood}): قیمت حدود {spot_s} دلار احتمالاً بین "
            f"{lo:,} (حمایت) و {hi:,} (هدف) نوسان می‌کند؛ "
            f"عجله برای خرید/فروش سنگین پرریسک است. "
            f"مسیر: {spot_s} → رفت‌وبرگشت در همین بازه → "
            f"روند واضح بعد از بستن بالای {hi:,} (صعود) یا پایین {lo:,} (ریزش)."
        )

    if p and len(p.legs) == 1:
        leg = p.legs[0]
        if leg.direction == "up":
            return (
                f"تک سناریو ({mood}): فشار به سمت بالا؛ "
                f"مسیر {spot_s} → مکث احتمالی {pause_up:,} → هدف {leg.to_level:,}. "
                f"ورود با حد ضرر زیر {support:,} یا بعد از عبور {target:,} منطقی‌تر است."
            )
        return (
            f"تک سناریو ({mood}): فشار به سمت پایین؛ "
            f"مسیر {spot_s} → حمایت {leg.to_level:,}. "
            f"منتظر واکنش در {support:,} بمانید."
        )

    if p and len(p.legs) >= 2:
        a, b = p.legs[0], p.legs[1]
        if a.direction == "up" and b.direction == "down":
            return (
                f"تک سناریو ({mood}): "
                f"مسیر {spot_s} → صعود تا {a.to_level:,} (مکث ~{pause_up:,}) "
                f"→ اصلاح به {b.to_level:,}."
            )
        if a.direction == "down" and b.direction == "up":
            return (
                f"تک سناریو ({mood}): "
                f"مسیر {spot_s} → افت تا {a.to_level:,} → "
                f"برگشت به {b.to_level:,} (چرخش ~{pause_down:,})."
            )

    return (
        f"تک سناریو ({mood}): نوسان بین {lo:,} و {hi:,} حول {spot_s}."
    )


def format_simple_paragraph(main: FlowAnalysis, guidance: Guidance) -> str:
    """پاراگراف کوتاه: قیمت، سطوح، یک تک‌سناریo با مسیر."""
    spot = round(main.spot, 2)
    support = guidance.support_zone
    target = guidance.target_zone
    p = guidance.path_primary
    in_range = guidance.bias == "neutral" or (p is not None and p.id == "range")

    head = (
        f"{_window_phrase(main)}، {main.trade_count:,} معاملهٔ آپشن بیت‌کوین بررسی شد؛ "
        f"قیمت حدود {spot:,.2f} دلار. "
        f"حمایت احتمالی {support:,} · هدف {target:,}"
        f"{_near_spot_strike_hint(main, spot)}. "
    )
    body = _single_scenario(
        main,
        guidance,
        spot=spot,
        support=support,
        target=target,
        in_range=in_range,
    )
    return head + body
