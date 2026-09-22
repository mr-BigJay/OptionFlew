from app.exchange_fee_profiles import (
    DEFAULT_FEE_PROFILE_ID,
    get_fee_profile,
    list_fee_profiles,
    resolve_fee_rate,
)


def test_bitunix_profile_exists() -> None:
    p = get_fee_profile("bitunix_usdt_vip0")
    assert p.exchange_en == "Bitunix"
    assert p.taker_rate == 0.0006


def test_resolve_taker_default() -> None:
    assert resolve_fee_rate(None) == get_fee_profile(DEFAULT_FEE_PROFILE_ID).taker_rate


def test_list_profiles_non_empty() -> None:
    assert len(list_fee_profiles()) >= 5
