from optionflow.flow_analyzer import (
    EffectiveBucket,
    FlowAnalysis,
    FlowBucket,
    confident_first_strike,
    dominant_strike_in_band,
)
from optionflow.path_scenario import MovementPath, PathLeg
from optionflow.scenario_narrative import format_narrative_scenario, resolve_scenario_plan


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


def _up_path() -> MovementPath:
    return MovementPath(
        id="up_continuation",
        title_fa="t",
        legs=(PathLeg("up", 84000, 85260),),
        narrative_fa="s",
        likelihood="primary",
    )


def test_dominant_strike_rejects_diffuse_book() -> None:
    strikes = {85000: 4, 86000: 4, 87000: 4, 88000: 3}
    assert (
        dominant_strike_in_band(strikes, 84000, pct_lo=1.002, pct_hi=1.085) is None
    )


def test_dominant_strike_returns_heaviest_not_average() -> None:
    strikes = {86000: 12, 90000: 4}
    assert dominant_strike_in_band(strikes, 84000, pct_lo=1.002, pct_hi=1.12) == 86000


def test_unclear_first_leg_when_calls_are_spread_out() -> None:
    main = _flow(
        call_buy_by_strike={85000: 5, 86000: 5, 87000: 5, 88000: 5},
    )
    text = format_narrative_scenario(
        main,
        bias="bullish",
        spot=84000,
        support=82740,
        target=85260,
        path_primary=_up_path(),
        path_alternate=None,
    )
    assert "مقصد اول نامشخص" in text
    assert "85,260" not in text
    plan = resolve_scenario_plan(
        main,
        support=82740,
        target=85260,
        path_primary=_up_path(),
        path_alternate=None,
    )
    assert plan is not None
    assert plan.first_confident is False


def test_confident_b_is_the_heaviest_call_strike() -> None:
    main = _flow(call_buy_by_strike={87000: 16, 85000: 4})
    assert confident_first_strike(main, "up") == 87000
    text = format_narrative_scenario(
        main,
        bias="bullish",
        spot=84000,
        support=82740,
        target=85260,
        path_primary=_up_path(),
        path_alternate=None,
    )
    assert "87,000" in text
    assert "مقصد اول نامشخص" not in text
    plan = resolve_scenario_plan(
        main,
        support=82740,
        target=85260,
        path_primary=_up_path(),
        path_alternate=None,
    )
    assert plan is not None and plan.first_confident and plan.b == 87000
