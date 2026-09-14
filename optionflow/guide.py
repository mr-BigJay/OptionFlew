from __future__ import annotations

import math
from dataclasses import dataclass

from optionflow.flow_analyzer import (
    FlowAnalysis,
    top_strikes,
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


def _sl_buffer(spot: float) -> int:
    return max(int(round(spot * 0.004)), 150)


def _scenario_tilt_title(
    guidance: Guidance,
    p: MovementPath | None,
    *,
    in_range: bool,
) -> str:
    if in_range or (p and p.id == "range"):
        return "سناریوی اصلی BTC: بازار متعادل / نوسان بین دو سطح"
    if p and p.legs:
        first = p.legs[0].direction
        if first == "down":
            return "سناریوی اصلی BTC: تمایل کوتاه‌مدت نزولی"
        if first == "up":
            return "سناریوی اصلی BTC: تمایل کوتاه‌مدت صعودی"
    if guidance.bias == "bullish":
        return "سناریوی اصلی BTC: تمایل کوتاه‌مدت صعودی"
    if guidance.bias == "bearish":
        return "سناریوی اصلی BTC: تمایل کوتاه‌مدت نزولی"
    return "سناریوی اصلی BTC: بازار متعادل"


def _format_structured_scenario(
    guidance: Guidance,
    *,
    spot: float,
    support: int,
    target: int,
    in_range: bool,
) -> str:
    """گزارش کوتاه با عنوان، مسیر، شرایط ورود، SL/TP و جمع‌بندی."""
    p = guidance.path_primary
    spot_i = int(round(spot))
    spot_disp = f"{spot:,.0f}"
    lo, hi = min(support, target), max(support, target)
    buf = _sl_buffer(spot)
    mid = int(round((lo + hi) / 2))
    title = _scenario_tilt_title(guidance, p, in_range=in_range)

    def _block(
        intro1: str,
        intro2: str,
        path_line: str,
        entry: str,
        stop: int,
        goal: int,
        invalid: str,
        summary: str,
    ) -> str:
        return (
            f"{title}\n\n"
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

    if in_range or (p and p.id == "range") or (
        guidance.bias == "neutral" and (not p or p.id == "range")
    ):
        intro1 = (
            f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
            f"با توجه به داده‌های فعلی (flow آپشن)، احتمال بیشتری وجود دارد "
            f"که قیمت بین {lo:,} و {hi:,} دلار نوسان کند."
        )
        intro2 = (
            f"تا زمانی که یکی از این سطوح با قدرت شکسته نشود، "
            f"مسیر محتمل رفت‌وبرگشت در همین بازه است. مسیر احتمالی فعلی:"
        )
        path_line = f"{spot_disp} → {lo:,} ↔ {hi:,}"
        entry = (
            f"خرید فقط نزدیک {lo:,} با واکنش صعودی (بستن کندل ۱۵ دقیقه‌ای بالای این محدوده)؛ "
            f"فروش/کوتاه فقط نزدیک {hi:,} با واکنش نزولی. "
            f"سوار روند: خرید بعد از بستن بالای {hi:,}، فروش بعد از بستن زیر {lo:,}."
        )
        invalid = (
            f"ورود در میانهٔ بازه (حدود {mid:,}) بدون تأیید سطح، ریسک بالاتری دارد. "
            f"شکست تثبیتی زیر {lo:,} سناریوی خرید از کف را باطل می‌کند؛ "
            f"شکست بالای {hi:,} سناریوی فروش از سقف را باطل می‌کند."
        )
        summary = (
            f"فعلاً بازار خنثی است و احتمال نوسان بین {lo:,} و {hi:,} "
            f"بیشتر از حرکت یک‌طرفه دیده می‌شود. "
            f"واکنش در هر یک از این دو سطح مهم‌ترین نقطهٔ تصمیم خواهد بود."
        )
        return _block(
            intro1,
            intro2,
            path_line,
            entry,
            lo - buf,
            hi,
            invalid,
            summary,
        )

    if p and len(p.legs) >= 2:
        a, b = p.legs[0], p.legs[1]
        if a.direction == "down" and b.direction == "up":
            intro1 = (
                f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
                f"با توجه به داده‌های فعلی، احتمال بیشتری وجود دارد که قیمت "
                f"از همین محدوده ابتدا به سمت {a.to_level:,} دلار حرکت کند."
            )
            intro2 = (
                f"در صورت رسیدن به {a.to_level:,} و مشاهده واکنش صعودی، "
                f"احتمال برگشت قیمت به سمت {b.to_level:,} افزایش پیدا می‌کند. "
                f"بنابراین مسیر احتمالی فعلی:"
            )
            path_line = f"{spot_disp} → {a.to_level:,} → {b.to_level:,}"
            entry = (
                f"ورود خرید فقط پس از واکنش صعودی معتبر در محدوده {a.to_level:,} انجام شود. "
                f"بسته‌شدن کندل ۱۵ دقیقه‌ای بالای این محدوده و افزایش فشار خرید، "
                f"تأیید ورود محسوب می‌شود."
            )
            invalid = (
                f"اگر قیمت بدون واکنش معتبر زیر {a.to_level:,} تثبیت شود، سناریوی خرید باطل می‌شود. "
                f"همچنین تا زمانی که قیمت در میانه محدوده قرار دارد، ورود جدید ریسک بیشتری دارد."
            )
            summary = (
                f"فعلاً جهت کوتاه‌مدت کمی نزولی است و احتمال آزمایش {a.to_level:,} "
                f"بیشتر از حرکت مستقیم به سمت {b.to_level:,} است. "
                f"واکنش قیمت در {a.to_level:,} مهم‌ترین نقطه تصمیم برای ادامه حرکت خواهد بود."
            )
            return _block(
                intro1,
                intro2,
                path_line,
                entry,
                a.to_level - buf,
                b.to_level,
                invalid,
                summary,
            )

        if a.direction == "up" and b.direction == "down":
            intro1 = (
                f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
                f"با توجه به داده‌های فعلی، احتمال بیشتری وجود دارد که قیمت "
                f"ابتدا به سمت {a.to_level:,} دلار حرکت کند."
            )
            intro2 = (
                f"پس از نزدیک شدن به {a.to_level:,}، اگر فشار فروش یا برگشت دیده شود، "
                f"احتمال اصلاح به {b.to_level:,} افزایش می‌یابد. مسیر احتمالی فعلی:"
            )
            path_line = f"{spot_disp} → {a.to_level:,} → {b.to_level:,}"
            entry = (
                f"خرید از همین محدوده یا اصلاح کوتاه به {support:,} با هدف {a.to_level:,}؛ "
                f"خروج یا فروش محافظه‌کارانه نزدیک {a.to_level:,} در صورت علائم برگشت. "
                f"تأیید: بستن کندل ۱۵ دقیقه‌ای در جهت معامله."
            )
            invalid = (
                f"شکست تثبیتی زیر {support - buf:,} سناریوی صعود کوتاه‌مدت را ضعیف می‌کند. "
                f"ورود جدید در میانهٔ مسیر ({mid:,}) بدون تأیید، ریسک بیشتری دارد."
            )
            summary = (
                f"فعلاً تمایل کوتاه‌مدت به بالا دیده می‌شود، اما flow نشان می‌دهد "
                f"پس از {a.to_level:,} احتمال اصلاح به {b.to_level:,} وجود دارد. "
                f"مدیریت ریسک نزدیک هدف اول اهمیت دارد."
            )
            return _block(
                intro1,
                intro2,
                path_line,
                entry,
                support - buf,
                a.to_level,
                invalid,
                summary,
            )

    if p and len(p.legs) == 1:
        leg = p.legs[0]
        if leg.direction == "up":
            intro1 = (
                f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
                f"با توجه به داده‌های فعلی، احتمال بیشتری وجود دارد که قیمت "
                f"به سمت {leg.to_level:,} دلار حرکت کند."
            )
            intro2 = "مسیر احتمالی فعلی:"
            path_line = f"{spot_disp} → {leg.to_level:,}"
            entry = (
                f"ورود خرید روی اصلاح به ناحیه {support:,}–{mid:,} "
                f"یا پس از بستن کندل ۱۵ دقیقه‌ای بالای {target:,}. "
                f"افزایش فشار خرید در flow، تأیید ورود محسوب می‌شود."
            )
            invalid = (
                f"تثبیت زیر {support:,} بدون برگشت سریع، سناریوی صعود را باطل می‌کند. "
                f"ورود در میانهٔ مسیر بدون اصلاح، ریسک بالاتری دارد."
            )
            summary = (
                f"فعلاً جهت کوتاه‌مدت صعودی است و هدف {leg.to_level:,} "
                f"از روی خرید کال در آپشن‌ها برآورد شده است."
            )
            return _block(
                intro1,
                intro2,
                path_line,
                entry,
                support - buf,
                leg.to_level,
                invalid,
                summary,
            )

        intro1 = (
            f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
            f"با توجه به داده‌های فعلی، احتمال بیشتری وجود دارد که قیمت "
            f"به سمت {leg.to_level:,} دلار (حمایت flow) حرکت کند."
        )
        intro2 = "مسیر احتمالی فعلی:"
        path_line = f"{spot_disp} → {leg.to_level:,}"
        entry = (
            f"فروش/کوتاه فقط پس از شکست {support:,} با بستن کندل ۱۵ دقیقه‌ای زیر آن؛ "
            f"خرید فقط پس از واکنش صعودی معتبر در {leg.to_level:,} "
            f"(بستن ۱۵ دقیقه بالای سطح)."
        )
        invalid = (
            f"اگر قیمت بدون رسیدن به {leg.to_level:,} بالای {spot_i + buf:,} تثبیت شود، "
            f"سناریوی فشار نزولی ضعیف می‌شود."
        )
        summary = (
            f"فعلاً جهت کوتاه‌مدت نزولی است و آزمایش {leg.to_level:,} "
            f"محتمل‌تر از حرکت مستقیم به {target:,} دیده می‌شود."
        )
        return _block(
            intro1,
            intro2,
            path_line,
            entry,
            leg.to_level - buf,
            target,
            invalid,
            summary,
        )

    intro1 = (
        f"قیمت فعلی بیت‌کوین حدود {spot_disp} دلار است. "
        f"حمایت {lo:,} و هدف {hi:,} از flow آپشن برآورد شده است."
    )
    intro2 = "مسیر احتمالی فعلی:"
    path_line = f"{spot_disp} → {lo:,} / {hi:,}"
    entry = f"فقط نزدیک {lo:,} یا {hi:,} با تأیید کندل ۱۵ دقیقه‌ای و حجم کم."
    invalid = f"ورود در میانهٔ بازه ({mid:,}) بدون تأیید سطح توصیه نمی‌شود."
    summary = "منتظر واکنش در یکی از سطوح flow بمانید."
    return _block(intro1, intro2, path_line, entry, lo - buf, hi, invalid, summary)


def format_simple_paragraph(main: FlowAnalysis, guidance: Guidance) -> str:
    """گزارش کوتاه ساختاریافته: مسیر از قیمت فعلی، ورود، SL و هدف."""
    spot = round(main.spot, 2)
    support = guidance.support_zone
    target = guidance.target_zone
    p = guidance.path_primary
    in_range = guidance.bias == "neutral" or (p is not None and p.id == "range")
    return _format_structured_scenario(
        guidance,
        spot=spot,
        support=support,
        target=target,
        in_range=in_range,
    )
