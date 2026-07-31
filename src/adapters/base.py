"""Stable provider boundary for data ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date

from src.models.types import JsonObject

type ProviderRecord = JsonObject


class ProviderAdapterError(RuntimeError):
    """Base error raised by a data provider adapter."""


class ProviderUnavailableError(ProviderAdapterError):
    """Raised when a provider has no configured and authorized connector."""


class BaseProviderAdapter(ABC):
    """Return provider records behind one replaceable ingestion interface.

    Provider-specific response parsing belongs in concrete adapters. Records
    returned here use the small ingestion vocabulary consumed by the
    normalizer; external API response objects never leave the adapter package.
    """

    provider_name: str
    market_scope: str

    @abstractmethod
    def healthcheck(self) -> JsonObject:
        """Return non-secret provider availability metadata."""

    @abstractmethod
    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return instrument records in the stable ingestion vocabulary."""

    @abstractmethod
    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return EOD records for the requested assets and date."""

    @abstractmethod
    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return document records for the requested assets and date range."""
