from optionflow.flow_analyzer import EffectiveBucket, FlowAnalysis, FlowBucket
from optionflow.path_scenario import MovementPath, PathLeg
from optionflow.scenario_narrative import format_narrative_scenario


def test_up_then_down_invalidation_does_not_cancel_path_to_c() -> None:
    main = FlowAnalysis(
        spot=84075,
        trade_count=10,
        window_label="day",
        contracts=FlowBucket(buyer_call=2, seller_put=1, buyer_put=1, seller_call=1),
        effective_usd=EffectiveBucket(),
    )
    path = MovementPath(
        id="primary",
        title_fa="t",
        legs=(
            PathLeg("up", 84075, 86841),
            PathLeg("down", 86841, 82226),
        ),
        narrative_fa="s",
        likelihood="primary",
    )
    text = format_narrative_scenario(
        main,
        bias="bullish",
        spot=84075,
        support=82226,
        target=86841,
        path_primary=path,
        path_alternate=None,
    )
    assert "لغو سناریوی صعود اول و مسیر بعدی به 82,226" not in text
    assert "اول 86,841، بعد اصلاح به 82,226" in text
    assert "کندل ۱۵ دقیقه بالای 82,226" not in text
