from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bistbot.domain.enums import CorporateActionType
from bistbot.domain.models import CorporateAction, PriceBar
from bistbot.services.data_quality import run_data_quality_check


def test_unexplained_gap_is_quarantined() -> None:
    now = datetime(2026, 3, 25, tzinfo=UTC)
    bars = [
        PriceBar("AKBNK", now, 10.0, 10.5, 9.9, 10.0, 1000, "1d"),
        PriceBar("AKBNK", now + timedelta(days=1), 13.5, 14.0, 13.2, 13.8, 2000, "1d"),
    ]

    events = run_data_quality_check(bars, [])

    assert len(events) == 1
    assert events[0].resolution == "quarantined"


def test_corporate_action_explains_large_gap() -> None:
    now = datetime(2026, 3, 25, tzinfo=UTC)
    bars = [
        PriceBar("AKBNK", now, 10.0, 10.5, 9.9, 10.0, 1000, "1d"),
        PriceBar("AKBNK", now + timedelta(days=1), 13.5, 14.0, 13.2, 13.8, 2000, "1d"),
    ]
    actions = [
        CorporateAction(
            symbol="AKBNK",
            action_type=CorporateActionType.BONUS,
            effective_at=now + timedelta(days=1),
            factor=1.5,
            reference="bonus-1",
        )
    ]

    events = run_data_quality_check(bars, actions)

    assert events == []
