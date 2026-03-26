from __future__ import annotations

from dataclasses import replace

from bistbot.domain.enums import CorporateActionType
from bistbot.domain.models import CorporateAction, PortfolioPosition


def adjust_position_for_corporate_action(
    position: PortfolioPosition, action: CorporateAction
) -> tuple[PortfolioPosition, float]:
    if position.symbol != action.symbol:
        return position, 0.0

    adjusted = replace(position)
    adjusted.last_corporate_action_at = action.effective_at
    cash_delta = 0.0

    if action.action_type in {CorporateActionType.SPLIT, CorporateActionType.BONUS}:
        if action.factor <= 0:
            raise ValueError("Corporate action factor must be positive.")
        adjusted.adjustment_factor *= action.factor
        adjusted.quantity = int(adjusted.quantity * action.factor)
        adjusted.adjusted_entry_price = position.entry_price / action.factor
        adjusted.adjusted_stop_price = position.stop_price / action.factor
        adjusted.adjusted_target_price = position.target_price / action.factor
    elif action.action_type == CorporateActionType.CASH_DIVIDEND:
        cash_delta = action.cash_amount * adjusted.quantity
        adjusted.adjusted_entry_price = max(position.entry_price - action.cash_amount, 0.0)
        adjusted.adjusted_stop_price = max(position.stop_price - action.cash_amount, 0.0)
        adjusted.adjusted_target_price = max(position.target_price - action.cash_amount, 0.0)

    return adjusted, cash_delta
