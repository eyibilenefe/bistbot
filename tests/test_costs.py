from __future__ import annotations

from bistbot.services.costs import CostInputs, estimated_round_trip_cost, volatility_adjusted_slippage


def test_volatility_adjusted_slippage_increases_when_current_atr_is_higher() -> None:
    inputs = CostInputs(
        broker_fee=0.0015,
        taxes=0.0005,
        base_slippage=0.0010,
        atr20_current=4.0,
        atr20_60d_median=2.0,
    )

    assert volatility_adjusted_slippage(inputs) == 0.0020
    assert estimated_round_trip_cost(inputs) == 0.0050
