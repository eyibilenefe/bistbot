from __future__ import annotations

import math
from dataclasses import dataclass

from bistbot.domain.models import PortfolioPosition, ProposedPosition


@dataclass(slots=True)
class RiskEvaluation:
    accepted: bool
    violations: list[str]
    projected_risk_exposure: float
    projected_sector_exposure: float


def calculate_position_size(
    *,
    portfolio_equity: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade: float = 0.01,
) -> int:
    per_share_risk = entry_price - stop_price
    if per_share_risk <= 0:
        raise ValueError("Entry price must be above stop price for long positions.")
    risk_budget = portfolio_equity * risk_per_trade
    return max(1, math.floor(risk_budget / per_share_risk))


def portfolio_risk_exposure(
    positions: list[PortfolioPosition | ProposedPosition], *, portfolio_equity: float
) -> float:
    if portfolio_equity <= 0:
        return 0.0
    open_risk = sum(max(position.last_price - position.stop_price, 0.0) * position.quantity for position in positions)
    return open_risk / portfolio_equity


def sector_exposure(
    positions: list[PortfolioPosition | ProposedPosition],
    *,
    portfolio_equity: float,
    sector: str,
) -> float:
    if portfolio_equity <= 0:
        return 0.0
    exposure = sum(
        position.last_price * position.quantity
        for position in positions
        if position.sector == sector
    )
    return exposure / portfolio_equity


def evaluate_position_constraints(
    *,
    existing_positions: list[PortfolioPosition],
    proposed_position: ProposedPosition,
    portfolio_equity: float,
    correlation_map: dict[tuple[str, str], float] | None = None,
    max_sector_positions: int = 2,
    max_sector_exposure: float = 0.40,
    max_correlation: float = 0.75,
    max_total_portfolio_risk: float = 0.05,
) -> RiskEvaluation:
    violations: list[str] = []
    correlation_map = correlation_map or {}

    sector_positions = [
        position for position in existing_positions if position.sector == proposed_position.sector
    ]
    if len(sector_positions) >= max_sector_positions:
        violations.append("sector_position_limit")

    positions_with_candidate: list[PortfolioPosition | ProposedPosition] = [
        *existing_positions,
        proposed_position,
    ]
    projected_sector = sector_exposure(
        positions_with_candidate,
        portfolio_equity=portfolio_equity,
        sector=proposed_position.sector,
    )
    if projected_sector > max_sector_exposure:
        violations.append("sector_exposure_limit")

    projected_risk = portfolio_risk_exposure(
        positions_with_candidate,
        portfolio_equity=portfolio_equity,
    )
    if projected_risk > max_total_portfolio_risk:
        violations.append("total_portfolio_risk_limit")

    for position in existing_positions:
        key = tuple(sorted((position.symbol, proposed_position.symbol)))
        correlation = correlation_map.get(key, 0.0)
        if correlation > max_correlation:
            violations.append(f"correlation_limit:{position.symbol}")
            break

    return RiskEvaluation(
        accepted=not violations,
        violations=violations,
        projected_risk_exposure=projected_risk,
        projected_sector_exposure=projected_sector,
    )
