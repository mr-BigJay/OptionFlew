from __future__ import annotations

import math
from dataclasses import dataclass

from optionflow.flow_analyzer import FlowAnalysis, top_strikes, weighted_strike_center
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
    filtered = {k: v for k, v in strikes.items() if lo <= k <= hi}
    return filtered if filtered else strikes


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

    call_target_center = weighted_strike_center(
        _filter_strikes_near(main.call_buy_by_strike, spot, 0.98, 1.12)
    )
    put_support_center = weighted_strike_center(
        _filter_strikes_near(main.put_buy_by_strike, spot, 0.88, 1.02)
    )
    if call_target_center is None:
        call_target_center = spot * 1.02
    if put_support_center is None:
        put_support_center = spot * 0.98

    target_zone = _round_zone(call_target_center)
    support_zone = _round_zone(put_support_center)

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
    if main.trade_count >= 100:
        confidence += 10
    if main.trade_count >= 300:
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


def format_simple_paragraph(main: FlowAnalysis, guidance: Guidance) -> str:
    """یک پاراگراف روند و مسیر (تک سناریو، متن کامل، بدون لیست داده)."""
    c = main.contracts
    p = guidance.path_primary
    spot = round(main.spot, 2)
    target = guidance.target_zone
    support = guidance.support_zone

    if c.buyer_call > c.buyer_put * 1.1:
        tone = (
            "فشار معاملات بیشتر سمت خرید کال است و تمایل کوتاه‌مدت صعودی دیده می‌شود"
        )
    elif c.buyer_put > c.buyer_call * 1.1:
        tone = (
            "فشار معاملات بیشتر سمت خرید پوت است و تمایل کوتاه‌مدت به سمت افت یا تست حمایت دیده می‌شود"
        )
    else:
        tone = (
            "خرید کال و پوت نزدیک به هم است؛ جهت حرکت بیشتر از روی سطوحی که معاملات روی آن‌ها متمرکز شده مشخص می‌شود"
        )

    pause_up = int(round(spot + (target - spot) * 0.42))
    pause_down = int(round(support + (spot - support) * 0.35))

    if p and len(p.legs) >= 2:
        a, b = p.legs[0], p.legs[1]
        target = a.to_level
        support = b.to_level
        pause_up = int(round(spot + (target - spot) * 0.42))
        if a.direction == "up" and b.direction == "down":
            path_text = (
                f"تک سناریوی محتمل: قیمت از محدودهٔ فعلی حدود {spot:,.2f} وارد فاز صعودی می‌شود؛ "
                f"در مسیر، نزدیک {pause_up:,} ممکن است شتاب صعود کم شود یا یک‌بار مکث کند، "
                f"سپس حرکت به سمت {target:,} ادامه پیدا کند. "
                f"از آنجا برگشت و اصلاح به محدوده {support:,} محتمل است؛ "
                f"در صورت نگه‌داشتن این ناحیه، احتمال تثبیت و آرام‌تر شدن نوسان در همان محدوده وجود دارد."
            )
        elif a.direction == "down" and b.direction == "up":
            path_text = (
                f"تک سناریوی محتمل: ابتدا قیمت به سمت {a.to_level:,} پایین می‌آید "
                f"(همان ناحیه‌ای که در معاملات پوت به‌عنوان حمایت دیده می‌شود)؛ "
                f"اگر آنجا بایستد، برگشت تدریجی به {b.to_level:,} محتمل است و "
                f"نزدیک {pause_down:,} می‌تواند محل چرخش کوتاه‌مدت باشد."
            )
        else:
            path_text = (
                f"تک سناریوی محتمل: نوسان بین {support:,} و {target:,} "
                f"با شروع از {spot:,.2f} تا شکست واضح‌تر یکی از سطوح."
            )
    elif p and len(p.legs) == 1:
        leg = p.legs[0]
        if leg.direction == "up":
            path_text = (
                f"تک سناریوی محتمل: حرکت یک‌طرفه به سمت {leg.to_level:,} "
                f"از {spot:,.2f}، با توقف احتمالی نزدیک {pause_up:,}."
            )
        else:
            path_text = (
                f"تک سناریوی محتمل: فشار به سمت {leg.to_level:,} "
                f"از {spot:,.2f}."
            )
    else:
        path_text = (
            f"تک سناریوی محتمل: نوسان در محدوده {support:,} تا {target:,} "
            f"با محور حدود {spot:,.2f}."
        )

    return (
        f"بر اساس معاملات آپشن بیت‌کوین در {main.window_label}، {tone}. "
        f"{path_text} "
        f"این جمع‌بندی یک سناریو است، نه سیگنال قطعی."
    )
