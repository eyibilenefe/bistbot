from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CostInputs:
    broker_fee: float
    taxes: float
    base_slippage: float
    atr20_current: float
    atr20_60d_median: float


def volatility_adjusted_slippage(inputs: CostInputs) -> float:
    baseline = inputs.atr20_60d_median if inputs.atr20_60d_median > 0 else inputs.atr20_current
    if baseline <= 0:
        return inputs.base_slippage
    multiplier = max(1.0, inputs.atr20_current / baseline)
    return inputs.base_slippage * multiplier


def estimated_round_trip_cost(inputs: CostInputs) -> float:
    return (
        inputs.broker_fee
        + inputs.taxes
        + inputs.base_slippage
        + volatility_adjusted_slippage(inputs)
    )
