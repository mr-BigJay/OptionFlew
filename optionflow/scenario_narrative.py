from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from optionflow.flow_analyzer import FlowAnalysis, top_strikes_near_spot
from optionflow.path_scenario import MovementPath, effective_movement_path


def _sl_buffer(spot: float) -> int:
    return max(int(round(spot * 0.004)), 150)


@dataclass
class _LegPlan:
    b: int
    c: int
    first_dir: str
    second_dir: str


def _normalize_bc(
    path: MovementPath,
    *,
    support: int,
    target: int,
) -> _LegPlan:
    legs = path.legs
    if len(legs) >= 2:
        return _LegPlan(
            b=legs[0].to_level,
            c=legs[1].to_level,
            first_dir=legs[0].direction,
            second_dir=legs[1].direction,
        )
    leg = legs[0]
    if leg.direction == "down":
        return _LegPlan(b=leg.to_level, c=target, first_dir="down", second_dir="up")
    return _LegPlan(b=leg.to_level, c=support, first_dir="up", second_dir="down")


def _title_label(bias: str, first_dir: str) -> str:
    if bias == "bullish":
        return "صعودی" if first_dir == "up" else "خنثی متمایل به نزول"
    if bias == "bearish":
        return "نزولی" if first_dir == "down" else "خنثی متمایل به صعود"
    if first_dir == "down":
        return "خنثی متمایل به نزول"
    return "خنثی متمایل به صعود"


def _flow_ratio(main: FlowAnalysis) -> float:
    c = main.contracts
    bull = c.buyer_call + c.seller_put
    bear = c.buyer_put + c.seller_call
    return bull / max(bear, 1e-9)


def _pick_phrases(
    main: FlowAnalysis,
    *,
    bias: str,
    support: int,
    target: int,
    plan: _LegPlan,
    ctx: Any | None,
) -> dict[str, str]:
    """استدلال علّی؛ فقط سیگنال‌های مؤثر."""
    c = main.contracts
    ratio = _flow_ratio(main)
    spot = main.spot
    b, c_level = plan.b, plan.c

    why_bits: list[str] = []
    leg1_bits: list[str] = []
    react_bits: list[str] = []
    leg2_bits: list[str] = []

    # --- Options flow (همیشه در دسترس) ---
    if plan.first_dir == "down":
        if c.buyer_put >= c.buyer_call * 1.05:
            why_bits.append(
                "غلبهٔ خرید پوت در آپشن Deribit نشان می‌دهد معامله‌گران برای افت کوتاه‌مدت hedge گرفته‌اند"
            )
        if ratio < 1.0:
            why_bits.append(
                "ترکیب flow (کال در برابر پوت) هنوز به نفع حرکت اول به پایین متمایل است"
            )
        top_puts = top_strikes_near_spot(main.put_buy_by_strike, spot, 2, pct_lo=0.85, pct_hi=1.02)
        if top_puts:
            strikes_s = " و ".join(f"{int(k):,}" for k, _ in top_puts)
            leg1_bits.append(
                f"تمرکز حجم خرید پوت نزدیک strikeهای {strikes_s} مسیر را به سمت جمع‌آوری نقدینگی "
                f"در حدود {b:,} هدایت می‌کند"
            )
        else:
            leg1_bits.append(
                f"مرکز وزنی flow پوت حمایت flow را نزدیک {b:,} نشان می‌دهد؛ "
                f"حرکت اول برای آزمایش همان محدوده منطقی است"
            )
        top_calls = top_strikes_near_spot(main.call_buy_by_strike, spot, 2, pct_lo=1.0, pct_hi=1.12)
        if top_calls and c.buyer_call >= c.seller_call * 0.7:
            react_bits.append(
                "هم‌زمان خرید کال در strikeهای بالاتر هنوز برقرار است؛ "
                f"اگر فروشندگان در {b:,} خسته شوند، پایان دفاع محتمل‌تر می‌شود"
            )
        react_bits.append(
            f"ناحیهٔ {b:,} همان «حمایت flow» برآوردشده از پوت است؛ "
            f"احتمال واکنش (برگشت یا مکث) در آنجا از روی همین تمرکز strike بالاست"
        )
        if c_level > b:
            leg2_bits.append(
                f"در صورت تأیید واکنش صعودی در {b:,}، هدف flow کال (حدود {c_level:,}) "
                f"به‌عنوان مقصد بعدی هم‌راستا با خرید کال باقی می‌ماند"
            )
    else:
        if c.buyer_call >= c.buyer_put * 1.05:
            why_bits.append(
                "خرید کال غالب در flow آپشن تمایل کوتاه‌مدت به بالا را تقویت می‌کند"
            )
        if ratio >= 1.0:
            why_bits.append(
                "نسبت flow صعودی/نزولی به نفع حرکت اول به سمت بالا متمایل است"
            )
        top_calls = top_strikes_near_spot(main.call_buy_by_strike, spot, 2, pct_lo=1.0, pct_hi=1.12)
        if top_calls:
            strikes_s = " و ".join(f"{int(k):,}" for k, _ in top_calls)
            leg1_bits.append(
                f"تمرکز خرید کال روی {strikes_s} مسیر را به سمت هدف flow "
                f"نزدیک {b:,} می‌کشد"
            )
        else:
            leg1_bits.append(
                f"مرکز وزنی strikeهای کال خریداری‌شده حدود {b:,} است؛ "
                f"حرکت اول برای نزدیک شدن به همان محدوده برآورد می‌شود"
            )
        react_bits.append(
            f"در {b:,} ممکن است فروش کال یا سودگیری کوتاه‌مدت ظاهر شود؛ "
            f"flow همین سطح را به‌عنوان هدف/مقاومت کوتاه‌مدت نشان داده است"
        )
        if c_level < b:
            leg2_bits.append(
                f"پس از واکنش در {b:,}، برگشت به ناحیهٔ {c_level:,} (حمایت flow پوت) "
                f"در سناریوی اصلاح کوتاه‌مدت قابل انتظار است"
            )
        elif c_level > b:
            leg2_bits.append(
                f"اگر {b:,} با حجم عبور شود، مقصد بعدی {c_level:,} "
                f"با هدف flow هم‌خوان است"
            )

    # --- Enriched (فقط اگر به استدلال اضافه کند) ---
    if ctx is not None:
        taker = getattr(ctx, "taker_buy_sell_ratio", None)
        oi_ch = getattr(ctx, "oi_change_pct_1h", None)
        depth = getattr(ctx, "depth_imbalance_pct", None)
        funding = getattr(ctx, "funding_rate", None)
        pcoi = getattr(ctx, "put_call_oi", None)
        max_pain = getattr(ctx, "max_pain", None)
        gamma_s = getattr(ctx, "gamma_support", None)
        gamma_r = getattr(ctx, "gamma_resistance", None)
        struct = getattr(ctx, "structure_notes", None) or []

        if plan.first_dir == "down" and taker is not None and taker < 0.92:
            why_bits.append(
                f"در futures، فشار taker فروش (نسبت {taker:.2f}) نشان می‌دهد "
                f"ورود aggressive خرید در spot/futures فعلاً محدود است"
            )
        if plan.first_dir == "up" and taker is not None and taker > 1.08:
            why_bits.append(
                f"خرید taker قوی‌تر (نسبت {taker:.2f}) حرکت اول به بالا را حمایت می‌کند"
            )
        if oi_ch is not None and oi_ch < -0.15 and plan.first_dir == "down":
            why_bits.append(
                f"کاهش جزئی OI آتی ({oi_ch:+.1f}٪ در ۱س) با ضعف موقت longها "
                f"هم‌خوان است با افت اولیه قبل از واکنش"
            )
        if depth is not None:
            if plan.first_dir == "down" and depth < -3:
                leg1_bits.append(
                    "عرضهٔ غالب در دفتر سفارش spot می‌تواند سرعت رسیدن به B را بیشتر کند"
                )
            elif plan.first_dir == "up" and depth > 3:
                leg1_bits.append(
                    "تقاضای نسبی در order book کوتاه‌مدت حرکت به B را تقویت می‌کند"
                )
        if funding is not None and abs(funding) > 0.0001:
            fr = funding * 100
            if funding > 0.01 and plan.first_dir == "down":
                why_bits.append(
                    f"فاندینگ مثبت ({fr:.3f}٪) نشان می‌دهد longهای اهرمی شلوغ‌اند؛ "
                    f"اصلاح کوتاه برای شکار نقدینگی پایین‌تر محتمل‌تر است"
                )
        if pcoi is not None and pcoi > 1.15 and plan.first_dir == "down":
            react_bits.append(
                f"Put/Call OI بالاتر ({pcoi:.2f}) یعنی زیرساخت hedging هنوز سنگین است؛ "
                f"واکنش در B اگر باشد احتمالاً محافظه‌کارانه خواهد بود"
            )
        if max_pain and abs(max_pain - c_level) / max(spot, 1) < 0.04:
            leg2_bits.append(
                f"max pain آپشن نزدیک {max_pain:,} با مقصد C هم‌راستاست و "
                f"می‌تواند magnet قیمت پس از واکنش در B باشد"
            )
        if plan.first_dir == "down" and gamma_s and abs(gamma_s - b) / max(spot, 1) < 0.02:
            react_bits.append(
                f"تمرکز gamma حمایتی نزدیک {gamma_s:,} احتمال مکث یا برگشت در B را بیشتر می‌کند"
            )
        if plan.first_dir == "up" and gamma_r and abs(gamma_r - b) / max(spot, 1) < 0.02:
            react_bits.append(
                f"تمرکز gamma مقاومتی نزدیک {gamma_r:,} توضیح‌دهندهٔ واکنش احتمالی در B است"
            )
        for note in struct[:1]:
            if plan.first_dir == "down" and ("PDL" in note or "sweep" in note or "کف" in note):
                leg1_bits.append(note.rstrip(".") + "؛ این با حرکت اول به B هم‌جهت است")
            elif plan.first_dir == "up" and ("PDH" in note or "premium" in note):
                react_bits.append(note.rstrip(".") + "؛ در B احتمال اصلاح بیشتر دیده می‌شود")

    def _join(parts: list[str], fallback: str) -> str:
        parts = [p for p in parts if p][:3]
        if not parts:
            return fallback
        return " ".join(parts)

    return {
        "why": _join(
            why_bits,
            "ترکیب flow آپشن در این پنجره جهت اول را به سمت B سوق می‌دهد.",
        ),
        "leg1": _join(
            leg1_bits,
            f"از قیمت فعلی، جذب نقدینگی و strikeهای فعال flow مسیر را به {b:,} می‌کشد.",
        ),
        "react": _join(
            react_bits,
            f"در {b:,} تمرکز strike و نقدینگی flow احتمال واکنش قیمت را بالا می‌برد.",
        ),
        "leg2": _join(
            leg2_bits,
            f"پس از تأیید واکنش در B، حرکت به {c_level:,} با هدف/حمایت flow هم‌خوان است.",
        ),
    }


def format_narrative_scenario(
    main: FlowAnalysis,
    *,
    bias: str,
    spot: float,
    support: int,
    target: int,
    path_primary: MovementPath | None,
    path_alternate: MovementPath | None,
    ctx: Any | None = None,
) -> str:
    path = effective_movement_path(
        main,
        support_zone=support,
        target_zone=target,
        spot=spot,
        primary=path_primary,
        alternate=path_alternate,
    )
    if not path.legs:
        return "دادهٔ کافی برای سناریوی اصلی از قیمت فعلی در دسترس نیست."

    plan = _normalize_bc(path, support=support, target=target)
    b, c = plan.b, plan.c
    spot_disp = f"{spot:,.0f}"
    buf = _sl_buffer(spot)
    label = _title_label(bias, plan.first_dir)
    phrases = _pick_phrases(
        main, bias=bias, support=support, target=target, plan=plan, ctx=ctx
    )

    if plan.first_dir == "down" and plan.second_dir == "up":
        entry = (
            f"ورود long فقط **بعد از B** و با تأیید: بستن کندل ۱۵ دقیقه‌ای بالای {b:,} "
            f"همراه با کاهش فشار taker فروش یا برگشت flow کال؛ رسیدن به B به‌تنهایی ورود نیست."
        )
        stop = b - buf
        goal = c
        invalid = (
            f"تثبیت روزانه/۴س زیر {b:,} بدون برگشت سریع، سناریوی B→C را باطل می‌کند. "
            f"عبور قوی بدون واکنش و ادامهٔ فشار پوت نیز سناریوی برگشت را ضعیف می‌کند."
        )
    elif plan.first_dir == "up" and plan.second_dir == "down":
        entry = (
            f"ورود long از spot یا اصلاح کوتاه فقط با تأیید صعود (۱۵دقیقه بالای {support:,})؛ "
            f"خروج یا hedge نزدیک {b:,} در صورت علائم برگشت. short بعد از B فقط با تأیید نزول."
        )
        stop = support - buf
        goal = b
        invalid = (
            f"شکست {support - buf:,} قبل از رسیدن به B سناریوی صعود اول را لغو می‌کند. "
            f"اگر B با حجم شکسته شود و C دور شود، سناریوی اصلاح به C فعال می‌ماند."
        )
    elif plan.first_dir == "up":
        entry = (
            f"ورود خرید روی اصلاح به {support:,} یا پس از بستن ۱۵دقیقه بالای {support:,}؛ "
            f"تأیید: افزایش نسبی خرید taker یا flow کال."
        )
        stop = support - buf
        goal = b
        invalid = f"تثبیت زیر {support:,} بدون برگشت، مسیر به B را باطل می‌کند."
    else:
        entry = (
            f"ورود long فقط بعد از B با واکنش صعودی (۱۵دقیقه بالای {b:,}). "
            f"short قبل از B فقط با شکست تأیید‌شده زیر {support:,}."
        )
        stop = b - buf
        goal = c
        invalid = (
            f"تثبیت زیر {b - buf:,} یا عدم هرگونه واکنش در B سناریو را باطل می‌کند."
        )

    summary = (
        f"قیمت از {spot_disp} در سناریوی اصلی ابتدا به {b:,} می‌رود؛ "
        f"{phrases['why']} "
        f"در {b:,} {phrases['react']} "
        f"سپس در صورت تأیید، {phrases['leg2']}"
    )

    return (
        f"**سناریوی اصلی BTC: {label}**\n\n"
        f"**قیمت فعلی:** {spot_disp}\n\n"
        f"**حرکت اولیه:**\n"
        f"از قیمت فعلی، احتمال حرکت به سمت **{b:,}** بیشتر است.\n\n"
        f"**چرا؟**\n"
        f"{phrases['why']}\n\n"
        f"**مرحله اول: قیمت فعلی → {b:,}**\n"
        f"{phrases['leg1']}\n\n"
        f"**واکنش در {b:,}:**\n"
        f"{phrases['react']}\n\n"
        f"**مرحله دوم: {b:,} → {c:,}**\n"
        f"{phrases['leg2']}\n\n"
        f"**مسیر:** {spot_disp} → {b:,} → {c:,}\n\n"
        f"**شرایط ورود:**\n"
        f"{entry}\n\n"
        f"**حد ضرر / نقطه توقف:** {stop:,}\n"
        f"**هدف:** {goal:,}\n\n"
        f"**ابطال سناریو:**\n"
        f"{invalid}\n\n"
        f"**جمع‌بندی سناریو:**\n"
        f"{summary}"
    )
