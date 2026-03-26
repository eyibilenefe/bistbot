from __future__ import annotations

from datetime import date

from bistbot.domain.models import SymbolSnapshot
from bistbot.services.clustering import assign_point_in_time_clusters


def test_point_in_time_cluster_assignment_uses_historical_snapshot() -> None:
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III"]
    old_vols = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    new_vols = [20, 2, 3, 4, 5, 6, 7, 8, 9]
    snapshots: list[SymbolSnapshot] = []

    for symbol, old_vol, new_vol in zip(symbols, old_vols, new_vols):
        snapshots.append(
            SymbolSnapshot(symbol=symbol, sector="banking", atr_percent_60d=old_vol, as_of=date(2025, 1, 31))
        )
        snapshots.append(
            SymbolSnapshot(symbol=symbol, sector="banking", atr_percent_60d=new_vol, as_of=date(2025, 6, 30))
        )

    _, old_assignments = assign_point_in_time_clusters(
        snapshots,
        as_of=date(2025, 1, 31),
        min_cluster_size=3,
    )
    _, new_assignments = assign_point_in_time_clusters(
        snapshots,
        as_of=date(2025, 6, 30),
        min_cluster_size=3,
    )

    assert old_assignments["AAA"] == "banking:low"
    assert new_assignments["AAA"] == "banking:high"
