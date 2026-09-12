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


def infer_movement_paths(
    main: FlowAnalysis,
    *,
    support_zone: int,
    target_zone: int,
    spot: float,
) -> tuple[MovementPath, MovementPath | None]:
    c = main.contracts
    spot_i = int(round(spot / 500) * 500)

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

    # 1) Up then down — call buyers push up, puts/sold calls cap and reverse
    if bullish_calls and (capped_upside or hedged_rally):
        legs = (
            PathLeg("up", spot_i, target_zone),
            PathLeg("down", target_zone, support_zone),
        )
        why = []
        if capped_upside:
            why.append("فروش کال نزدیک هدف (سقف احتمالی)")
        if hedged_rally:
            why.append("هم‌زمان خرید پوت (احتمال برگشت بعد از رally)")
        paths.append(
            MovementPath(
                id="up_then_down",
                title_fa="مسیر محتمل: اول بالا، بعد برگشت پایین",
                legs=legs,
                narrative_fa=(
                    f"بر اساس flow، **احتمال حرکت به سمت {target_zone:,}** هست "
                    f"(خریدار کال غالب)، ولی {' و '.join(why)}؛ "
                    f"پس سناریوی **برگشت به ناحیهٔ {support_zone:,}** بعد از لمس یا نزدیک شدن به هدف منطقی است."
                ),
                likelihood="primary",
            )
        )

    # 2) Down then up — dip to put support, then call targets
    if bearish_puts or (put_buy_near_support >= max(c.buyer_call * 0.3, 2.0)):
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
                        f"خرید پوت نزدیک **{support_zone:,}** «حمله» یا flush کوتاه‌مدت را پیشنهاد می‌دهد؛ "
                        f"اگر حمایت بگیرد، flow کال همچنان **{target_zone:,}** را به‌عنوان هدف بالاتر نشان می‌دهد."
                    ),
                    likelihood="primary" if not paths else "alternate",
                )
            )

    # 3) Straight up
    if bullish_calls and not capped_upside and not paths:
        paths.append(
            MovementPath(
                id="up_continuation",
                title_fa="مسیر محتمل: ادامهٔ حرکت به بالا",
                legs=(PathLeg("up", spot_i, target_zone),),
                narrative_fa=(
                    f"غلبهٔ خریدار کال بدون سقف قوی فروش کال در {target_zone:,}; "
                    f"مسیر کوتاه‌مدت بیشتر **یک‌طرفه به سمت هدف** دیده می‌شود."
                ),
                likelihood="primary",
            )
        )

    # 4) Straight down
    if bearish_puts and c.buyer_call < c.buyer_put * 0.9 and not any(
        p.id == "down_then_up" for p in paths
    ):
        paths.append(
            MovementPath(
                id="down_continuation",
                title_fa="مسیر محتمل: فشار به پایین",
                legs=(PathLeg("down", spot_i, support_zone),),
                narrative_fa=(
                    f"flow محافظتی غالب است؛ مسیر اولیه به سمت **{support_zone:,}** "
                    f"قبل از هر برگشت صعودی محتمل‌تر است."
                ),
                likelihood="primary" if not paths else "alternate",
            )
        )

    # 5) Range / chop
    if not paths:
        paths.append(
            MovementPath(
                id="range",
                title_fa="مسیر محتمل: نوسان بین دو سطح",
                legs=(
                    PathLeg("up", spot_i, target_zone),
                    PathLeg("down", target_zone, support_zone),
                ),
                narrative_fa=(
                    f"flow متعادل است؛ **امکان دارد** قیمت بین **{support_zone:,}** و **{target_zone:,}** "
                    "چند بار بالا-پایین شود بدون break قطعی."
                ),
                likelihood="primary",
            )
        )

    primary = next(p for p in paths if p.likelihood == "primary")
    alternate = next((p for p in paths if p.likelihood == "alternate"), None)
    if alternate is None:
        for p in paths:
            if p is not primary:
                alternate = p
                break
    return primary, alternate


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
            "_منطق: مسیر از تضاد/هم‌راستایی خرید کال (هدف بالا) و خرید/فروش در strikeهای کلیدی ساخته شده._"
        )
    return "\n".join(lines)
