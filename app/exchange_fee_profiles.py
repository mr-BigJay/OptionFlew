"""پروفایل کارمزد فیوچرز USDT (سطح پایه / VIP0) — برای شبیه‌سازی پوزیشن فرضی.

نرخ‌ها به‌صورت اعشاری (۰.۰۰۰۵ = ۰.۰۵٪). در موتور پوزیشن برای باز و بست
معمولاً کارمزد taker (مارکت) اعمال می‌شود؛ maker برای TP/SL با لیمیت در آینده.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeeSide = Literal["taker", "maker"]

DEFAULT_FEE_PROFILE_ID = "binance_usdt_vip0"


@dataclass(frozen=True)
class ExchangeFeeProfile:
    id: str
    label_fa: str
    exchange_en: str
    maker_rate: float
    taker_rate: float
    tier_note_fa: str
    source_note_fa: str


PROFILES: tuple[ExchangeFeeProfile, ...] = (
    ExchangeFeeProfile(
        id="binance_usdt_vip0",
        label_fa="بایننس — USDT-M",
        exchange_en="Binance",
        maker_rate=0.0002,
        taker_rate=0.0005,
        tier_note_fa="VIP 0 · فیوچرز USDT",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۵٪ (USDT-M)",
    ),
    ExchangeFeeProfile(
        id="bybit_usdt_vip0",
        label_fa="بای‌بیت — USDT",
        exchange_en="Bybit",
        maker_rate=0.0002,
        taker_rate=0.00055,
        tier_note_fa="Non-VIP · Perpetual USDT",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۵۵٪",
    ),
    ExchangeFeeProfile(
        id="okx_usdt_vip0",
        label_fa="OKX — USDT",
        exchange_en="OKX",
        maker_rate=0.0002,
        taker_rate=0.0005,
        tier_note_fa="سطح پایه · Swap USDT",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۵٪",
    ),
    ExchangeFeeProfile(
        id="bitunix_usdt_vip0",
        label_fa="بیت‌یونیکس — USDT",
        exchange_en="Bitunix",
        maker_rate=0.0002,
        taker_rate=0.0006,
        tier_note_fa="VIP 0 · Futures USDT",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۶٪",
    ),
    ExchangeFeeProfile(
        id="gate_usdt_vip0",
        label_fa="Gate.io — USDT",
        exchange_en="Gate.io",
        maker_rate=0.0002,
        taker_rate=0.0005,
        tier_note_fa="سطح پایه · Perpetual",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۵٪",
    ),
    ExchangeFeeProfile(
        id="mexc_usdt_vip0",
        label_fa="MEXC — USDT",
        exchange_en="MEXC",
        maker_rate=0.0002,
        taker_rate=0.0006,
        tier_note_fa="سطح پایه · Futures",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۶٪",
    ),
    ExchangeFeeProfile(
        id="kucoin_usdt_vip0",
        label_fa="KuCoin — USDT",
        exchange_en="KuCoin",
        maker_rate=0.0002,
        taker_rate=0.0006,
        tier_note_fa="سطح پایه · Futures",
        source_note_fa="Maker ۰.۰۲٪ · Taker ۰.۰۶٪",
    ),
)

_BY_ID = {p.id: p for p in PROFILES}


def list_fee_profiles() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for p in PROFILES:
        out.append(
            {
                "id": p.id,
                "label_fa": p.label_fa,
                "exchange_en": p.exchange_en,
                "maker_rate": p.maker_rate,
                "taker_rate": p.taker_rate,
                "maker_pct": round(p.maker_rate * 100, 4),
                "taker_pct": round(p.taker_rate * 100, 4),
                "tier_note_fa": p.tier_note_fa,
                "source_note_fa": p.source_note_fa,
            }
        )
    return out


def get_fee_profile(profile_id: str | None) -> ExchangeFeeProfile:
    pid = (profile_id or "").strip() or DEFAULT_FEE_PROFILE_ID
    return _BY_ID.get(pid, _BY_ID[DEFAULT_FEE_PROFILE_ID])


def resolve_fee_rate(
    profile_id: str | None,
    *,
    side: FeeSide = "taker",
    legacy_fee_rate: float | None = None,
) -> float:
    """نرخ مؤثر برای محاسبه کارمزد پوزیشن."""
    if profile_id == "legacy_manual" and legacy_fee_rate is not None:
        return max(0.0, float(legacy_fee_rate))
    p = get_fee_profile(profile_id)
    if side == "maker":
        return p.maker_rate
    return p.taker_rate


def fee_profile_summary_fa(profile_id: str | None) -> str:
    p = get_fee_profile(profile_id)
    return f"{p.label_fa} · Taker {p.taker_rate * 100:.3f}٪"
