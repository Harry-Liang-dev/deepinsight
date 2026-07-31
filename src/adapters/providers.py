"""Phase One provider placeholders and the deterministic offline provider."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from datetime import date
from typing import NoReturn

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.models.types import JsonObject


class _UnavailableProviderAdapter(BaseProviderAdapter):
    """Explicit non-networking boundary for an unconfigured connector."""

    access_mode: str

    def healthcheck(self) -> JsonObject:
        """Report that this connector requires explicit configuration."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "unavailable",
            "access_mode": self.access_mode,
            "network_attempted": False,
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Fail without attempting provider access."""

        self._raise_unavailable()

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Fail without attempting provider access."""

        del asset_ids, target_date
        self._raise_unavailable()

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Fail without attempting provider access."""

        del asset_ids, start_date, end_date
        self._raise_unavailable()

    def _raise_unavailable(self) -> NoReturn:
        raise ProviderUnavailableError(
            f"{self.provider_name} connector is not configured"
        )


class WindAdapter(_UnavailableProviderAdapter):
    """Licensed Wind WDS connector boundary."""

    provider_name = "wind_wds"
    market_scope = "GLOBAL"
    access_mode = "licensed"


class CNINFOAdapter(_UnavailableProviderAdapter):
    """Official CNINFO connector boundary."""

    provider_name = "cninfo"
    market_scope = "CN"
    access_mode = "official"


class HKEXNewsAdapter(_UnavailableProviderAdapter):
    """Official HKEXnews connector boundary."""

    provider_name = "hkexnews"
    market_scope = "HK"
    access_mode = "official_search"


class SECEDGARAdapter(_UnavailableProviderAdapter):
    """Official SEC EDGAR connector boundary."""

    provider_name = "sec_edgar"
    market_scope = "US"
    access_mode = "official"


class FREDAdapter(_UnavailableProviderAdapter):
    """Official FRED connector boundary.

    Macro-series fetching is intentionally absent until the Base Adapter
    contract for macro observations is confirmed.
    """

    provider_name = "fred"
    market_scope = "US"
    access_mode = "official"


class AlpacaAdapter(_UnavailableProviderAdapter):
    """Official Alpaca Market Data connector boundary."""

    provider_name = "alpaca_market_data"
    market_scope = "US"
    access_mode = "official"


class XSearchAdapter(_UnavailableProviderAdapter):
    """Official X Search Posts connector boundary."""

    provider_name = "x_search_posts"
    market_scope = "US"
    access_mode = "official"


class LSEGLicensedAdapter(_UnavailableProviderAdapter):
    """Licensed LSEG/Reuters connector boundary."""

    provider_name = "lseg_news"
    market_scope = "GLOBAL"
    access_mode = "licensed"


class BloombergLicensedAdapter(_UnavailableProviderAdapter):
    """Licensed Bloomberg connector boundary."""

    provider_name = "bloomberg_data"
    market_scope = "GLOBAL"
    access_mode = "licensed"


class FakeProviderAdapter(BaseProviderAdapter):
    """Deterministic provider for offline tests and local development."""

    provider_name = "fake"
    market_scope = "MIXED"

    def __init__(
        self,
        *,
        instruments: Sequence[ProviderRecord] = (),
        eod_bars: Sequence[ProviderRecord] = (),
        documents: Sequence[ProviderRecord] = (),
        fail_stream: str | None = None,
        fail_after: int = 0,
    ) -> None:
        """Store fixed records without network or process-environment access.

        Args:
            instruments: Fixed instrument records.
            eod_bars: Fixed EOD records.
            documents: Fixed document records.
            fail_stream: Optional stream name that should fail while iterating.
            fail_after: Number of records yielded before the configured failure.
        """

        if fail_stream not in {None, "instruments", "eod_bars", "documents"}:
            raise ValueError("invalid fake provider failure stream")
        if fail_after < 0:
            raise ValueError("fail_after cannot be negative")
        self._instruments = tuple(deepcopy(instruments))
        self._eod_bars = tuple(deepcopy(eod_bars))
        self._documents = tuple(deepcopy(documents))
        self._fail_stream = fail_stream
        self._fail_after = fail_after

    def healthcheck(self) -> JsonObject:
        """Report deterministic offline availability."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "ok",
            "mode": "offline",
            "network_attempted": False,
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Yield fixed instrument records."""

        return self._stream("instruments", self._instruments)

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Yield fixed bars matching the requested canonical values."""

        selected = tuple(
            item
            for item in self._eod_bars
            if _matches_asset(item, asset_ids)
            and _matches_date(item, "trade_date", target_date)
        )
        return self._stream("eod_bars", selected)

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Yield fixed documents within the requested date range."""

        selected = tuple(
            item
            for item in self._documents
            if _matches_asset(item, asset_ids)
            and _within_date_range(item, start_date, end_date)
        )
        return self._stream("documents", selected)

    def _stream(
        self,
        name: str,
        records: Sequence[ProviderRecord],
    ) -> Iterable[ProviderRecord]:
        for index, record in enumerate(records):
            if self._fail_stream == name and index == self._fail_after:
                raise ProviderUnavailableError("fake provider configured failure")
            yield deepcopy(record)
        if self._fail_stream == name and len(records) <= self._fail_after:
            raise ProviderUnavailableError("fake provider configured failure")


def _matches_asset(record: ProviderRecord, requested: list[str]) -> bool:
    if not requested:
        return True
    value = record.get("asset_id")
    return value is None or str(value) in requested


def _matches_date(record: ProviderRecord, field: str, expected: date) -> bool:
    value = record.get(field)
    return value is None or str(value) == expected.isoformat()


def _within_date_range(
    record: ProviderRecord,
    start_date: date,
    end_date: date,
) -> bool:
    value = record.get("publish_ts")
    if value is None:
        return True
    try:
        published = date.fromisoformat(str(value)[:10])
    except ValueError:
        return True
    return start_date <= published <= end_date
