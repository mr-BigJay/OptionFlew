from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from optionflow.flow_analyzer import FlowAnalysis, top_strikes_near_spot
from optionflow.path_scenario import (
    MovementPath,
    PathLeg,
    effective_movement_path,
)


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


def _down_then_up_path(spot: float, support: int, target: int) -> MovementPath:
    spot_i = int(round(spot))
    return MovementPath(
        id="down_then_up",
        title_fa="مسیر محتمل: اول پایین، بعد برگشت",
        legs=(
            PathLeg("down", spot_i, support),
            PathLeg("up", support, target),
        ),
        narrative_fa="",
        likelihood="primary",
    )


def _resolve_path_for_narrative(
    main: FlowAnalysis,
    *,
    support: int,
    target: int,
    spot: float,
    path_primary: MovementPath | None,
    path_alternate: MovementPath | None,
    ctx: Any | None,
) -> MovementPath:
    """مسیر گزارش: enriched (taker/OI) + flow؛ هم‌راستا با سناریوی down→up نمونه."""
    base = effective_movement_path(
        main,
        support_zone=support,
        target_zone=target,
        spot=spot,
        primary=path_primary,
        alternate=path_alternate,
    )
    spot_i = int(round(spot))
    if support >= spot_i or target <= support:
        return base

    c = main.contracts
    bear_pts = 0
    bull_pts = 0

    if ctx is not None:
        taker = getattr(ctx, "taker_buy_sell_ratio", None)
        oi_ch = getattr(ctx, "oi_change_pct_1h", None)
        if taker is not None:
            if taker < 0.98:
                bear_pts += 3
            elif taker > 1.02:
                bull_pts += 3
        if oi_ch is not None:
            if oi_ch < -0.05:
                bear_pts += 1
            elif oi_ch > 0.05:
                bull_pts += 1

    ratio = _flow_ratio(main)
    if c.buyer_put >= c.buyer_call * 1.08:
        bear_pts += 2
    if c.buyer_call >= c.buyer_put * 1.08:
        bull_pts += 2
    if ratio < 0.95:
        bear_pts += 1
    elif ratio > 1.05:
        bull_pts += 1

    if bear_pts > bull_pts and bear_pts >= 2:
        return _down_then_up_path(spot, support, target)
    if bull_pts > bear_pts and bull_pts >= 3 and ratio >= 1.08:
        if base.id == "up_then_down":
            return base
        return MovementPath(
            id="up_then_down",
            title_fa="مسیر محتمل: اول بالا، بعد اصلاح",
            legs=(
                PathLeg("up", spot_i, target),
                PathLeg("down", target, support),
            ),
            narrative_fa="",
            likelihood="primary",
        )
    if base.id in ("down_then_up", "down_continuation"):
        return _down_then_up_path(spot, support, target)
    return base


def _assemble_report(
    *,
    title: str,
    spot_disp: str,
    opening: str,
    b: int,
    c: int,
    leg1: str,
    react: str,
    leg2: str,
    entry: str,
    stop: int,
    goal: int,
    invalid: str,
    summary: str,
) -> str:
    return (
        f"**سناریوی اصلی BTC: {title}**\n\n"
        f"**قیمت فعلی: {spot_disp} دلار**\n\n"
        f"{opening}\n\n"
        f"**مرحله اول: {spot_disp} → {b:,}**\n\n"
        f"{leg1}\n\n"
        f"**واکنش در {b:,}**\n\n"
        f"{react}\n\n"
        f"**مرحله دوم: {b:,} → {c:,}**\n\n"
        f"{leg2}\n\n"
        f"**شرایط ورود**\n\n"
        f"{entry}\n\n"
        f"**حد ضرر:** {stop:,} دلار\n"
        f"**هدف:** {goal:,} دلار\n\n"
        f"**ابطال سناریو**\n\n"
        f"{invalid}\n\n"
        f"**جمع‌بندی**\n\n"
        f"{summary}"
    )


def _title_label(first_dir: str) -> str:
    if first_dir == "down":
        return "تمایل کوتاه‌مدت نزولی"
    return "تمایل کوتاه‌مدت صعودی"


def _join_bits(parts: list[str], fallback: str) -> str:
    cleaned = [p.strip().rstrip(".") for p in parts if p][:3]
    if not cleaned:
        return fallback
    return ". ".join(cleaned) + "."


def _opening_paragraph(
    plan: _LegPlan,
    b: int,
    phrases: dict[str, str],
    ctx: Any | None,
) -> str:
    lead = (
        f"از قیمت فعلی، احتمال حرکت اولیه به سمت **{b:,} دلار** بیشتر است."
    )
    if ctx is None:
        return f"{lead} {phrases['why']}"

    taker = getattr(ctx, "taker_buy_sell_ratio", None)
    oi_ch = getattr(ctx, "oi_change_pct_1h", None)
    funding = getattr(ctx, "funding_rate", None)

    if plan.first_dir == "down" and taker is not None and taker < 1.0:
        tail = (
            f" دلیل اصلی این دید، ضعف نسبی فشار خرید در بازار فیوچرز است؛ "
            f"نسبت Taker Buy/Sell روی **{taker:.2f}** قرار دارد"
        )
        if oi_ch is not None and oi_ch < 0:
            tail += " و OI نیز کمی کاهش داشته است"
        elif oi_ch is not None:
            tail += f" و تغییر OI در ۱س حدود {oi_ch:+.1f}٪ است"
        if funding is not None:
            fr = funding * 100
            if abs(fr) < 0.008:
                tail += (
                    ". در کنار آن، Funding تقریباً خنثی است و فعلاً نشانه‌ای از "
                    "قدرت بالای خریداران اهرمی دیده نمی‌شود."
                )
            elif funding > 0:
                tail += (
                    f". Funding مثبت ({fr:.3f}٪) نشان می‌دهد longهای اهرمی شلوغ‌اند؛ "
                    "اصلاح کوتاه‌مدت به پایین محتمل‌تر است."
                )
            else:
                tail += f". Funding ({fr:.3f}٪) فعلاً از فشار فروش اهرمی حکایت ندارد."
        else:
            tail += "."
        c_flow = main.contracts
        if c_flow.buyer_put >= c_flow.buyer_call * 1.05:
            return (
                lead
                + tail
                + f" در معاملات آپشن Deribit نیز خرید پوت غالب است و "
                f"سطح {b:,} به‌عنوان حمایت flow برجسته شده است."
            )
        extra = phrases["why"]
        if "پوت" in extra and "taker" not in extra.lower():
            first = extra.split(". ")[0].strip()
            if first and first not in tail:
                return lead + tail + " " + first + "."
        return lead + tail

    if plan.first_dir == "up" and taker is not None and taker > 1.0:
        tail = (
            f" فشار خرید taker (نسبت **{taker:.2f}**) در futures "
            f"حرکت اول به سمت بالا را تقویت می‌کند."
        )
        if oi_ch is not None and oi_ch > 0:
            tail += f" افزایش OI ({oi_ch:+.1f}٪ در ۱س) نیز همراهی می‌کند."
        return lead + tail + " " + phrases["why"]

    return f"{lead} {phrases['why']}"


def _leg1_paragraph(plan: _LegPlan, spot_disp: str, b: int, phrases: dict[str, str]) -> str:
    if plan.first_dir == "down":
        base = (
            f"احتمال می‌دهیم قیمت ابتدا به سمت **{b:,} دلار** حرکت کند، "
            f"چون در شرایط فعلی قدرت خرید کافی برای شکستن مستقیم سقف محدوده دیده نمی‌شود. "
            f"این حرکت می‌تواند با هدف جمع‌کردن نقدینگی در محدوده پایین‌تر و آزمایش حمایت اصلی انجام شود."
        )
    else:
        base = (
            f"احتمال می‌دهیم قیمت ابتدا به سمت **{b:,} دلار** حرکت کند، "
            f"چون flow آپشن و خرید کال در strikeهای بالاتر مسیر کوتاه‌مدت را به سمت هدف flow هدایت می‌کند."
        )
    extra = phrases["leg1"]
    if extra and extra not in base:
        return base + " " + extra
    return base


def _react_paragraph(plan: _LegPlan, b: int, phrases: dict[str, str]) -> str:
    if plan.first_dir == "down" and plan.second_dir == "up":
        base = (
            f"در این محدوده انتظار واکنش قیمت را داریم، چون این سطح بر اساس معاملات آپشن "
            f"به‌عنوان حمایت مهم شناسایی شده است. "
            f"اگر در برخورد با این سطح فشار فروش کاهش پیدا کند و خریداران وارد شوند، "
            f"احتمال برگشت قیمت افزایش می‌یابد."
        )
    elif plan.first_dir == "up" and plan.second_dir == "down":
        base = (
            f"در **{b:,}** انتظار واکنش یا اصلاح داریم، چون flow همین سطح را "
            f"به‌عنوان هدف/مقاومت کوتاه‌مدت نشان داده است. "
            f"فروش کال یا سودگیری می‌تواند حرکت را موقتاً متوقف کند."
        )
    else:
        base = phrases["react"]
    extra = phrases["react"]
    if plan.first_dir == "down" and plan.second_dir == "up":
        if extra and extra not in base:
            return base + " " + extra
        return base
    if plan.first_dir == "up" and plan.second_dir == "down":
        if extra and extra not in base:
            return base + " " + extra
        return base
    if extra and extra not in base:
        return base + " " + extra
    return base


def _leg2_paragraph(plan: _LegPlan, b: int, c: int, phrases: dict[str, str]) -> str:
    if plan.first_dir == "down" and plan.second_dir == "up":
        base = (
            f"در صورت تأیید واکنش صعودی در {b:,}، حرکت بعدی می‌تواند به سمت **{c:,} دلار** باشد. "
            f"در این حالت، برگشت از حمایت می‌تواند قیمت را به سمت محدوده بالایی بازار "
            f"و سطح مهم بعدی آپشن‌ها (هدف flow) هدایت کند."
        )
        extra = phrases["leg2"]
        if extra and extra not in base:
            return base + " " + extra
        return base
    if plan.first_dir == "up" and plan.second_dir == "down":
        return (
            f"پس از واکنش در {b:,}، اصلاح به **{c:,} دلار** (حمایت flow) "
            f"در سناریوی کوتاه‌مدت محتمل است."
        )
    return phrases["leg2"]


def _summary_paragraph(
    spot_disp: str,
    b: int,
    c: int,
    plan: _LegPlan,
) -> str:
    if plan.first_dir == "down" and plan.second_dir == "up":
        return (
            f"سناریوی اصلی این است که BTC از **{spot_disp} دلار ابتدا به سمت {b:,} دلار** "
            f"حرکت کند، در آن محدوده واکنش بگیرد و در صورت تأیید ورود خریداران، "
            f"به سمت **{c:,} دلار** برگردد. بنابراین در قیمت فعلی، تمرکز اصلی روی "
            f"حرکت نزولی اولیه و سپس بررسی واکنش قیمت در {b:,} دلار است."
        )
    if plan.first_dir == "up" and plan.second_dir == "down":
        return (
            f"سناریوی اصلی: از **{spot_disp} دلار** ابتدا صعود به **{b:,} دلار**، "
            f"سپس در صورت واکنش، اصلاح به **{c:,} دلار**. "
            f"تمرکز فعلی روی حرکت اول به بالا و مدیریت ریسک نزدیک {b:,} است."
        )
    direction = "صعودی" if plan.first_dir == "up" else "نزولی"
    return (
        f"سناریوی اصلی حرکت {direction} اولیه از **{spot_disp} دلار** به **{b:,} دلار** است؛ "
        f"ادامه به **{c:,} دلار** فقط در صورت تأیید واکنش در B."
    )


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
            clean = note.rstrip(".")
            if plan.first_dir == "down" and (
                "PDL" in note or "sweep" in note or "کف" in note
            ):
                leg1_bits.append(clean + "؛ با حرکت اول به B هم‌جهت است")
            elif plan.first_dir == "up" and (
                "premium" in note or "PDH" in note or "اصلاح" in note
            ):
                react_bits.append(clean)

    if ctx is not None and plan.first_dir == "down":
        taker_open = getattr(ctx, "taker_buy_sell_ratio", None)
        if taker_open is not None and taker_open < 1.0:
            why_bits = [
                w
                for w in why_bits
                if "taker" not in w.lower()
                and "futures" not in w
                and "OI آتی" not in w
            ]

    return {
        "why": _join_bits(
            why_bits,
            "ترکیب flow آپشن در این پنجره جهت اول را به سمت B سوق می‌دهد.",
        ),
        "leg1": _join_bits(
            leg1_bits,
            f"از قیمت فعلی، جذب نقدینگی و strikeهای فعال flow مسیر را به {b:,} می‌کشد.",
        ),
        "react": _join_bits(
            react_bits,
            f"در {b:,} تمرکز strike و نقدینگی flow احتمال واکنش قیمت را بالا می‌برد.",
        ),
        "leg2": _join_bits(
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
    path = _resolve_path_for_narrative(
        main,
        support=support,
        target=target,
        spot=spot,
        path_primary=path_primary,
        path_alternate=path_alternate,
        ctx=ctx,
    )
    if not path.legs:
        return "دادهٔ کافی برای سناریوی اصلی از قیمت فعلی در دسترس نیست."

    plan = _normalize_bc(path, support=support, target=target)
    b, c = plan.b, plan.c
    spot_disp = f"{spot:,.0f}"
    buf = _sl_buffer(spot)
    label = _title_label(plan.first_dir)
    phrases = _pick_phrases(
        main, bias=bias, support=support, target=target, plan=plan, ctx=ctx
    )
    opening = _opening_paragraph(plan, b, phrases, ctx)
    leg1 = _leg1_paragraph(plan, spot_disp, b, phrases)
    react = _react_paragraph(plan, b, phrases)
    leg2 = _leg2_paragraph(plan, b, c, phrases)

    if plan.first_dir == "down" and plan.second_dir == "up":
        entry = (
            f"ورود خرید فقط بعد از واکنش معتبر در {b:,} انجام شود؛ "
            f"ترجیحاً با بسته‌شدن کندل ۱۵ دقیقه‌ای بالای محدوده و تأیید افزایش فشار خرید."
        )
        stop = b - buf
        goal = c
        invalid = (
            f"اگر قیمت زیر **{b:,} دلار** تثبیت شود و حمایت از دست برود، "
            f"سناریوی برگشت صعودی دیگر معتبر نیست و ورود خرید انجام نمی‌شود."
        )
    elif plan.first_dir == "up" and plan.second_dir == "down":
        entry = (
            f"ورود long فقط با تأیید صعود (کندل ۱۵ دقیقه بالای {support:,})؛ "
            f"خروج یا hedge نزدیک {b:,}. short بعد از B فقط با تأیید نزول."
        )
        stop = support - buf
        goal = b
        invalid = (
            f"شکست {support - buf:,} قبل از رسیدن به {b:,} سناریوی صعود اول را لغو می‌کند."
        )
    elif plan.first_dir == "up":
        entry = (
            f"ورود خرید روی اصلاح به {support:,} یا پس از بستن ۱۵ دقیقه بالای {support:,} "
            f"با تأیید فشار خرید."
        )
        stop = support - buf
        goal = b
        invalid = f"تثبیت زیر {support:,} بدون برگشت، مسیر به {b:,} باطل می‌شود."
    else:
        entry = (
            f"ورود خرید فقط بعد از واکنش در {b:,} (۱۵ دقیقه بالای سطح). "
            f"رسیدن به B به‌تنهایی ورود نیست."
        )
        stop = b - buf
        goal = c
        invalid = f"تثبیت زیر **{b:,} دلار** بدون واکنش، سناریو را باطل می‌کند."

    return _assemble_report(
        title=label,
        spot_disp=spot_disp,
        opening=opening,
        b=b,
        c=c,
        leg1=leg1,
        react=react,
        leg2=leg2,
        entry=entry,
        stop=stop,
        goal=goal,
        invalid=invalid,
        summary=_summary_paragraph(spot_disp, b, c, plan),
    )
