from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from bistbot.domain.enums import LifecycleEventType
from bistbot.domain.models import LifecycleEvent, PortfolioPosition, SetupCandidate


def is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def require_finite_number(name: str, value: object) -> float:
    if not is_finite_number(value):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


def require_probability(name: str, value: object | None) -> float | None:
    if value is None:
        return None
    probability = require_finite_number(name, value)
    if probability < 0.0 or probability > 1.0:
        raise ValueError(f"{name} must be between 0 and 1.")
    return probability


def require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer.")
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if quantity < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return quantity


def validate_long_trade_values(
    *,
    entry_price: object,
    stop_price: object,
    target_price: object | None = None,
) -> tuple[float, float, float | None]:
    resolved_entry = require_finite_number("entry_price", entry_price)
    resolved_stop = require_finite_number("stop_price", stop_price)
    resolved_target = (
        require_finite_number("target_price", target_price)
        if target_price is not None
        else None
    )
    if resolved_entry <= resolved_stop:
        raise ValueError("Entry price must be above stop price for long positions.")
    if resolved_target is not None and resolved_target <= resolved_entry:
        raise ValueError("Target price must be above entry price for long positions.")
    return resolved_entry, resolved_stop, resolved_target


def normalize_probability(probability: float | None) -> float | None:
    if probability is None or not is_finite_number(probability):
        return None
    return max(0.0, min(float(probability), 1.0))


def format_probability_pct(probability: float | None) -> float | None:
    normalized = normalize_probability(probability)
    if normalized is None:
        return None
    return round(normalized * 100, 1)


def compute_expected_r(
    *,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
) -> float | None:
    if not (
        is_finite_number(entry_price)
        and is_finite_number(stop_price)
        and is_finite_number(target_price)
    ):
        return None
    resolved_entry = float(entry_price)
    resolved_stop = float(stop_price)
    resolved_target = float(target_price)
    risk_per_share = resolved_entry - resolved_stop
    if risk_per_share <= 0:
        return None
    return max((resolved_target - resolved_entry) / risk_per_share, 0.0)


def build_setup_thesis(
    *,
    family_label: str,
    cluster_label: str,
    trend_indicator: str,
    momentum_indicator: str,
    volume_indicator: str,
    confluence_score: float | None,
    score: float | None,
    expected_r: float | None,
    wf_window_count: int,
    wf_win_rate: float | None,
    wf_total_return_pct: float | None,
) -> str:
    confluence_text = _format_float(confluence_score) or "-"
    score_text = _format_float(score) or "-"
    expected_r_text = _format_float(expected_r) or "-"
    wf_clause = ""
    if wf_window_count > 0:
        wf_win_rate_text = _format_float(wf_win_rate, digits=2) or "-"
        wf_return_text = _format_float(wf_total_return_pct, digits=2) or "-"
        wf_clause = (
            f" Walk-forward OOS dogrulamasi {wf_window_count} pencere,"
            f" {wf_win_rate_text}% kazanma ve {wf_return_text}% getiri gosterdi."
        )
    return (
        f"{family_label} stratejisi {cluster_label} kumesinde one cikti. "
        f"{trend_indicator}, {momentum_indicator} ve {volume_indicator} birlikte onay verdi; "
        f"uyum {confluence_text}, skor {score_text} ve beklenen getiri {expected_r_text}R."
        f"{wf_clause}"
    )


def build_position_entry_reason(
    *,
    base_thesis: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    expected_r_at_entry: float | None = None,
    confidence_at_entry: float | None = None,
) -> str:
    entry_text = _format_price(entry_price) or "?"
    stop_text = _format_price(stop_price) or "?"
    target_text = _format_price(target_price) or "?"
    clauses = [
        base_thesis.strip() or "Paper-trading pozisyonu olusturuldu.",
        f"Pozisyon {entry_text} giris, {stop_text} stop ve {target_text} hedef ile tasindi.",
    ]
    expected_r_text = _format_float(expected_r_at_entry)
    if expected_r_text is not None:
        clauses.append(f"Beklenen getiri {expected_r_text}R olarak kaydedildi.")
    confidence_text = _format_float(format_probability_pct(confidence_at_entry), digits=1)
    if confidence_text is not None:
        clauses.append(f"Kayitli guven gostergesi %{confidence_text}.")
    return " ".join(clauses)


def build_setup_view(
    *,
    setup: SetupCandidate,
    strategy_name: str,
    strategy_family_label: str,
    sector: str,
    cluster_label: str,
    trend_indicator: str,
    momentum_indicator: str,
    volume_indicator: str,
    now: datetime | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    entry_low = _safe_float(setup.entry_low, "entry_low", reasons)
    entry_high = _safe_float(setup.entry_high, "entry_high", reasons)
    stop = _safe_float(setup.stop, "stop", reasons)
    target = _safe_float(setup.target, "target", reasons)
    score = _safe_float(setup.score, "score", reasons)
    confluence = _safe_float(setup.confluence_score, "confluence_score", reasons)
    expected_r = _safe_float(setup.expected_r, "expected_r", reasons)
    confidence = _safe_probability(setup.confidence, "confidence", reasons)

    if entry_low is not None and entry_high is not None and entry_high < entry_low:
        reasons.append("entry_zone_invalid")
    if entry_high is not None and stop is not None and entry_high <= stop:
        reasons.append("entry_stop_relationship_invalid")
    if target is not None and entry_high is not None and target <= entry_high:
        reasons.append("target_relationship_invalid")
    if confidence is None:
        reasons.append("confidence_missing")

    risk_reward = compute_expected_r(
        entry_price=entry_high,
        stop_price=stop,
        target_price=target,
    )
    thesis = (
        setup.thesis
        or build_setup_thesis(
            family_label=strategy_family_label,
            cluster_label=cluster_label,
            trend_indicator=trend_indicator,
            momentum_indicator=momentum_indicator,
            volume_indicator=volume_indicator,
            confluence_score=confluence,
            score=score,
            expected_r=expected_r,
            wf_window_count=setup.wf_window_count,
            wf_win_rate=_safe_float(setup.wf_win_rate, "wf_win_rate", []),
            wf_total_return_pct=_safe_float(setup.wf_total_return_pct, "wf_total_return_pct", []),
        )
    )
    expires_in_hours = None
    if now is not None:
        expires_in_hours = round(max((setup.expires_at - now).total_seconds(), 0.0) / 3600, 1)

    return {
        "id": setup.id,
        "symbol": setup.symbol,
        "cluster_id": setup.cluster_id,
        "cluster_label": cluster_label,
        "strategy_id": setup.strategy_id,
        "strategy_name": strategy_name,
        "strategy_family": setup.strategy_family.value,
        "strategy_family_label": strategy_family_label,
        "score": score,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "target": target,
        "confidence": confidence,
        "confidence_pct": format_probability_pct(confidence),
        "confluence_score": confluence,
        "expected_r": expected_r,
        "risk_reward": round(risk_reward, 2) if risk_reward is not None else None,
        "created_at": setup.created_at,
        "expires_at": setup.expires_at,
        "expires_in_hours": expires_in_hours,
        "wf_window_count": setup.wf_window_count,
        "wf_win_rate": _safe_float(setup.wf_win_rate, "wf_win_rate", []),
        "wf_total_return_pct": _safe_float(setup.wf_total_return_pct, "wf_total_return_pct", []),
        "thesis": thesis,
        "status": setup.status.value,
        "invalidated_reason": setup.invalidated_reason,
        "sector": sector,
        "is_degraded": bool(reasons),
        "degraded_reasons": _dedupe(reasons),
    }


def build_position_view(
    *,
    position: PortfolioPosition,
    base_thesis: str,
) -> dict[str, object]:
    reasons: list[str] = []
    entry_price = _safe_float(position.entry_price, "entry_price", reasons)
    stop_price = _safe_float(position.stop_price, "stop_price", reasons)
    target_price = _safe_float(position.target_price, "target_price", reasons)
    last_price = _safe_float(position.last_price, "last_price", reasons)
    initial_stop_price = _safe_float(position.initial_stop_price, "initial_stop_price", reasons)
    initial_target_price = _safe_float(position.initial_target_price, "initial_target_price", reasons)
    expected_r_at_entry = _safe_float(position.expected_r_at_entry, "expected_r_at_entry", reasons)
    confidence_at_entry = _safe_probability(
        position.confidence_at_entry if position.confidence_at_entry is not None else position.success_probability,
        "confidence_at_entry",
        reasons,
    )

    if position.quantity < 1:
        reasons.append("quantity_invalid")
        quantity: int | None = None
    else:
        quantity = position.quantity

    if entry_price is not None and stop_price is not None and entry_price <= stop_price:
        reasons.append("entry_stop_relationship_invalid")
    if target_price is not None and entry_price is not None and target_price <= entry_price:
        reasons.append("target_relationship_invalid")
    if confidence_at_entry is None:
        reasons.append("confidence_missing")

    derived_expected_r = expected_r_at_entry
    if derived_expected_r is None:
        derived_expected_r = compute_expected_r(
            entry_price=entry_price,
            stop_price=initial_stop_price if initial_stop_price is not None else stop_price,
            target_price=initial_target_price if initial_target_price is not None else target_price,
        )

    entry_reason = build_position_entry_reason(
        base_thesis=base_thesis,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        expected_r_at_entry=derived_expected_r,
        confidence_at_entry=confidence_at_entry,
    )

    return {
        "id": position.id,
        "symbol": position.symbol,
        "sector": position.sector,
        "status": position.status.value,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "quantity": quantity,
        "last_price": last_price,
        "opened_at": position.opened_at,
        "entry_reason": entry_reason,
        "success_probability": confidence_at_entry,
        "success_probability_pct": format_probability_pct(confidence_at_entry),
        "closed_at": position.closed_at,
        "adjustment_factor": _safe_float(position.adjustment_factor, "adjustment_factor", []),
        "adjusted_entry_price": _safe_float(position.adjusted_entry_price, "adjusted_entry_price", []),
        "adjusted_stop_price": _safe_float(position.adjusted_stop_price, "adjusted_stop_price", []),
        "adjusted_target_price": _safe_float(position.adjusted_target_price, "adjusted_target_price", []),
        "last_corporate_action_at": position.last_corporate_action_at,
        "source_setup_id": position.source_setup_id,
        "initial_stop_price": initial_stop_price,
        "initial_target_price": initial_target_price,
        "expected_r_at_entry": round(derived_expected_r, 4) if derived_expected_r is not None else None,
        "confidence_at_entry": confidence_at_entry,
        "is_degraded": bool(reasons),
        "degraded_reasons": _dedupe(reasons),
    }


def build_watchlist_row_view(
    *,
    symbol: str,
    sector: str,
    close: object,
    change_pct: object,
    high: object,
    low: object,
    volume: object,
) -> dict[str, object]:
    reasons: list[str] = []
    safe_close = _safe_float(close, "close", reasons)
    safe_change = _safe_float(change_pct, "change_pct", reasons)
    safe_high = _safe_float(high, "high", reasons)
    safe_low = _safe_float(low, "low", reasons)
    safe_volume = _safe_float(volume, "volume", reasons)
    if safe_volume is not None and safe_volume < 0:
        reasons.append("volume_invalid")
    return {
        "symbol": symbol,
        "sector": sector,
        "close": safe_close,
        "change_pct": safe_change,
        "high": safe_high,
        "low": safe_low,
        "volume": int(safe_volume) if safe_volume is not None and safe_volume >= 0 else None,
        "is_degraded": bool(reasons),
        "degraded_reasons": _dedupe(reasons),
    }


def sanitize_chart_payload(payload: dict[str, object]) -> dict[str, object]:
    sanitized = dict(payload)
    reasons: list[str] = list(sanitized.get("degraded_reasons", []))

    filtered_candles = 0
    clean_candles: list[dict[str, object]] = []
    for candle in _coerce_sequence(sanitized.get("candles")):
        if not isinstance(candle, dict):
            filtered_candles += 1
            continue
        if not (
            is_finite_number(candle.get("time"))
            and is_finite_number(candle.get("open"))
            and is_finite_number(candle.get("high"))
            and is_finite_number(candle.get("low"))
            and is_finite_number(candle.get("close"))
        ):
            filtered_candles += 1
            continue
        clean_candles.append(
            {
                "time": int(float(candle["time"])),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
            }
        )
    sanitized["candles"] = clean_candles
    if filtered_candles:
        reasons.append("invalid_candles_filtered")
    if not clean_candles:
        reasons.append("no_valid_candles")

    filtered_lines = 0
    clean_lines: list[dict[str, object]] = []
    for line in _coerce_sequence(sanitized.get("price_lines")):
        if not isinstance(line, dict) or not is_finite_number(line.get("price")):
            filtered_lines += 1
            continue
        clean_lines.append(
            {
                "price": float(line["price"]),
                "title": str(line.get("title", "")),
                "color": str(line.get("color", "#1d2430")),
                "lineWidth": int(line.get("lineWidth", 2)),
            }
        )
    sanitized["price_lines"] = clean_lines
    if filtered_lines:
        reasons.append("invalid_price_lines_filtered")

    filtered_markers = 0
    clean_markers: list[dict[str, object]] = []
    for marker in _coerce_sequence(sanitized.get("markers")):
        if not isinstance(marker, dict) or not is_finite_number(marker.get("time")):
            filtered_markers += 1
            continue
        clean_markers.append(
            {
                "time": int(float(marker["time"])),
                "position": str(marker.get("position", "aboveBar")),
                "color": str(marker.get("color", "#1d2430")),
                "shape": str(marker.get("shape", "circle")),
                "text": str(marker.get("text", "")),
            }
        )
    sanitized["markers"] = clean_markers
    if filtered_markers:
        reasons.append("invalid_markers_filtered")

    last_price = sanitized.get("last_price")
    sanitized["last_price"] = (
        float(last_price)
        if is_finite_number(last_price)
        else (clean_candles[-1]["close"] if clean_candles else None)
    )
    if last_price is not None and not is_finite_number(last_price):
        reasons.append("invalid_last_price")

    sanitized["filtered_candle_count"] = filtered_candles
    sanitized["filtered_price_line_count"] = filtered_lines
    sanitized["filtered_marker_count"] = filtered_markers
    sanitized["is_degraded"] = bool(sanitized.get("is_degraded")) or bool(reasons)
    sanitized["degraded_reasons"] = _dedupe(reasons)
    return sanitized


def build_lifecycle_event_view(event: LifecycleEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "event_type": event.event_type.value,
        "occurred_at": _ensure_utc(event.occurred_at),
        "symbol": event.symbol,
        "setup_id": event.setup_id,
        "position_id": event.position_id,
        "details": event.details,
        "message": _event_message(event),
    }


def _event_message(event: LifecycleEvent) -> str:
    symbol = event.symbol or event.details.get("symbol") or "?"
    if event.event_type == LifecycleEventType.SETUP_CREATED:
        return f"{symbol} icin yeni setup olustu."
    if event.event_type == LifecycleEventType.SETUP_APPROVED:
        return f"{symbol} setup'i manuel giris icin onaylandi."
    if event.event_type == LifecycleEventType.SETUP_EXPIRED:
        return f"{symbol} setup'i suresi doldugu icin kapandi."
    if event.event_type == LifecycleEventType.SETUP_INVALIDATED:
        reason = str(event.details.get("reason", "kosullar bozuldu"))
        return f"{symbol} setup'i gecersiz oldu: {reason}."
    if event.event_type == LifecycleEventType.POSITION_ENTERED:
        entry_price = _format_price(event.details.get("entry_price"))
        return f"{symbol} pozisyonu {entry_price or '?'} seviyesinden acildi."
    if event.event_type == LifecycleEventType.STOP_MOVED_TO_BREAKEVEN:
        stop_price = _format_price(event.details.get("to_stop"))
        return f"{symbol} stop seviyesi breakeven'a cekildi ({stop_price or '?'})."
    if event.event_type == LifecycleEventType.STOP_MOVED_TO_PLUS_1R:
        stop_price = _format_price(event.details.get("to_stop"))
        return f"{symbol} stop seviyesi +1R alanina tasindi ({stop_price or '?'})."
    if event.event_type == LifecycleEventType.POSITION_CLOSED:
        exit_price = _format_price(event.details.get("exit_price"))
        reason = str(event.details.get("close_reason", "kapandi"))
        return f"{symbol} pozisyonu {exit_price or '?'} seviyesinden kapandi ({reason})."
    return f"{symbol} icin lifecycle olayi kaydedildi."


def _coerce_sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _safe_float(value: object, field_name: str, reasons: list[str]) -> float | None:
    if value is None:
        return None
    if not is_finite_number(value):
        reasons.append(f"{field_name}_invalid")
        return None
    return float(value)


def _safe_probability(value: object, field_name: str, reasons: list[str]) -> float | None:
    if value is None:
        return None
    if not is_finite_number(value):
        reasons.append(f"{field_name}_invalid")
        return None
    resolved = float(value)
    if resolved < 0.0 or resolved > 1.0:
        reasons.append(f"{field_name}_out_of_range")
        return None
    return resolved


def _ensure_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _format_price(value: object) -> str | None:
    if not is_finite_number(value):
        return None
    return f"{float(value):.2f}"


def _format_float(value: object, *, digits: int = 2) -> str | None:
    if not is_finite_number(value):
        return None
    return f"{float(value):.{digits}f}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
