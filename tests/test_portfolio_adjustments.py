from __future__ import annotations

from datetime import UTC, datetime

from bistbot.domain.enums import CorporateActionType, PositionStatus
from bistbot.domain.models import CorporateAction, PortfolioPosition
from bistbot.services.portfolio_adjustments import adjust_position_for_corporate_action


def test_split_adjusts_quantity_and_price_anchors() -> None:
    position = PortfolioPosition(
        id="pos-1",
        symbol="AKBNK",
        sector="banking",
        status=PositionStatus.OPEN,
        entry_price=100.0,
        stop_price=95.0,
        target_price=115.0,
        quantity=10,
        last_price=104.0,
        opened_at=datetime(2026, 3, 20, tzinfo=UTC),
        adjusted_entry_price=100.0,
        adjusted_stop_price=95.0,
        adjusted_target_price=115.0,
    )
    action = CorporateAction(
        symbol="AKBNK",
        action_type=CorporateActionType.SPLIT,
        effective_at=datetime(2026, 3, 25, tzinfo=UTC),
        factor=2.0,
        reference="split-1",
    )

    adjusted, cash_delta = adjust_position_for_corporate_action(position, action)

    assert adjusted.quantity == 20
    assert adjusted.adjusted_entry_price == 50.0
    assert adjusted.adjusted_stop_price == 47.5
    assert cash_delta == 0.0


def test_cash_dividend_adjusts_price_and_adds_cash() -> None:
    position = PortfolioPosition(
        id="pos-1",
        symbol="AKBNK",
        sector="banking",
        status=PositionStatus.OPEN,
        entry_price=100.0,
        stop_price=95.0,
        target_price=115.0,
        quantity=10,
        last_price=104.0,
        opened_at=datetime(2026, 3, 20, tzinfo=UTC),
        adjusted_entry_price=100.0,
        adjusted_stop_price=95.0,
        adjusted_target_price=115.0,
    )
    action = CorporateAction(
        symbol="AKBNK",
        action_type=CorporateActionType.CASH_DIVIDEND,
        effective_at=datetime(2026, 3, 25, tzinfo=UTC),
        cash_amount=4.0,
        reference="dividend-1",
    )

    adjusted, cash_delta = adjust_position_for_corporate_action(position, action)

    assert adjusted.adjusted_entry_price == 96.0
    assert adjusted.adjusted_stop_price == 91.0
    assert cash_delta == 40.0
