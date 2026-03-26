from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime

from bistbot.domain.enums import SetupStatus
from bistbot.domain.models import SetupCandidate


def compute_confluence_score(
    *,
    daily_regime_valid: bool,
    trend_signal: bool,
    momentum_signal: bool,
    volume_confirmation: bool,
    entry_zone_proximity: float,
) -> float:
    proximity = min(max(entry_zone_proximity, 0.0), 1.0)
    return (
        0.30 * float(daily_regime_valid)
        + 0.25 * float(trend_signal)
        + 0.20 * float(momentum_signal)
        + 0.15 * float(volume_confirmation)
        + 0.10 * proximity
    )


def quality_gate(candidates: list[SetupCandidate], *, top_percent: float = 0.10) -> list[SetupCandidate]:
    if not candidates:
        return []

    eligible = [
        candidate
        for candidate in candidates
        if candidate.expected_r >= 2.0 and candidate.confluence_score >= 0.75
    ]
    if not eligible:
        return []

    eligible.sort(key=lambda candidate: candidate.score, reverse=True)
    keep_count = max(1, math.ceil(len(candidates) * top_percent))
    return eligible[:keep_count]


def refresh_setup_status(
    setup: SetupCandidate,
    *,
    now: datetime,
    daily_regime_valid: bool,
    entry_distance_atr: float,
    stop_logic_intact: bool,
) -> SetupCandidate:
    if setup.status not in {SetupStatus.ACTIVE, SetupStatus.APPROVED_PENDING_ENTRY}:
        return setup
    if now >= setup.expires_at:
        return replace(setup, status=SetupStatus.EXPIRED, invalidated_reason="expired")
    if not daily_regime_valid:
        return replace(setup, status=SetupStatus.INVALIDATED, invalidated_reason="daily_regime_broken")
    if entry_distance_atr > 0.5:
        return replace(
            setup,
            status=SetupStatus.INVALIDATED,
            invalidated_reason="entry_zone_drifted_more_than_half_atr",
        )
    if not stop_logic_intact:
        return replace(setup, status=SetupStatus.INVALIDATED, invalidated_reason="stop_logic_invalid")
    return setup


def approve_setup(setup: SetupCandidate, *, now: datetime) -> SetupCandidate:
    refreshed = refresh_setup_status(
        setup,
        now=now,
        daily_regime_valid=True,
        entry_distance_atr=0.0,
        stop_logic_intact=True,
    )
    if refreshed.status != SetupStatus.ACTIVE:
        return refreshed
    return replace(refreshed, status=SetupStatus.APPROVED_PENDING_ENTRY)


def reject_setup(setup: SetupCandidate) -> SetupCandidate:
    return replace(setup, status=SetupStatus.REJECTED)


def validate_manual_entry(setup: SetupCandidate, *, now: datetime) -> None:
    refreshed = refresh_setup_status(
        setup,
        now=now,
        daily_regime_valid=True,
        entry_distance_atr=0.0,
        stop_logic_intact=True,
    )
    if refreshed.status != SetupStatus.APPROVED_PENDING_ENTRY:
        raise ValueError("Setup is no longer eligible for manual entry.")
