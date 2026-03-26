from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Callable

from bistbot.domain.models import CorporateAction, DataQualityEvent, PriceBar


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_symbols(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def fetch_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        force_refresh: bool = False,
    ) -> list[PriceBar]:
        raise NotImplementedError

    @abstractmethod
    def fetch_sectors(
        self,
        *,
        as_of: date,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def fetch_corporate_actions(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[CorporateAction]:
        raise NotImplementedError

    @abstractmethod
    def run_data_quality_check(self) -> list[DataQualityEvent]:
        raise NotImplementedError
