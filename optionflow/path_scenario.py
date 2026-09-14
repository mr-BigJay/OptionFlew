from __future__ import annotations

from dataclasses import dataclass

from optionflow.flow_analyzer import FlowAnalysis, top_strikes, weighted_strike_center


@dataclass(frozen=True)
class PathLeg:
    direction: str  # "up" | "down" | "flat"
    from_level: int
    to_level: int

    def arrow_fa(self) -> str:
        if self.direction == "up":
            sym = "↑"
        elif self.direction == "down":
            sym = "↓"
        else:
            sym = "→"
        return f"{self.from_level:,} {sym} {self.to_level:,}"


@dataclass(frozen=True)
class MovementPath:
    id: str
    title_fa: str
    legs: tuple[PathLeg, ...]
    narrative_fa: str
    likelihood: str  # primary | alternate

    def diagram(self) -> str:
        if not self.legs:
            return ""
        parts = [f"{self.legs[0].from_level:,}"]
        for leg in self.legs:
            arrow = "↑" if leg.direction == "up" else "↓" if leg.direction == "down" else "→"
            parts.append(f"{arrow} {leg.to_level:,}")
        return "  ".join(parts)


def _sum_strikes_in_band(strikes: dict[float, float], lo: float, hi: float) -> float:
    return sum(v for k, v in strikes.items() if lo <= k <= hi)


def _flow_bias_flags(main: FlowAnalysis) -> tuple[float, bool, bool, bool]:
    """Same bull/bear/neutral thresholds as guide.build_guidance."""
    c = main.contracts
    bull_flow = c.buyer_call + c.seller_put
    bear_flow = c.buyer_put + c.seller_call
    ratio = bull_flow / max(bear_flow, 1e-9)
    flow_bullish = ratio >= 1.25
    flow_bearish = ratio <= 0.8
    flow_neutral = not flow_bullish and not flow_bearish
    return ratio, flow_bullish, flow_bearish, flow_neutral


def _range_path(
    spot_i: int,
    support_zone: int,
    target_zone: int,
) -> MovementPath:
    return MovementPath(
        id="range",
        title_fa="مسیر محتمل: نوسان بین دو سطح",
        legs=(
            PathLeg("up", spot_i, target_zone),
            PathLeg("down", target_zone, support_zone),
        ),
        narrative_fa=(
            f"معاملات متعادل است؛ امکان دارد قیمت بین {support_zone:,} و {target_zone:,} "
            f"چند بار بالا و پایین شود تا یکی از سطوح شکسته شود."
        ),
        likelihood="primary",
    )


def infer_movement_paths(
    main: FlowAnalysis,
    *,
    support_zone: int,
    target_zone: int,
    spot: float,
) -> tuple[MovementPath, MovementPath | None]:
    c = main.contracts
    spot_i = int(round(spot))
    _, flow_bullish, flow_bearish, flow_neutral = _flow_bias_flags(main)

    call_sell_at_target = _sum_strikes_in_band(
        main.call_sell_by_strike,
        target_zone * 0.97,
        target_zone * 1.03,
    )
    put_buy_near_support = _sum_strikes_in_band(
        main.put_buy_by_strike,
        support_zone * 0.97,
        support_zone * 1.03,
    )

    bullish_calls = c.buyer_call >= c.buyer_put * 1.1 and target_zone > spot_i
    bearish_puts = c.buyer_put >= c.buyer_call * 1.1 and support_zone < spot_i
    capped_upside = call_sell_at_target >= max(c.buyer_call * 0.25, 2.0)
    hedged_rally = c.buyer_put >= c.buyer_call * 0.45 and bullish_calls

    paths: list[MovementPath] = []

    pullback_credible = hedged_rally or put_buy_near_support >= max(
        c.buyer_call * 0.12, 1.0
    )

    # 1) Up then down — needs upside cap AND evidence puts/support invite a pullback
    if flow_bullish and bullish_calls and capped_upside and pullback_credible:
        legs = (
            PathLeg("up", spot_i, target_zone),
            PathLeg("down", target_zone, support_zone),
        )
        why = []
        if capped_upside:
            why.append("فروش کال نزدیک هدف (سقف احتمالی)")
        if hedged_rally:
            why.append("هم‌زمان خرید پوت (احتمال برگشت بعد از صعود)")
        paths.append(
            MovementPath(
                id="up_then_down",
                title_fa="مسیر محتمل: اول بالا، بعد برگشت پایین",
                legs=legs,
                narrative_fa=(
                    f"احتمال حرکت به سمت {target_zone:,} هست (خریدار کال غالب)، "
                    f"ولی {' و '.join(why)}؛ "
                    f"پس برگشت به ناحیهٔ {support_zone:,} بعد از نزدیک شدن به هدف منطقی است."
                ),
                likelihood="primary",
            )
        )

    # 2) Down then up — dip to put support, then call targets
    dip_credible = bearish_puts or (
        put_buy_near_support >= max(c.buyer_call * 0.3, 2.0)
    )
    if dip_credible and not flow_neutral:
        if target_zone > support_zone and c.buyer_call >= c.seller_call * 0.8:
            legs = (
                PathLeg("down", spot_i, support_zone),
                PathLeg("up", support_zone, target_zone),
            )
            paths.append(
                MovementPath(
                    id="down_then_up",
                    title_fa="مسیر محتمل: اول پایین (یا حمله به حمایت)، بعد برگشت بالا",
                    legs=legs,
                    narrative_fa=(
                        f"خرید پوت نزدیک {support_zone:,} می‌تواند یک افت کوتاه‌مدت بسازد؛ "
                        f"اگر حمایت بگیرد، خرید کال همچنان {target_zone:,} را به‌عنوان هدف بالاتر نشان می‌دهد."
                    ),
                    likelihood="primary" if not paths else "alternate",
                )
            )

    # 3) Straight up
    if flow_bullish and bullish_calls and not capped_upside and not paths:
        paths.append(
            MovementPath(
                id="up_continuation",
                title_fa="مسیر محتمل: ادامهٔ حرکت به بالا",
                legs=(PathLeg("up", spot_i, target_zone),),
                narrative_fa=(
                    f"غلبهٔ خریدار کال بدون سقف قوی فروش کال در {target_zone:,}; "
                    f"مسیر کوتاه‌مدت بیشتر یک‌طرفه به سمت هدف دیده می‌شود."
                ),
                likelihood="primary",
            )
        )

    # 4) Straight down
    if (
        flow_bearish
        and bearish_puts
        and c.buyer_call < c.buyer_put * 0.9
        and not any(p.id == "down_then_up" for p in paths)
    ):
        paths.append(
            MovementPath(
                id="down_continuation",
                title_fa="مسیر محتمل: فشار به پایین",
                legs=(PathLeg("down", spot_i, support_zone),),
                narrative_fa=(
                    f"تمایل محافظتی غالب است؛ مسیر اولیه به سمت {support_zone:,} "
                    f"قبل از هر برگشت صعودی محتمل‌تر است."
                ),
                likelihood="primary" if not paths else "alternate",
            )
        )

    # 5) Range / chop
    if not paths:
        paths.append(_range_path(spot_i, support_zone, target_zone))

    primary = next(p for p in paths if p.likelihood == "primary")
    alternate = next((p for p in paths if p.likelihood == "alternate"), None)
    if alternate is None:
        for p in paths:
            if p is not primary:
                alternate = p
                break

    return primary, alternate


def effective_movement_path(
    main: FlowAnalysis,
    *,
    support_zone: int,
    target_zone: int,
    spot: float,
    primary: MovementPath | None,
    alternate: MovementPath | None,
) -> MovementPath:
    """مسیر جهت‌دار برای گزارش کوتاه؛ از رنج مبهم پرهیز می‌کند."""
    if primary is not None and primary.id != "range":
        return primary
    if alternate is not None and alternate.id != "range":
        return alternate
    return _inferred_direction_path(main, spot=spot, support_zone=support_zone, target_zone=target_zone)


def _inferred_direction_path(
    main: FlowAnalysis,
    *,
    spot: float,
    support_zone: int,
    target_zone: int,
) -> MovementPath:
    spot_i = int(round(spot))
    c = main.contracts
    bull = c.buyer_call + c.seller_put
    bear = c.buyer_put + c.seller_call
    ratio = bull / max(bear, 1e-9)

    if ratio >= 1.08 and target_zone > spot_i:
        if bear >= bull * 0.38 and support_zone < spot_i:
            legs = (
                PathLeg("up", spot_i, target_zone),
                PathLeg("down", target_zone, support_zone),
            )
            return MovementPath(
                id="up_then_down",
                title_fa="مسیر محتمل: اول بالا، بعد اصلاح",
                legs=legs,
                narrative_fa=(
                    f"flow کمی صعودی است؛ حرکت اول به {target_zone:,} محتمل‌تر دیده می‌شود "
                    f"و پس از آن احتمال اصلاح به {support_zone:,}."
                ),
                likelihood="primary",
            )
        return MovementPath(
            id="up_continuation",
            title_fa="مسیر محتمل: حرکت اول به بالا",
            legs=(PathLeg("up", spot_i, target_zone),),
            narrative_fa=f"از همین قیمت، مسیر کوتاه‌مدت به سمت {target_zone:,} برآورد می‌شود.",
            likelihood="primary",
        )

    if ratio <= 0.92 and support_zone < spot_i:
        if bull >= bear * 0.35 and target_zone > support_zone:
            legs = (
                PathLeg("down", spot_i, support_zone),
                PathLeg("up", support_zone, target_zone),
            )
            return MovementPath(
                id="down_then_up",
                title_fa="مسیر محتمل: اول پایین، بعد برگشت",
                legs=legs,
                narrative_fa=(
                    f"فشار محافظتی؛ حرکت اول به {support_zone:,} محتمل‌تر است "
                    f"و در صورت حمایت، هدف بعدی {target_zone:,}."
                ),
                likelihood="primary",
            )
        return MovementPath(
            id="down_continuation",
            title_fa="مسیر محتمل: حرکت اول به پایین",
            legs=(PathLeg("down", spot_i, support_zone),),
            narrative_fa=f"از همین قیمت، مسیر کوتاه‌مدت به سمت {support_zone:,} برآورد می‌شود.",
            likelihood="primary",
        )

    # تمایل ضعیف ولی یک جهت اول انتخاب می‌شود (نه «رنج»)
    if ratio >= 1.0 and target_zone > spot_i:
        return MovementPath(
            id="up_continuation",
            title_fa="مسیر محتمل: تمایل جزئی به بالا",
            legs=(PathLeg("up", spot_i, target_zone),),
            narrative_fa=f"تمایل flow اندک به بالا؛ مقصد اول {target_zone:,}.",
            likelihood="primary",
        )
    if support_zone < spot_i:
        return MovementPath(
            id="down_continuation",
            title_fa="مسیر محتمل: تمایل جزئی به پایین",
            legs=(PathLeg("down", spot_i, support_zone),),
            narrative_fa=f"تمایل flow اندک به پایین؛ مقصد اول {support_zone:,}.",
            likelihood="primary",
        )
    return MovementPath(
        id="up_continuation",
        title_fa="مسیر محتمل: حرکت اول",
        legs=(PathLeg("up", spot_i, max(target_zone, spot_i + 1)),),
        narrative_fa="دادهٔ جهت‌دار محدود؛ مسیر اول صعودی فرض شده است.",
        likelihood="primary",
    )


def format_path_section(
    primary: MovementPath,
    alternate: MovementPath | None,
    main: FlowAnalysis,
) -> str:
    lines = [
        "**پیش‌بینی مسیر حرکت (سناریو، نه قطعیت):**",
        "",
        f"▶ {primary.title_fa}",
        f"   {primary.diagram()}",
        primary.narrative_fa,
    ]
    if alternate:
        lines.extend(
            [
                "",
                f"▷ سناریوی جایگزین: {alternate.title_fa}",
                f"   {alternate.diagram()}",
                alternate.narrative_fa,
            ]
        )
    top_c = top_strikes(main.call_buy_by_strike, 2)
    top_p = top_strikes(main.put_buy_by_strike, 2)
    if top_c or top_p:
        lines.append("")
        lines.append(
            "_منطق: مسیر از هم‌راستایی یا تضاد خرید کال (هدف بالا) و خرید پوت (حمایت پایین) ساخته شده._"
        )
    return "\n".join(lines)
