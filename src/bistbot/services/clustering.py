from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date

from bistbot.domain.enums import ClusterFallbackMode
from bistbot.domain.models import ClusterDefinition, SymbolSnapshot

VOL_BUCKET_LABELS = ("low", "mid", "high")


def latest_snapshots_as_of(
    snapshots: list[SymbolSnapshot], *, as_of: date
) -> list[SymbolSnapshot]:
    latest_by_symbol: dict[str, SymbolSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.as_of > as_of:
            continue
        current = latest_by_symbol.get(snapshot.symbol)
        if current is None or snapshot.as_of > current.as_of:
            latest_by_symbol[snapshot.symbol] = snapshot
    return [snapshot for snapshot in latest_by_symbol.values() if snapshot.tradeable]


def assign_point_in_time_clusters(
    snapshots: list[SymbolSnapshot],
    *,
    as_of: date,
    min_cluster_size: int = 8,
) -> tuple[list[ClusterDefinition], dict[str, str]]:
    current_snapshots = latest_snapshots_as_of(snapshots, as_of=as_of)
    sector_groups: dict[str, list[SymbolSnapshot]] = defaultdict(list)
    for snapshot in current_snapshots:
        sector_groups[snapshot.sector].append(snapshot)

    clusters: list[ClusterDefinition] = []
    assignments: dict[str, str] = {}

    for sector, group in sector_groups.items():
        sector_clusters, sector_assignments = _build_sector_clusters(
            sector, group, as_of=as_of, min_cluster_size=min_cluster_size
        )
        clusters.extend(sector_clusters)
        assignments.update(sector_assignments)

    return clusters, assignments


def _build_sector_clusters(
    sector: str,
    snapshots: list[SymbolSnapshot],
    *,
    as_of: date,
    min_cluster_size: int,
) -> tuple[list[ClusterDefinition], dict[str, str]]:
    ordered = sorted(snapshots, key=lambda snapshot: snapshot.atr_percent_60d)
    if len(ordered) < min_cluster_size:
        cluster = ClusterDefinition(
            id=f"{sector}:all",
            sector=sector,
            vol_bucket="all",
            symbol_count=len(ordered),
            fallback_mode=ClusterFallbackMode.SECTOR_ONLY,
            as_of=as_of,
            members=[snapshot.symbol for snapshot in ordered],
        )
        return [cluster], {snapshot.symbol: cluster.id for snapshot in ordered}

    raw_groups: dict[str, list[SymbolSnapshot]] = {label: [] for label in VOL_BUCKET_LABELS}
    total = len(ordered)
    for index, snapshot in enumerate(ordered):
        if index < total / 3:
            raw_groups["low"].append(snapshot)
        elif index < 2 * total / 3:
            raw_groups["mid"].append(snapshot)
        else:
            raw_groups["high"].append(snapshot)

    fallback_mode = {
        "low": ClusterFallbackMode.NONE,
        "mid": ClusterFallbackMode.NONE,
        "high": ClusterFallbackMode.NONE,
    }

    if len(raw_groups["low"]) < min_cluster_size:
        raw_groups["mid"] = raw_groups["low"] + raw_groups["mid"]
        raw_groups["low"] = []
        fallback_mode["mid"] = ClusterFallbackMode.ADJACENT_VOLATILITY_MERGE

    if len(raw_groups["high"]) < min_cluster_size:
        raw_groups["mid"] = raw_groups["mid"] + raw_groups["high"]
        raw_groups["high"] = []
        fallback_mode["mid"] = ClusterFallbackMode.ADJACENT_VOLATILITY_MERGE

    if raw_groups["mid"] and len(raw_groups["mid"]) < min_cluster_size:
        merged_members = raw_groups["low"] + raw_groups["mid"] + raw_groups["high"]
        cluster = ClusterDefinition(
            id=f"{sector}:all",
            sector=sector,
            vol_bucket="all",
            symbol_count=len(merged_members),
            fallback_mode=ClusterFallbackMode.SECTOR_ONLY,
            as_of=as_of,
            members=[snapshot.symbol for snapshot in merged_members],
        )
        return [cluster], {snapshot.symbol: cluster.id for snapshot in merged_members}

    clusters: list[ClusterDefinition] = []
    assignments: dict[str, str] = {}
    for bucket in VOL_BUCKET_LABELS:
        members = raw_groups[bucket]
        if not members:
            continue
        cluster = ClusterDefinition(
            id=f"{sector}:{bucket}",
            sector=sector,
            vol_bucket=bucket,
            symbol_count=len(members),
            fallback_mode=fallback_mode[bucket],
            as_of=as_of,
            members=[snapshot.symbol for snapshot in members],
        )
        clusters.append(cluster)
        for snapshot in members:
            assignments[snapshot.symbol] = cluster.id

    return clusters, assignments


def freeze_cluster_assignments_for_test_window(
    snapshots: list[SymbolSnapshot],
    *,
    window_start: date,
    min_cluster_size: int = 8,
) -> tuple[list[ClusterDefinition], dict[str, str]]:
    return assign_point_in_time_clusters(
        snapshots,
        as_of=window_start,
        min_cluster_size=min_cluster_size,
    )
