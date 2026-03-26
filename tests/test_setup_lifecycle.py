from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bistbot.domain.enums import SetupStatus, StrategyFamily
from bistbot.domain.models import SetupCandidate
from bistbot.services.setup_lifecycle import (
    approve_setup,
    compute_confluence_score,
    quality_gate,
    refresh_setup_status,
    validate_manual_entry,
)


def make_setup(index: int, *, score: float) -> SetupCandidate:
    now = datetime.now(UTC)
    return SetupCandidate(
        id=f"setup-{index}",
        symbol="AKBNK",
        cluster_id="banking:low",
        strategy_id="strategy-1",
        strategy_family=StrategyFamily.TREND_FOLLOWING,
        score=score,
        entry_low=10.0,
        entry_high=10.5,
        stop=9.0,
        target=12.0,
        confidence=0.80,
        confluence_score=0.85,
        expected_r=2.2,
        created_at=now,
        expires_at=now + timedelta(hours=6),
    )


def test_quality_gate_keeps_only_top_decile_candidates() -> None:
    candidates = [make_setup(index, score=1 - (index * 0.01)) for index in range(20)]

    gated = quality_gate(candidates)

    assert len(gated) == 2
    assert [setup.id for setup in gated] == ["setup-0", "setup-1"]


def test_setup_approval_and_manual_entry_validation() -> None:
    now = datetime.now(UTC)
    setup = approve_setup(make_setup(1, score=0.9), now=now)

    assert setup.status == SetupStatus.APPROVED_PENDING_ENTRY
    validate_manual_entry(setup, now=now + timedelta(minutes=5))


def test_setup_is_expired_or_invalidated_when_conditions_break() -> None:
    now = datetime.now(UTC)
    expired = refresh_setup_status(
        make_setup(2, score=0.8),
        now=now + timedelta(hours=7),
        daily_regime_valid=True,
        entry_distance_atr=0.0,
        stop_logic_intact=True,
    )
    invalidated = refresh_setup_status(
        make_setup(3, score=0.7),
        now=now,
        daily_regime_valid=False,
        entry_distance_atr=0.0,
        stop_logic_intact=True,
    )

    assert expired.status == SetupStatus.EXPIRED
    assert invalidated.status == SetupStatus.INVALIDATED


def test_confluence_score_reaches_full_weight_when_all_checks_pass() -> None:
    score = compute_confluence_score(
        daily_regime_valid=True,
        trend_signal=True,
        momentum_signal=True,
        volume_confirmation=True,
        entry_zone_proximity=1.0,
    )

    assert score == pytest.approx(1.0)
