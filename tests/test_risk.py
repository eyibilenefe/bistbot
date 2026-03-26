from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bistbot.domain.enums import PositionStatus
from bistbot.domain.models import PortfolioPosition, ProposedPosition
from bistbot.services.position_management import should_keep_position_open
from bistbot.services.risk import (
    calculate_position_size,
    evaluate_position_constraints,
    portfolio_risk_exposure,
)


def test_position_sizing_uses_one_percent_risk_budget() -> None:
    quantity = calculate_position_size(
        portfolio_equity=30_000.0,
        entry_price=100.0,
        stop_price=95.0,
    )

    assert quantity == 60


def test_portfolio_constraints_enforce_sector_correlation_and_total_risk_caps() -> None:
    existing = [
        PortfolioPosition(
            id="pos-1",
            symbol="AKBNK",
            sector="banking",
            status=PositionStatus.OPEN,
            entry_price=100.0,
            stop_price=95.0,
            target_price=112.0,
            quantity=60,
            last_price=102.0,
            opened_at=datetime(2026, 3, 20, tzinfo=UTC),
        ),
        PortfolioPosition(
            id="pos-2",
            symbol="YKBNK",
            sector="banking",
            status=PositionStatus.OPEN,
            entry_price=80.0,
            stop_price=76.0,
            target_price=90.0,
            quantity=50,
            last_price=81.0,
            opened_at=datetime(2026, 3, 19, tzinfo=UTC),
        ),
    ]
    proposed = ProposedPosition(
        symbol="GARAN",
        sector="banking",
        entry_price=120.0,
        stop_price=114.0,
        last_price=120.0,
        quantity=20,
    )

    evaluation = evaluate_position_constraints(
        existing_positions=existing,
        proposed_position=proposed,
        portfolio_equity=30_000.0,
        correlation_map={("AKBNK", "GARAN"): 0.80},
    )

    assert not evaluation.accepted
    assert "sector_position_limit" in evaluation.violations
    assert "correlation_limit:AKBNK" in evaluation.violations


def test_portfolio_risk_and_soft_holding_extension() -> None:
    positions = [
        ProposedPosition(
            symbol="TUPRS",
            sector="energy",
            entry_price=150.0,
            stop_price=140.0,
            last_price=152.0,
            quantity=10,
        )
    ]
    exposure = portfolio_risk_exposure(positions, portfolio_equity=30_000.0)

    assert exposure == (12 * 10) / 30_000.0
    assert should_keep_position_open(
        opened_at=datetime.now(UTC) - timedelta(days=9),
        as_of=datetime.now(UTC),
        daily_close=155.0,
        daily_ema20=150.0,
        daily_ema50=145.0,
    )
