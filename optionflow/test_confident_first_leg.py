from optionflow.flow_analyzer import (
    EffectiveBucket,
    FlowAnalysis,
    FlowBucket,
    confident_first_strike,
    dominant_strike_in_band,
)


def _flow(**kwargs) -> FlowAnalysis:
    base = dict(
        spot=84000.0,
        trade_count=20,
        window_label="4h",
        window_hours=4.0,
        contracts=FlowBucket(buyer_call=20, seller_put=2, buyer_put=4, seller_call=2),
        effective_usd=EffectiveBucket(),
    )
    base.update(kwargs)
    return FlowAnalysis(**base)


def test_dominant_strike_rejects_diffuse_book() -> None:
    strikes = {85000: 4, 86000: 4, 87000: 4, 88000: 3}
    assert (
        dominant_strike_in_band(strikes, 84000, pct_lo=1.002, pct_hi=1.085) is None
    )


def test_dominant_strike_returns_heaviest_not_average() -> None:
    strikes = {86000: 12, 90000: 4}
    assert dominant_strike_in_band(strikes, 84000, pct_lo=1.002, pct_hi=1.12) == 86000


def test_confident_b_is_the_heaviest_call_strike() -> None:
    main = _flow(call_buy_by_strike={87000: 16, 85000: 4})
    assert confident_first_strike(main, "up") == 87000