from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ManualEntryRequest(BaseModel):
    setup_id: str
    fill_price: float
    filled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    quantity: int | None = None


class PositionUpdateRequest(BaseModel):
    stop_price: float | None = None
    target_price: float | None = None
    last_price: float | None = None
    status: str | None = None
    closed_at: datetime | None = None
