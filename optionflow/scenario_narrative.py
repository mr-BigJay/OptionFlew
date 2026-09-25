from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optionflow.flow_analyzer import (
    FlowAnalysis,
    confident_first_strike,
    top_strikes_near_spot,
)
from optionflow.path_scenario import (
    MovementPath,
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
    two_legs: bool


@dataclass
class _UsedSignals:
    keys: set[str] = field(default_factory=set)

    def take(self, key: str) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


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
            two_legs=True,
        )
    leg = legs[0]
    if leg.direction == "down":
        return _LegPlan(
            b=leg.to_level,
            c=target,
            first_dir="down",
            second_dir="up",
            two_legs=False,
        )
    return _LegPlan(
        b=leg.to_level,
        c=support,
        first_dir="up",
        second_dir="down",
        two_legs=False,
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
    """مسیر واحد Spot→B→C؛ فقط از guidance/flow — ctx مسیر را عوض نمی‌کند."""
    _ = ctx
    return effective_movement_path(
        main,
        support_zone=support,
        target_zone=target,
        spot=spot,
        primary=path_primary,
        alternate=path_alternate,
    )


def _plain(text: str) -> str:
    import re

    t = text.replace("**", "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _path_summary_fa(spot_disp: str, b: int, c: int) -> str:
    return f"از {spot_disp} به {b:,} و سپس به {c:,}"


def _flow_ratio(main: FlowAnalysis) -> float:
    c = main.contracts
    bull = c.buyer_call + c.seller_put
    bear = c.buyer_put + c.seller_call
    return bull / max(bear, 1e-9)


def _title_label(plan: _LegPlan) -> str:
    if plan.first_dir == "down":
        return "تمایل کوتاه‌مدت به افت اولیه"
    return "تمایل کوتاه‌مدت به صعود اولیه"


def _fallback_why_spot_b(plan: _LegPlan, b: int) -> str:
    if plan.first_dir == "down":
        return (
            f"جریان معاملات آپشن و سطوح فعال، حرکت اول از قیمت فعلی به سمت "
            f"{b:,} دلار را محتمل‌تر نشان می‌دهند."
        )
    return (
        f"جریان معاملات آپشن و تمرکز خرید در محدودهٔ بالاتر، "
        f"حرکت اول به {b:,} دلار را در کوتاه‌مدت محتمل‌تر می‌کند."
    )


def _why_spot_to_b(
    main: FlowAnalysis,
    plan: _LegPlan,
    b: int,
    ctx: Any | None,
    used: _UsedSignals,
) -> str:
    c = main.contracts
    ratio = _flow_ratio(main)
    spot = main.spot
    parts: list[str] = []

    if ctx is not None:
        taker = getattr(ctx, "taker_buy_sell_ratio", None)
        oi_ch = getattr(ctx, "oi_change_pct_1h", None)
        funding = getattr(ctx, "funding_rate", None)
        depth = getattr(ctx, "depth_imbalance_pct", None)

        if (
            plan.first_dir == "down"
            and taker is not None
            and taker < 0.98
            and used.take("taker")
        ):
            tail = (
                "فروش تهاجمی در بازار آتی کمی غالب است و فشار خرید فعلاً ضعیف به نظر می‌رسد"
            )
            if oi_ch is not None and oi_ch < -0.03 and used.take("oi"):
                tail += "؛ کاهش جزئی موقعیت‌های باز نیز با ضعف موقت خریداران هم‌خوان است"
            tail += f"؛ بنابراین حرکت اولیه به سمت {b:,} دلار محتمل‌تر شده است."
            parts.append(tail)
        elif (
            plan.first_dir == "up"
            and taker is not None
            and taker > 1.02
            and used.take("taker")
        ):
            tail = "خرید تهاجمی در بازار آتی نسبتاً قوی‌تر است"
            if oi_ch is not None and oi_ch > 0.03 and used.take("oi"):
                tail += " و افزایش موقعیت‌های باز حرکت اول به بالا را همراهی می‌کند"
            tail += f"؛ در نتیجه رسیدن به {b:,} دلار در مرحلهٔ اول محتمل‌تر است."
            parts.append(tail)

        if (
            not parts
            and funding is not None
            and funding > 0.0008
            and plan.first_dir == "down"
            and used.take("funding")
        ):
            parts.append(
                "فاندینگ مثبت نشان می‌دهد خریداران اهرمی شلوغ‌اند؛ "
                f"اصلاح کوتاه به سمت {b:,} دلار قبل از هر برگشت قوی‌تر دیده می‌شود."
            )

        if (
            not parts
            and depth is not None
            and plan.first_dir == "down"
            and depth < -3
            and used.take("depth")
        ):
            parts.append(
                "عرضهٔ نسبی در دفتر سفارش می‌تواند سرعت رسیدن قیمت به مقصد اول را بیشتر کند."
            )
        elif (
            not parts
            and depth is not None
            and plan.first_dir == "up"
            and depth > 3
            and used.take("depth")
        ):
            parts.append(
                "تقاضای نسبی در دفتر سفارش کوتاه‌مدت حرکت به مقصد اول را تقویت می‌کند."
            )

        struct = getattr(ctx, "structure_notes", None) or []
        for note in struct[:1]:
            clean = note.rstrip(".")
            if plan.first_dir == "down" and (
                "PDL" in note or "sweep" in note or "کف" in note
            ):
                if used.take("structure"):
                    parts.append(f"{clean}؛ با حرکت اول به {b:,} هم‌جهت است.")
                    break

    if not parts:
        if plan.first_dir == "down" and c.buyer_put >= c.buyer_call * 1.05 and used.take(
            "flow_put"
        ):
            parts.append(
                "غلبهٔ خرید قرارداد پوت در آپشن نشان می‌دهد معامله‌گران برای افت کوتاه‌مدت "
                f"پوشش ریسک گرفته‌اند؛ حرکت اول به {b:,} دلار منطقی است."
            )
        elif plan.first_dir == "up" and c.buyer_call >= c.buyer_put * 1.05 and used.take(
            "flow_call"
        ):
            parts.append(
                "خرید قرارداد کال در آپشن تمایل کوتاه‌مدت به بالا را تقویت می‌کند؛ "
                f"مقصد اول {b:,} دلار برآورد می‌شود."
            )
        elif (plan.first_dir == "down" and ratio < 1.0) or (
            plan.first_dir == "up" and ratio >= 1.0
        ):
            if used.take("flow_ratio"):
                dir_fa = "پایین" if plan.first_dir == "down" else "بالا"
                parts.append(
                    f"ترکیب جریان صعودی و نزولی در آپشن به نفع حرکت اول به سمت {dir_fa} است؛ "
                    f"مقصد اول {b:,} دلار است."
                )

    if not parts and used.take("strikes_leg1"):
        if plan.first_dir == "down":
            top_puts = top_strikes_near_spot(
                main.put_buy_by_strike, spot, 2, pct_lo=0.85, pct_hi=1.02
            )
            if top_puts:
                strikes_s = " و ".join(f"{int(k):,}" for k, _ in top_puts)
                parts.append(
                    f"تمرکز حجم خرید پوت نزدیک سطوح {strikes_s} مسیر را به سمت "
                    f"آزمایش حمایت در {b:,} دلار هدایت می‌کند."
                )
        else:
            top_calls = top_strikes_near_spot(
                main.call_buy_by_strike, spot, 2, pct_lo=1.0, pct_hi=1.12
            )
            if top_calls:
                strikes_s = " و ".join(f"{int(k):,}" for k, _ in top_calls)
                parts.append(
                    f"تمرکز خرید کال روی {strikes_s} قیمت را به سمت {b:,} دلار "
                    f"در مرحلهٔ اول می‌کشد."
                )

    return parts[0] if parts else _fallback_why_spot_b(plan, b)


def _why_react_at_b(
    main: FlowAnalysis,
    plan: _LegPlan,
    b: int,
    ctx: Any | None,
    used: _UsedSignals,
) -> str:
    spot = main.spot
    c = main.contracts

    if ctx is not None:
        gamma_s = getattr(ctx, "gamma_support", None)
        gamma_r = getattr(ctx, "gamma_resistance", None)
        pcoi = getattr(ctx, "put_call_oi", None)
        if plan.first_dir == "down" and gamma_s and abs(gamma_s - b) / max(spot, 1) < 0.02:
            if used.take("gamma"):
                return (
                    f"تمرکز گاما حمایتی نزدیک {b:,} دلار احتمال مکث یا برگشت در همان ناحیه "
                    f"را بیشتر می‌کند."
                )
        if plan.first_dir == "up" and gamma_r and abs(gamma_r - b) / max(spot, 1) < 0.02:
            if used.take("gamma"):
                return (
                    f"تمرکز گاما مقاومتی نزدیک {b:,} دلار توضیح می‌دهد چرا در مقصد اول "
                    f"واکنش یا اصلاح محتمل است."
                )
        if pcoi is not None and pcoi > 1.15 and plan.first_dir == "down" and used.take(
            "pcoi"
        ):
            return (
                f"نسبت بالای موقعیت باز پوت به کال نشان می‌دهد پوشش ریسک هنوز سنگین است؛ "
                f"واکنش در {b:,} دلار اگر رخ دهد احتمالاً محافظه‌کارانه خواهد بود."
            )
        struct = getattr(ctx, "structure_notes", None) or []
        for note in struct[:1]:
            if plan.first_dir == "up" and (
                "premium" in note or "PDH" in note or "اصلاح" in note
            ):
                if used.take("structure"):
                    return f"{note.rstrip('.')}؛ بنابراین در {b:,} دلار انتظار واکنش داریم."

        fg = getattr(ctx, "fear_greed", None)
        if fg is not None and fg <= 25 and used.take("fear_greed"):
            return (
                f"شاخص ترس در بازار بالاست؛ برخورد با {b:,} دلار ممکن است با واکنش "
                f"محافظه‌کارانه همراه شود."
            )

    if plan.first_dir == "down" and plan.second_dir == "up":
        if used.take("flow_react"):
            return (
                f"سطح {b:,} دلار از روی جریان آپشن به‌عنوان حمایت مهم دیده می‌شود؛ "
                f"اگر فشار فروش کم شود و خریداران وارد شوند، برگشت قیمت محتمل‌تر می‌شود."
            )
    if plan.first_dir == "up" and plan.second_dir == "down":
        if used.take("flow_react"):
            return (
                f"جریان آپشن همین {b:,} دلار را مقصد/مقاومت کوتاه‌مدت نشان داده؛ "
                f"سودگیری می‌تواند حرکت را موقتاً متوقف کند."
            )

    if c.buyer_call >= c.seller_call * 0.7 and plan.first_dir == "down" and used.take(
        "calls_hedge"
    ):
        return (
            "هم‌زمان خرید کال در سطوح بالاتر برقرار است؛ "
            f"اگر در {b:,} دلار فروشندگان خسته شوند، واکنش صعودی محتمل‌تر می‌شود."
        )

    return (
        f"تمرکز قراردادها و نقدینگی آپشن در {b:,} دلار احتمال واکنش قیمت "
        f"(مکث یا برگشت) را بالا می‌برد."
    )


def _why_b_to_c(plan: _LegPlan, b: int, c: int, main: FlowAnalysis, ctx: Any | None, used: _UsedSignals) -> str:
    spot = main.spot
    if b == c:
        return "در این سناریو مقصد بعدی با مقصد اول یکی است؛ ادامه مسیر منوط به تأیید در B است."

    if ctx is not None:
        max_pain = getattr(ctx, "max_pain", None)
        if max_pain and abs(max_pain - c) / max(spot, 1) < 0.04 and used.take("max_pain"):
            return (
                f"پس از واکنش در {b:,} دلار، کشش قیمت به سمت {c:,} "
                f"(نزدیک میانگین درد آپشن) محتمل است."
            )

    c_flow = main.contracts
    if plan.first_dir == "down" and plan.second_dir == "up" and used.take("flow_leg2"):
        return (
            f"اگر واکنش صعودی در {b:,} دلار تأیید شود، هدف بعدی جریان خرید کال "
            f"همچنان {c:,} دلار باقی می‌ماند."
        )
    if plan.first_dir == "up" and plan.second_dir == "down" and used.take("flow_leg2"):
        return (
            f"پس از واکنش در {b:,} دلار، اصلاح به {c:,} دلار (حمایت جریان پوت) "
            f"در سناریوی کوتاه‌مدت قابل انتظار است."
        )

    return (
        f"تأیید واکنش در {b:,} دلار شرط حرکت بعدی به {c:,} دلار است؛ "
        f"بدون آن ادامهٔ مسیر معتبر نیست."
    )


def _goal_line(plan: _LegPlan, b: int, c: int) -> str:
    if plan.two_legs or (plan.second_dir and b != c):
        return (
            f"مقصد اولیه {b:,} دلار است؛ در صورت واکنش و تأیید، مقصد بعدی {c:,} دلار خواهد بود."
        )
    return f"مقصد اولیه {b:,} دلار است."


def _summary_paragraph(spot_disp: str, b: int, c: int, plan: _LegPlan) -> str:
    path = _path_summary_fa(spot_disp, b, c)
    if plan.first_dir == "down" and plan.second_dir == "up":
        return (
            f"در کوتاه‌مدت انتظار داریم قیمت {path} حرکت کند: "
            f"ابتدا افت به {b:,}، واکنش در همان سطح، و در صورت تأیید برگشت به {c:,}."
        )
    if plan.first_dir == "up" and plan.second_dir == "down":
        return (
            f"در کوتاه‌مدت انتظار داریم قیمت {path} حرکت کند: "
            f"ابتدا صعود به {b:,}، واکنش یا اصلاح آنجا، و در صورت تأیید بازگشت به {c:,}."
        )
    direction = "بالا" if plan.first_dir == "up" else "پایین"
    return (
        f"سناریوی اصلی حرکت اول به سمت {direction} تا {b:,} دلار است؛ "
        f"ادامه تا {c:,} فقط پس از واکنش معتبر در مقصد اول."
    )


@dataclass(frozen=True)
class ScenarioPlan:
    """مسیر واحد گزارش (همان B/C متن سناریو)."""

    spot: float
    b: int
    c: int
    first_dir: str
    second_dir: str
    two_legs: bool
    # False: no concentrated strike, so A→B must not be drawn or stated as a level.
    first_confident: bool = True
    zone_low: int | None = None
    zone_high: int | None = None
    band_low: int | None = None
    band_high: int | None = None


def resolve_scenario_plan(
    main: FlowAnalysis,
    *,
    support: int,
    target: int,
    path_primary: MovementPath | None,
    path_alternate: MovementPath | None,
) -> ScenarioPlan | None:
    spot = round(main.spot, 2)
    path = _resolve_path_for_narrative(
        main,
        support=support,
        target=target,
        spot=spot,
        path_primary=path_primary,
        path_alternate=path_alternate,
        ctx=None,
    )
    if not path.legs:
        return None
    plan = _normalize_bc(path, support=support, target=target)
    anchored = confident_first_strike(main, plan.first_dir)
    if anchored is None:
        return ScenarioPlan(
            spot=spot,
            b=plan.b,
            c=plan.c,
            first_dir=plan.first_dir,
            second_dir=plan.second_dir,
            two_legs=plan.two_legs,
            first_confident=False,
        )
    return ScenarioPlan(
        spot=spot,
        b=anchored,
        c=plan.c,
        first_dir=plan.first_dir,
        second_dir=plan.second_dir,
        two_legs=plan.two_legs,
        first_confident=True,
    )


def _unclear_first_leg(spot: float) -> str:
    spot_disp = f"{spot:,.0f}"
    return (
        f"**سناریوی اصلی BTC**\nقیمت فعلی: {spot_disp} دلار\n\n"
        "**حرکت اول**\nمقصد اول نامشخص\n\n"
        "خرید کال یا خرید پوت در این پنجره روی یک استرایک جمع نشده است. "
        "میانگین وزنی استرایک‌ها و فاصلهٔ ثابت از قیمت، مقصد محسوب نمی‌شود.\n\n"
        "**جمع‌بندی**\n\n"
        "تا وقتی حجم جهت‌دار روی یک استرایک غالب شود، مسیر A به B رسم نمی‌شود."
    )


def _assemble_structured_report(
    *,
    title: str,
    spot_disp: str,
    b: int,
    c: int,
    why_spot_b: str,
    why_react_b: str,
    why_b_c: str,
    entry: str,
    stop: int,
    goal_line: str,
    invalid: str,
    summary: str,
) -> str:
    sections = [
        f"**سناریوی اصلی BTC**\n{title} — قیمت فعلی: {spot_disp} دلار",
        f"**حرکت اول**\nاز {spot_disp} به {b:,}\n\n{_plain(why_spot_b)}",
        f"**واکنش در B**\n{b:,} دلار\n\n{_plain(why_react_b)}",
        f"**حرکت دوم**\nاز {b:,} به {c:,}\n\n{_plain(why_b_c)}",
        f"**شرایط ورود**\n\n{_plain(entry)}",
        f"**حد ضرر**\n{stop:,} دلار",
        f"**هدف**\n{_plain(goal_line)}",
        f"**ابطال سناریو**\n\n{_plain(invalid)}",
        f"**جمع‌بندی**\n\n{_plain(summary)}",
    ]
    return "\n\n".join(sections)


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
    _ = bias
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
    anchored = confident_first_strike(main, plan.first_dir)
    if anchored is None:
        return _unclear_first_leg(spot)
    plan.b = anchored
    b, c = plan.b, plan.c
    spot_disp = f"{spot:,.0f}"
    buf = _sl_buffer(spot)
    used = _UsedSignals()

    why_spot_b = _why_spot_to_b(main, plan, b, ctx, used)
    why_react_b = _why_react_at_b(main, plan, b, ctx, used)
    why_b_c = _why_b_to_c(plan, b, c, main, ctx, used)

    if plan.first_dir == "down" and plan.second_dir == "up":
        entry = (
            f"ورود خرید فقط پس از واکنش معتبر در {b:,} دلار؛ "
            f"ترجیحاً بسته‌شدن کندل ۱۵ دقیقه‌ای بالای محدوده و تأیید فشار خرید."
        )
        stop = b - buf
        invalid = (
            f"تثبیت قیمت زیر {b:,} دلار بدون واکنش صعودی؛ "
            f"از دست رفتن حمایت و باطل شدن سناریوی برگشت به {c:,}."
        )
    elif plan.first_dir == "up" and plan.second_dir == "down":
        # مقصد اصلاح (C) زیر قیمت است؛ استاپ کمی پایین‌تر از آن کف سناریو است،
        # نه «لغو مسیر به C». ورود هم نباید «بستن کندل بالای C» باشد وقتی قیمت از قبل بالاتر است.
        floor = min(support, c)
        stop = floor - buf
        entry = (
            f"خرید اهرمی فقط در جهت صعود اول به سمت {b:,}، "
            f"با تأیید کندل ۱۵ دقیقه در جهت بالا. "
            f"پوشش یا خروج نزدیک {b:,}. "
            f"فروش اهرمی فقط بعد از واکنش در {b:,} و تأیید نزول به سمت {c:,}."
        )
        invalid = (
            f"اگر قبل از رسیدن به {b:,} قیمت زیر {stop:,} تثبیت شود، صعود اول باطل است. "
            f"سناریو ترتیب دارد: اول {b:,}، بعد اصلاح به {c:,}. "
            f"افت مستقیم زیر {stop:,} این ترتیب را باطل می‌کند؛ "
            f"عبور از {c:,} بدون صعود اول، همان حرکت دوم برنامه‌ریزی‌شده نیست."
        )
    elif plan.first_dir == "up":
        entry = (
            f"ورود خرید روی اصلاح به {support:,} یا پس از بستن ۱۵ دقیقه بالای {support:,} "
            f"با تأیید فشار خرید."
        )
        stop = support - buf
        invalid = (
            f"تثبیت زیر {support:,} بدون برگشت؛ باطل شدن مسیر به {b:,} "
            f"و ادامه تا {c:,}."
        )
    else:
        entry = (
            f"ورود خرید فقط بعد از واکنش در {b:,} (۱۵ دقیقه بالای سطح). "
            f"رسیدن به مقصد اول به‌تنهایی ورود نیست."
        )
        stop = b - buf
        invalid = (
            f"تثبیت زیر {b:,} دلار بدون واکنش؛ باطل شدن سناریو و مسیر بعدی به {c:,}."
        )

    goal_line = _goal_line(plan, b, c)
    summary = _summary_paragraph(spot_disp, b, c, plan)
    title = _title_label(plan)

    return _assemble_structured_report(
        title=title,
        spot_disp=spot_disp,
        b=b,
        c=c,
        why_spot_b=why_spot_b,
        why_react_b=why_react_b,
        why_b_c=why_b_c,
        entry=entry,
        stop=stop,
        goal_line=goal_line,
        invalid=invalid,
        summary=summary,
    )
