"""باند حرکت و زون سررسید از کتاب آپشن دریبیت.

مقصد مسیر از خوشهٔ موقعیت‌باز نزدیک قیمت می‌آید، نه از میانگین معامله‌های پنجره.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

DERIBIT = "https://www.deribit.com/api/v2/public"

# جابه‌جایی کمتر از این، نسبت به قیمت، «تغییر محسوس» نیست.
SHIFT_PCT = 0.0035
ZONE_SHARE = 0.35
ZONE_SPAN = 0.015


@dataclass(frozen=True)
class ExpiryBand:
    expiry: str
    hours_left: float
    iv_pct: float
    band_low: int
    band_high: int


@dataclass(frozen=True)
class StrikeZone:
    low: int
    high: int
    mid: int
    weight: float


@dataclass(frozen=True)
class Compass:
    spot: float
    expiries: tuple[ExpiryBand, ...]
    zone_down: StrikeZone | None
    zone_up: StrikeZone | None
    path_side: str  # "down" | "up" | ""
    path_level: int | None

    @property
    def primary(self) -> ExpiryBand | None:
        return self.expiries[0] if self.expiries else None


@dataclass(frozen=True)
class PriorCompass:
    band_low: int | None = None
    down_zone_mid: int | None = None
    up_zone_mid: int | None = None


def expiry_datetime(code: str) -> datetime:
    """سررسید دریبیت، ۰۸:۰۰ UTC."""
    return datetime.strptime(code, "%d%b%y").replace(hour=8, tzinfo=timezone.utc)


def _parse_instrument(name: str) -> tuple[str, float, str] | None:
    parts = name.split("-")
    if len(parts) < 4:
        return None
    try:
        strike = float(parts[2])
    except ValueError:
        return None
    opt = "call" if parts[3].upper().startswith("C") else "put"
    return parts[1], strike, opt


def expected_move(spot: float, iv_pct: float, hours_left: float) -> float:
    if spot <= 0 or iv_pct <= 0 or hours_left <= 0:
        return 0.0
    years = hours_left / 24.0 / 365.0
    return spot * (iv_pct / 100.0) * (years ** 0.5)


def _atm_iv(rows: list[tuple[float, str, float]], spot: float) -> float | None:
    """میانگین mark IV کال و پوتِ نزدیک‌ترین استرایک به قیمت."""
    if spot <= 0 or not rows:
        return None
    nearest = min(rows, key=lambda row: abs(row[0] - spot))[0]
    ivs = [iv for strike, _opt, iv in rows if strike == nearest and iv > 0]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def _cluster(points: list[tuple[float, float]]) -> StrikeZone | None:
    if not points:
        return None
    ordered = sorted((k, w) for k, w in points if w > 0)
    if not ordered:
        return None
    total = sum(w for _, w in ordered)
    best: list[tuple[float, float]] | None = None
    best_w = 0.0
    for i, (start, _) in enumerate(ordered):
        window: list[tuple[float, float]] = []
        weight = 0.0
        for strike, w in ordered[i:]:
            if strike > start * (1.0 + ZONE_SPAN):
                break
            window.append((strike, w))
            weight += w
        if weight > best_w:
            best_w = weight
            best = window
    if best is None or total <= 0 or best_w / total < ZONE_SHARE:
        return None
    mid = max(best, key=lambda item: item[1])[0]
    return StrikeZone(
        low=int(round(best[0][0])),
        high=int(round(best[-1][0])),
        mid=int(round(mid)),
        weight=best_w,
    )


def _bands(
    by_expiry: dict[str, list[tuple[float, str, float, float]]],
    spot: float,
    now: datetime,
) -> list[ExpiryBand]:
    bands: list[ExpiryBand] = []
    for expiry, rows in by_expiry.items():
        try:
            when = expiry_datetime(expiry)
        except ValueError:
            continue
        hours = (when - now).total_seconds() / 3600.0
        if hours < 0.5:
            continue
        iv = _atm_iv([(s, o, iv) for s, o, iv, _oi in rows], spot)
        if iv is None:
            continue
        move = expected_move(spot, iv, hours)
        if move <= 0:
            continue
        bands.append(
            ExpiryBand(
                expiry=expiry,
                hours_left=hours,
                iv_pct=iv,
                band_low=int(round(spot - move)),
                band_high=int(round(spot + move)),
            )
        )
    bands.sort(key=lambda band: band.hours_left)
    return bands[:3]


def build_compass(
    books: list[dict[str, Any]],
    spot: float,
    *,
    greeks: dict[str, float] | None = None,
    now: datetime | None = None,
) -> Compass | None:
    """سه سررسید نزدیک، باند هر کدام، و زون پایین/بالا روی نزدیک‌ترین سررسید."""
    if spot <= 0 or not books:
        return None
    moment = now or datetime.now(timezone.utc)
    greeks = greeks or {}
    by_expiry: dict[str, list[tuple[float, str, float, float]]] = {}
    for row in books:
        parsed = _parse_instrument(str(row.get("instrument_name") or ""))
        if parsed is None:
            continue
        expiry, strike, opt = parsed
        oi = float(row.get("open_interest") or 0)
        if oi <= 0:
            continue
        try:
            iv = float(row.get("mark_iv") or 0)
        except (TypeError, ValueError):
            iv = 0.0
        by_expiry.setdefault(expiry, []).append((strike, opt, iv, oi))

    bands = _bands(by_expiry, spot, moment)
    if not bands:
        return None
    primary = bands[0]
    rows = by_expiry.get(primary.expiry, [])
    down: list[tuple[float, float]] = []
    up: list[tuple[float, float]] = []
    strike_gamma: dict[float, float] = {}
    for name, gamma in greeks.items():
        parsed = _parse_instrument(name)
        if parsed is None or parsed[0] != primary.expiry:
            continue
        strike_gamma[parsed[1]] = strike_gamma.get(parsed[1], 0.0) + abs(float(gamma))

    grouped: dict[float, float] = {}
    for strike, _opt, _iv, oi in rows:
        gamma = strike_gamma.get(strike, 0.0)
        # گاما موجودی را سنگین‌تر می‌کند؛ بدون گاما خودِ موقعیت باز وزن است.
        grouped[strike] = grouped.get(strike, 0.0) + oi * (1.0 + gamma * spot)

    lo = min(primary.band_low, spot * 0.88)
    hi = max(primary.band_high, spot * 1.12)
    for strike, weight in grouped.items():
        if strike < spot and strike >= lo:
            down.append((strike, weight))
        elif strike > spot and strike <= hi:
            up.append((strike, weight))

    zone_down = _cluster(down)
    zone_up = _cluster(up)
    side, level = _path_side(zone_down, zone_up)
    return Compass(
        spot=spot,
        expiries=tuple(bands),
        zone_down=zone_down,
        zone_up=zone_up,
        path_side=side,
        path_level=level,
    )


def _path_side(
    zone_down: StrikeZone | None,
    zone_up: StrikeZone | None,
) -> tuple[str, int | None]:
    down_w = zone_down.weight if zone_down else 0.0
    up_w = zone_up.weight if zone_up else 0.0
    if zone_down and down_w >= up_w * 1.25:
        return "down", zone_down.mid
    if zone_up and up_w >= down_w * 1.25:
        return "up", zone_up.mid
    return "", None


def classify_shift(
    prior: PriorCompass | None,
    compass: Compass,
) -> str:
    """down/up فقط وقتی باند و زون همان سمت هر دو جابه‌جا شده باشند."""
    if prior is None or prior.band_low is None or not compass.primary:
        return "unknown"
    spot = compass.spot
    thresh = spot * SHIFT_PCT
    band_delta = compass.primary.band_low - prior.band_low
    if (
        compass.zone_down
        and prior.down_zone_mid
        and band_delta <= -thresh
        and compass.zone_down.mid - prior.down_zone_mid <= -thresh
    ):
        return "down"
    if (
        compass.zone_up
        and prior.up_zone_mid
        and band_delta >= thresh
        and compass.zone_up.mid - prior.up_zone_mid >= thresh
    ):
        return "up"
    return "flat"


def apply_shift(compass: Compass, shift: str) -> Compass:
    """اگر باند و زون با هم به یک سمت رفته باشند، مقصد همان زون است."""
    if shift == "down" and compass.zone_down:
        return Compass(
            spot=compass.spot,
            expiries=compass.expiries,
            zone_down=compass.zone_down,
            zone_up=compass.zone_up,
            path_side="down",
            path_level=compass.zone_down.mid,
        )
    if shift == "up" and compass.zone_up:
        return Compass(
            spot=compass.spot,
            expiries=compass.expiries,
            zone_down=compass.zone_down,
            zone_up=compass.zone_up,
            path_side="up",
            path_level=compass.zone_up.mid,
        )
    return compass


def _hours_fa(hours: float) -> str:
    if hours >= 48:
        return f"{hours / 24:.1f} روز"
    return f"{hours:.1f} ساعت"


def format_compass_paragraph(
    compass: Compass,
    shift: str,
    *,
    buyer_call: float = 0,
    buyer_put: float = 0,
    seller_call: float = 0,
    seller_put: float = 0,
    eff_buyer_call: float = 0,
    eff_buyer_put: float = 0,
    eff_seller_call: float = 0,
    eff_seller_put: float = 0,
) -> str:
    primary = compass.primary
    assert primary is not None
    spot = compass.spot
    lines = [
        "**قطب‌نمای سررسید**",
        (
            f"قیمت {spot:,.0f} دلار. نزدیک‌ترین سررسید {primary.expiry}، "
            f"حدود {_hours_fa(primary.hours_left)} مانده. "
            f"باند حرکت این سررسید {primary.band_low:,} تا {primary.band_high:,} است."
        ),
    ]
    extra = [band for band in compass.expiries[1:]]
    if extra:
        bits = [
            f"{band.expiry} ({band.band_low:,} تا {band.band_high:,})"
            for band in extra
        ]
        lines.append("سررسیدهای بعد جدا مانده‌اند: " + "؛ ".join(bits) + ".")

    if compass.zone_down:
        z = compass.zone_down
        lines.append(
            f"زون پایین {z.low:,} تا {z.high:,} است؛ وسطش حدود {z.mid:,}."
        )
    else:
        lines.append("زون پایین متمرکز داخل باند دیده نشد.")
    if compass.zone_up:
        z = compass.zone_up
        lines.append(
            f"زون بالا {z.low:,} تا {z.high:,} است؛ وسطش حدود {z.mid:,}."
        )
    else:
        lines.append("زون بالا متمرکز داخل باند دیده نشد.")

    lines.append(
        "**جریان تا این لحظه**\n"
        f"خریدار کال {buyer_call:,.1f} قرارداد (ارزش {eff_buyer_call:,.0f}). "
        f"خریدار پوت {buyer_put:,.1f} (ارزش {eff_buyer_put:,.0f}). "
        f"فروشنده کال {seller_call:,.1f} (ارزش {eff_seller_call:,.0f}). "
        f"فروشنده پوت {seller_put:,.1f} (ارزش {eff_seller_put:,.0f})."
    )

    if shift == "down":
        lines.append(
            "**جابه‌جایی**\n"
            "باند پایین و زون پایین نسبت به گزارش قبل هر دو پایین آمده‌اند. "
            "این هم‌جهتی، حرکت پرمومنتوم به سمت زون پایین است."
        )
    elif shift == "up":
        lines.append(
            "**جابه‌جایی**\n"
            "باند پایین و زون بالا نسبت به گزارش قبل هر دو بالا رفته‌اند. "
            "این هم‌جهتی، حرکت پرمومنتوم به سمت زون بالا است."
        )
    elif shift == "flat":
        lines.append(
            "**جابه‌جایی**\n"
            "باند و زون نسبت به گزارش قبل با هم به یک سمت نرفته‌اند. "
            "مومنتوم تازه اعلام نمی‌شود."
        )
    else:
        lines.append(
            "**جابه‌جایی**\n"
            "گزارش قبلی برای مقایسهٔ باند و زون نیست. این سطح ثبت شد؛ "
            "جابه‌جایی از گزارش بعد گفته می‌شود."
        )

    if compass.path_level and compass.path_side == "down":
        lines.append(
            f"**حرکت**\nاز {spot:,.0f} به حدود {compass.path_level:,}. "
            "مقصد وسط زون موقعیت‌باز زیر قیمت است، نه میانگین استرایک‌های معامله‌شده."
        )
    elif compass.path_level and compass.path_side == "up":
        lines.append(
            f"**حرکت**\nاز {spot:,.0f} به حدود {compass.path_level:,}. "
            "مقصد وسط زون موقعیت‌باز بالای قیمت است، نه میانگین استرایک‌های معامله‌شده."
        )
    else:
        lines.append(
            "**حرکت**\nمقصد اول نامشخص. "
            "داخل باند، یک زون غالب برای بستن مسیر وجود ندارد."
        )

    lines.append(
        "**جمع‌بندی**\n"
        + (
            f"تا سررسید {primary.expiry} سطح قابل‌اشاره حدود {compass.path_level:,} است "
            "و زون آهنرباست، نه قیمتی که باید دقیق لمس شود."
            if compass.path_level
            else f"تا سررسید {primary.expiry} باند و زون ثبت شد، بدون مقصد تک‌رقمی."
        )
    )
    return "\n\n".join(lines)


def fetch_book() -> list[dict[str, Any]]:
    r = httpx.get(
        f"{DERIBIT}/get_book_summary_by_currency",
        params={"currency": "BTC", "kind": "option"},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["result"]


def fetch_gamma_for(names: list[str], *, limit: int = 30) -> dict[str, float]:
    """گامای پرتعدادترین قراردادهای نزدیک. شکست یک تیکر بقیه را حذف نمی‌کند."""
    out: dict[str, float] = {}
    with httpx.Client(timeout=15.0) as client:
        for name in names[:limit]:
            try:
                tr = client.get(f"{DERIBIT}/ticker", params={"instrument_name": name})
                if tr.status_code != 200:
                    continue
                gamma = float((tr.json().get("result") or {}).get("greeks", {}).get("gamma") or 0)
            except (TypeError, ValueError, httpx.HTTPError):
                continue
            if gamma:
                out[name] = gamma
    return out


def names_for_gamma(books: list[dict[str, Any]], spot: float, expiry: str) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for row in books:
        parsed = _parse_instrument(str(row.get("instrument_name") or ""))
        if parsed is None or parsed[0] != expiry:
            continue
        oi = float(row.get("open_interest") or 0)
        if oi <= 0 or not (spot * 0.88 <= parsed[1] <= spot * 1.12):
            continue
        ranked.append((oi, str(row["instrument_name"])))
    ranked.sort(reverse=True)
    return [name for _oi, name in ranked]


def live_compass(spot: float) -> Compass | None:
    try:
        books = fetch_book()
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None
    draft = build_compass(books, spot)
    if draft is None or draft.primary is None:
        return None
    greeks = fetch_gamma_for(names_for_gamma(books, spot, draft.primary.expiry))
    if not greeks:
        return draft
    return build_compass(books, spot, greeks=greeks) or draft
