"""Phase One provider placeholders and the deterministic offline provider."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import NoReturn
from urllib.parse import urlencode

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.http import (
    ProviderHTTPClient,
    ProviderHTTPTransport,
    decode_http_payload,
)
from src.models.enums import Market
from src.models.identifiers import AssetId
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


class SECEDGARAdapter(BaseProviderAdapter):
    """Minimal official SEC EDGAR submissions and filing adapter."""

    provider_name = "sec_edgar"
    market_scope = "US"
    access_mode = "official"

    def __init__(
        self,
        *,
        user_agent: str,
        cik_by_asset: Mapping[str, str],
        request_timeout: float = 30.0,
        max_retries: int = 2,
        requests_per_second: float = 5.0,
        backoff_base_seconds: float = 0.5,
        max_backoff_seconds: float = 30.0,
        max_documents: int = 1,
        http_transport: ProviderHTTPTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """Configure identified, bounded access to official SEC endpoints.

        Args:
            user_agent: SEC Fair Access identity with a contact email.
            cik_by_asset: Canonical US asset IDs mapped to SEC CIK values.
            request_timeout: Timeout for every official HTTPS request.
            max_retries: Maximum additional transient-failure attempts.
            requests_per_second: Per-adapter request ceiling, at most ten.
            backoff_base_seconds: Initial retry backoff.
            max_backoff_seconds: Upper bound for a retry delay.
            max_documents: Maximum filings returned by one fetch.
            http_transport: Optional HTTP transport for offline tests.
            clock: Optional monotonic clock for offline tests.
            sleeper: Optional sleep function for offline tests.
        """

        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError("SEC user agent must include a contact email")
        if not cik_by_asset:
            raise ValueError("at least one SEC asset/CIK mapping is required")
        if request_timeout <= 0:
            raise ValueError("SEC request timeout must be positive")
        if not 0 <= max_retries <= 5:
            raise ValueError("SEC max_retries must be between zero and five")
        if not 0 < requests_per_second <= 10:
            raise ValueError("SEC requests_per_second must be positive and at most ten")
        if backoff_base_seconds < 0:
            raise ValueError("SEC retry backoff cannot be negative")
        if max_backoff_seconds <= 0:
            raise ValueError("SEC maximum backoff must be positive")
        if max_documents <= 0:
            raise ValueError("SEC max_documents must be positive")
        self._user_agent = user_agent.strip()
        self._cik_by_asset = {
            asset_id.upper(): _normalize_cik(cik)
            for asset_id, cik in cik_by_asset.items()
        }
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._requests_per_second = requests_per_second
        self._max_documents = max_documents
        self._http_client = ProviderHTTPClient(
            user_agent=self._user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            backoff_base_seconds=backoff_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
            transport=http_transport,
            clock=clock,
            sleeper=sleeper,
        )
        self._submissions: dict[str, JsonObject] = {}
        self._filing_pages: dict[str, JsonObject] = {}

    def healthcheck(self) -> JsonObject:
        """Return configured status without making a network request."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "access_mode": self.access_mode,
            "network_attempted": False,
            "asset_count": len(self._cik_by_asset),
            "max_retries": self._max_retries,
            "requests_per_second": self._requests_per_second,
            "capabilities": ["instruments", "documents", "fundamentals"],
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return instrument identity from official submissions metadata."""

        records: list[ProviderRecord] = []
        for asset_id, cik in self._cik_by_asset.items():
            submissions = self._load_submissions(cik)
            ticker = asset_id.removeprefix("US:")
            tickers = submissions.get("tickers")
            exchanges = submissions.get("exchanges")
            exchange = "US"
            if isinstance(tickers, list) and isinstance(exchanges, list):
                for index, value in enumerate(tickers):
                    if str(value).upper() == ticker and index < len(exchanges):
                        exchange = str(exchanges[index]).upper() or "US"
                        break
            records.append(
                {
                    "asset_id": asset_id,
                    "market": "US",
                    "exchange_code": exchange,
                    "company_name": str(submissions.get("name") or ticker),
                    "currency": "USD",
                    "metadata": {"cik": cik},
                }
            )
        return records

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return no prices because SEC EDGAR is a disclosure source."""

        del asset_ids, target_date
        return ()

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return bounded recent 10-K/10-Q filing documents."""

        requested = {value.upper() for value in asset_ids}
        records: list[ProviderRecord] = []
        for asset_id, cik in self._cik_by_asset.items():
            if requested and asset_id not in requested:
                continue
            submissions = self._load_submissions(cik)
            seen_accessions: set[str] = set()
            page_seen = False
            for filing_page in self._iter_filing_pages_for_window(
                submissions,
                start_date,
                end_date,
            ):
                page_seen = True
                for filing in _recent_filings(filing_page):
                    filing_date = _iso_date(filing.get("filingDate"))
                    if (
                        filing.get("form") not in {"10-K", "10-Q"}
                        or filing_date is None
                        or not start_date <= filing_date <= end_date
                    ):
                        continue
                    accession = str(filing.get("accessionNumber") or "")
                    primary_document = str(filing.get("primaryDocument") or "")
                    if (
                        not accession
                        or accession in seen_accessions
                        or not primary_document
                    ):
                        continue
                    seen_accessions.add(accession)
                    archive_cik = str(int(cik))
                    accession_path = accession.replace("-", "")
                    source_url = (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{archive_cik}/{accession_path}/{primary_document}"
                    )
                    raw_text = _html_to_text(
                        self._http_client.get_text(
                            source_url,
                            accept="text/html,application/xhtml+xml",
                        )
                    )
                    if not raw_text:
                        raise ProviderUnavailableError(
                            "SEC filing document contained no readable text"
                        )
                    accepted = _sec_acceptance_timestamp(
                        filing.get("acceptanceDateTime"),
                        filing_date,
                    )
                    form = str(filing["form"])
                    records.append(
                        {
                            "document_id": f"sec-{cik}-{accession_path}",
                            "asset_id": asset_id,
                            "market": "US",
                            "doc_type": "filing",
                            "title": (
                                f"{submissions.get('name') or asset_id} "
                                f"{form} filed {filing_date.isoformat()}"
                            ),
                            "language": "en",
                            "publisher": ("U.S. Securities and Exchange Commission"),
                            "publish_ts": accepted,
                            "source_url": source_url,
                            "raw_text": raw_text,
                            "metadata": {
                                "cik": cik,
                                "accession_number": accession,
                                "provider_locator": (f"sec:accession:{accession}"),
                                "primary_document": primary_document,
                                "form": form,
                                "filing_date": filing_date.isoformat(),
                            },
                        }
                    )
                    if len(records) >= self._max_documents:
                        return records
            if not page_seen:
                raise ProviderUnavailableError(
                    "SEC submissions response has no filing records"
                )
        return records

    def fetch_fundamentals_range(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return normalized SEC Company Facts filed in an inclusive window.

        The external XBRL response is reduced to the stable ingestion
        vocabulary here. Taxonomy tags and SEC response layout therefore do
        not escape the Adapter boundary.

        Args:
            asset_ids: Canonical US asset identifiers.
            start_date: Inclusive filing-date cursor.
            end_date: Inclusive filing-date upper bound.

        Returns:
            Fundamental records ordered by filing date and accession.
        """

        if end_date < start_date:
            raise ValueError("SEC fundamental end_date cannot precede start_date")
        requested = _sec_requested_assets(asset_ids)
        records: list[tuple[date, str, ProviderRecord]] = []
        for asset_id, cik in self._cik_by_asset.items():
            if requested and asset_id not in requested:
                continue
            facts = self._load_company_facts(cik)
            submissions = self._load_submissions(cik)
            records.extend(
                _sec_fundamental_records(
                    asset_id,
                    cik,
                    facts,
                    start_date=start_date,
                    end_date=end_date,
                    accepted_by_accession=_sec_acceptance_by_accession(submissions),
                )
            )
        records.sort(key=lambda item: (item[0], item[1]))
        return [record for _, _, record in records]

    def _load_submissions(self, cik: str) -> JsonObject:
        cached = self._submissions.get(cik)
        if cached is not None:
            return cached
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        result = self._load_json_object(url, "SEC submissions")
        self._submissions[cik] = result
        return result

    def _load_company_facts(self, cik: str) -> JsonObject:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        return self._load_json_object(url, "SEC Company Facts")

    def _iter_filing_pages_for_window(
        self,
        submissions: JsonObject,
        start_date: date,
        end_date: date,
    ) -> Iterator[JsonObject]:
        filings = submissions.get("filings")
        if not isinstance(filings, dict):
            return
        recent = filings.get("recent")
        if isinstance(recent, dict):
            yield dict(recent)
        historical = filings.get("files")
        if not isinstance(historical, list):
            return
        for descriptor in historical:
            if not isinstance(descriptor, dict) or not _page_overlaps_window(
                descriptor,
                start_date,
                end_date,
            ):
                continue
            name = str(descriptor.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9._-]+\.json", name):
                raise ProviderUnavailableError(
                    "SEC submissions page has an invalid locator"
                )
            cached = self._filing_pages.get(name)
            if cached is None:
                cached = self._load_json_object(
                    f"https://data.sec.gov/submissions/{name}",
                    "SEC submissions page",
                )
                self._filing_pages[name] = cached
            yield cached

    def _load_json_object(self, url: str, label: str) -> JsonObject:
        try:
            decoded = json.loads(
                self._http_client.get_text(
                    url,
                    accept="application/json",
                )
            )
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                f"{label} response was not valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderUnavailableError(f"{label} response must be an object")
        return dict(decoded)


class FREDAdapter(BaseProviderAdapter):
    """Official FRED/ALFRED point-in-time macro-series adapter."""

    provider_name = "fred"
    market_scope = "US"
    access_mode = "official"
    _API_ROOT = "https://api.stlouisfed.org/fred"
    DEFAULT_SERIES = (
        "FEDFUNDS",
        "DGS2",
        "DGS10",
        "T10Y2Y",
        "CPIAUCSL",
        "PCEPILFE",
        "UNRATE",
        "PAYEMS",
        "GDP",
        "INDPRO",
        "VIXCLS",
        "BAMLH0A0HYM2",
    )

    def __init__(
        self,
        *,
        api_key: str,
        user_agent: str = "DeepInsight/0.1",
        request_timeout: float = 30.0,
        max_retries: int = 2,
        requests_per_second: float = 2.0,
        backoff_base_seconds: float = 0.5,
        max_backoff_seconds: float = 30.0,
        http_transport: ProviderHTTPTransport | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """Configure authenticated official API access with bounded retries."""

        if not api_key.strip():
            raise ValueError("FRED API key is required")
        if request_timeout <= 0:
            raise ValueError("FRED request timeout must be positive")
        if not 0 <= max_retries <= 5:
            raise ValueError("FRED max_retries must be between zero and five")
        if requests_per_second <= 0:
            raise ValueError("FRED requests_per_second must be positive")
        self._api_key = api_key.strip()
        self._max_retries = max_retries
        self._requests_per_second = requests_per_second
        self._http_client = ProviderHTTPClient(
            user_agent=user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
            backoff_base_seconds=backoff_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
            transport=http_transport,
            clock=clock,
            wall_clock=wall_clock,
            sleeper=sleeper,
        )

    def healthcheck(self) -> JsonObject:
        """Return credential-safe configured status without network access."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "access_mode": self.access_mode,
            "network_attempted": False,
            "series_count": len(self.DEFAULT_SERIES),
            "max_retries": self._max_retries,
            "requests_per_second": self._requests_per_second,
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return no securities because FRED is a macro source."""

        return ()

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return no security bars because FRED is a macro source."""

        del asset_ids, target_date
        return ()

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return no documents because v1 persists structured observations."""

        del asset_ids, start_date, end_date
        return ()

    def fetch_macro_series(
        self,
        series_ids: Sequence[str],
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> Iterable[ProviderRecord]:
        """Return approved observations as they were known on ``as_of``."""

        if end_date < start_date:
            raise ValueError("FRED end_date cannot precede start_date")
        if end_date > as_of:
            raise ValueError("FRED observation window cannot exceed as_of")
        approved = tuple(series_ids) if series_ids else self.DEFAULT_SERIES
        unsupported = sorted(set(approved) - set(self.DEFAULT_SERIES))
        if unsupported:
            raise ValueError("unapproved FRED series: " + ", ".join(unsupported))
        records: list[ProviderRecord] = []
        for series_id in approved:
            metadata = self._load_json(
                "series",
                (("series_id", series_id),),
            )
            series = metadata.get("seriess")
            if not isinstance(series, list) or len(series) != 1:
                raise ProviderUnavailableError(
                    f"FRED series metadata unavailable for {series_id}"
                )
            description = series[0]
            if not isinstance(description, dict):
                raise ProviderUnavailableError("FRED series metadata must be an object")
            indicator_name = str(description.get("title") or series_id)
            unit = str(description.get("units") or "") or None
            frequency = str(description.get("frequency") or "") or None
            payload = self._load_json(
                "series/observations",
                (
                    ("series_id", series_id),
                    ("observation_start", start_date.isoformat()),
                    ("observation_end", end_date.isoformat()),
                    ("realtime_start", as_of.isoformat()),
                    ("realtime_end", as_of.isoformat()),
                    ("sort_order", "asc"),
                    ("limit", 100000),
                ),
            )
            observations = payload.get("observations")
            if not isinstance(observations, list):
                raise ProviderUnavailableError(
                    f"FRED observations unavailable for {series_id}"
                )
            for raw in observations:
                if not isinstance(raw, dict):
                    raise ProviderUnavailableError("FRED observation must be an object")
                raw_value = raw.get("value")
                if raw_value is None or raw_value == ".":
                    continue
                observation_date = _iso_date(raw.get("date"))
                realtime_start = _iso_date(raw.get("realtime_start"))
                realtime_end = _iso_date(raw.get("realtime_end"))
                if (
                    observation_date is None
                    or realtime_start is None
                    or realtime_end is None
                ):
                    raise ProviderUnavailableError(
                        "FRED observation is missing date lineage"
                    )
                records.append(
                    {
                        "series_id": series_id,
                        "region_code": "US",
                        "observation_date": observation_date.isoformat(),
                        "indicator_name": indicator_name,
                        "value": raw_value,
                        "unit": unit,
                        "frequency": frequency,
                        "realtime_start": realtime_start.isoformat(),
                        "realtime_end": realtime_end.isoformat(),
                        "source_locator": (
                            f"fred:series:{series_id}:observation:"
                            f"{observation_date.isoformat()}:vintage:{as_of.isoformat()}"
                        ),
                    }
                )
        return records

    def _load_json(
        self,
        path: str,
        parameters: Sequence[tuple[str, str | int]],
    ) -> JsonObject:
        query = urlencode(
            (*parameters, ("api_key", self._api_key), ("file_type", "json"))
        )
        try:
            payload = json.loads(
                self._http_client.get_text(
                    f"{self._API_ROOT}/{path}?{query}",
                    accept="application/json",
                )
            )
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError("FRED response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("FRED response must be an object")
        return dict(payload)


class AlpacaAdapter(BaseProviderAdapter):
    """Official Alpaca US historical daily-bar and attributed-news adapter."""

    provider_name = "alpaca_market_data"
    market_scope = "US"
    access_mode = "official"
    _BARS_PATH = "/v2/stocks/bars"
    _NEWS_PATH = "/v1beta1/news"
    _FEEDS = frozenset({"iex", "sip"})
    _ADJUSTMENTS = frozenset({"raw", "split", "dividend", "spin-off", "all"})

    def __init__(
        self,
        *,
        api_key_id: str,
        api_secret_key: str,
        api_base_url: str = "https://data.alpaca.markets",
        user_agent: str = "DeepInsight/0.1",
        request_timeout: float = 30.0,
        max_retries: int = 2,
        requests_per_minute: float = 180.0,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        feed: str = "iex",
        adjustment: str = "raw",
        page_limit: int = 10_000,
        max_pages: int = 100,
        news_page_limit: int = 50,
        include_news_content: bool = False,
        http_transport: ProviderHTTPTransport | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """Configure authenticated, bounded access to Alpaca Market Data.

        Args:
            api_key_id: Alpaca Trading API key identifier.
            api_secret_key: Alpaca Trading API secret.
            api_base_url: Alpaca Market Data API origin.
            user_agent: Public application identity.
            request_timeout: Timeout for every HTTPS request.
            max_retries: Maximum additional transient-failure attempts.
            requests_per_minute: Proactive per-adapter request ceiling.
            backoff_base_seconds: Initial exponential retry backoff.
            max_backoff_seconds: Upper bound for one retry delay.
            feed: Historical US stock feed, ``iex`` or ``sip``.
            adjustment: Official Alpaca bar adjustment selection.
            page_limit: Maximum bars requested in one response page.
            max_pages: Safety bound for one range request.
            http_transport: Optional HTTP transport for offline tests.
            clock: Optional monotonic clock for offline tests.
            wall_clock: Optional Unix clock for rate-limit reset tests.
            sleeper: Optional sleep function for offline tests.
        """

        if not api_key_id.strip() or not api_secret_key.strip():
            raise ValueError("Alpaca API key ID and secret are required")
        normalized_base_url = api_base_url.strip().rstrip("/")
        if not normalized_base_url.startswith("https://"):
            raise ValueError("Alpaca API base URL must use HTTPS")
        if not user_agent.strip():
            raise ValueError("Alpaca user agent is required")
        if request_timeout <= 0:
            raise ValueError("Alpaca request timeout must be positive")
        if not 0 <= max_retries <= 5:
            raise ValueError("Alpaca max_retries must be between zero and five")
        if not 0 < requests_per_minute <= 200:
            raise ValueError(
                "Alpaca requests_per_minute must be positive and at most 200"
            )
        if backoff_base_seconds < 0:
            raise ValueError("Alpaca retry backoff cannot be negative")
        if max_backoff_seconds <= 0:
            raise ValueError("Alpaca maximum backoff must be positive")
        if feed not in self._FEEDS:
            raise ValueError("Alpaca feed must be iex or sip")
        if adjustment not in self._ADJUSTMENTS:
            raise ValueError("unsupported Alpaca bar adjustment")
        if not 1 <= page_limit <= 10_000:
            raise ValueError("Alpaca page_limit must be between one and 10000")
        if max_pages <= 0:
            raise ValueError("Alpaca max_pages must be positive")
        if not 1 <= news_page_limit <= 50:
            raise ValueError("Alpaca news_page_limit must be between one and 50")
        self._headers = {
            "APCA-API-KEY-ID": api_key_id.strip(),
            "APCA-API-SECRET-KEY": api_secret_key.strip(),
        }
        self._bars_url = f"{normalized_base_url}{self._BARS_PATH}"
        self._news_url = f"{normalized_base_url}{self._NEWS_PATH}"
        self._max_retries = max_retries
        self._requests_per_minute = requests_per_minute
        self._feed = feed
        self._adjustment = adjustment
        self._page_limit = page_limit
        self._max_pages = max_pages
        self._news_page_limit = news_page_limit
        self._include_news_content = include_news_content
        self._http_client = ProviderHTTPClient(
            user_agent=user_agent,
            request_timeout=request_timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_minute / 60.0,
            backoff_base_seconds=backoff_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
            transport=http_transport,
            clock=clock,
            wall_clock=wall_clock,
            sleeper=sleeper,
        )

    def healthcheck(self) -> JsonObject:
        """Return safe configuration metadata without making a request."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "access_mode": self.access_mode,
            "network_attempted": False,
            "feed": self._feed,
            "adjustment": self._adjustment,
            "max_retries": self._max_retries,
            "requests_per_minute": self._requests_per_minute,
            "capabilities": ["eod_bars", "news"],
            "coverage_scope": _alpaca_coverage_scope(self._feed),
        }

    def fetch_instruments(self) -> Iterable[ProviderRecord]:
        """Return no instrument master data from the historical-bars endpoint."""

        return ()

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return official daily bars for one requested trading date."""

        return self.fetch_eod_bars_range(
            asset_ids,
            target_date,
            target_date,
        )

    def fetch_eod_bars_range(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return official daily bars for an inclusive date range.

        Args:
            asset_ids: Canonical US asset identifiers.
            start_date: Inclusive first trading date.
            end_date: Inclusive last trading date.

        Returns:
            Stable provider records ready for ``DataNormalizer``.

        Raises:
            ValueError: If the range or canonical identifiers are invalid.
            ProviderUnavailableError: If Alpaca returns malformed or
                inconsistent data.
        """

        if end_date < start_date:
            raise ValueError("Alpaca end_date cannot precede start_date")
        symbol_to_asset = _alpaca_symbol_mapping(asset_ids)
        if not symbol_to_asset:
            return ()

        records: list[ProviderRecord] = []
        seen_bars: set[tuple[str, date]] = set()
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        for _ in range(self._max_pages):
            payload = self._load_bars_page(
                symbols=list(symbol_to_asset),
                start_date=start_date,
                end_date=end_date,
                page_token=page_token,
            )
            bars = payload.get("bars")
            if not isinstance(bars, dict):
                raise ProviderUnavailableError(
                    "Alpaca bars response must contain a bars object"
                )
            for symbol, raw_bars in bars.items():
                asset_id = symbol_to_asset.get(str(symbol).upper())
                if asset_id is None:
                    raise ProviderUnavailableError(
                        "Alpaca returned an unrequested stock symbol"
                    )
                if not isinstance(raw_bars, list):
                    raise ProviderUnavailableError(
                        "Alpaca symbol bars must be an array"
                    )
                for raw_bar in raw_bars:
                    record, trade_date = _alpaca_bar_record(
                        asset_id,
                        raw_bar,
                        feed=self._feed,
                        adjustment=self._adjustment,
                    )
                    if not start_date <= trade_date <= end_date:
                        raise ProviderUnavailableError(
                            "Alpaca returned a bar outside the requested range"
                        )
                    identity = (asset_id, trade_date)
                    if identity in seen_bars:
                        raise ProviderUnavailableError(
                            "Alpaca returned a duplicate daily bar"
                        )
                    seen_bars.add(identity)
                    records.append(record)

            token_value = payload.get("next_page_token")
            if token_value is None or token_value == "":
                return records
            if not isinstance(token_value, str):
                raise ProviderUnavailableError(
                    "Alpaca next_page_token must be a string"
                )
            if token_value in seen_page_tokens:
                raise ProviderUnavailableError(
                    "Alpaca returned a repeated pagination token"
                )
            seen_page_tokens.add(token_value)
            page_token = token_value

        raise ProviderUnavailableError("Alpaca pagination exceeded the safety limit")

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return paginated, source-attributed official Alpaca News records."""

        if end_date < start_date:
            raise ValueError("Alpaca news end_date cannot precede start_date")
        symbol_to_asset = _alpaca_symbol_mapping(asset_ids)
        if not symbol_to_asset:
            return ()
        records: list[ProviderRecord] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        seen_news: set[str] = set()
        for _ in range(self._max_pages):
            payload = self._load_news_page(
                symbols=list(symbol_to_asset),
                start_date=start_date,
                end_date=end_date,
                page_token=page_token,
            )
            news = payload.get("news")
            if not isinstance(news, list):
                raise ProviderUnavailableError(
                    "Alpaca news response must contain a news array"
                )
            for raw in news:
                mapped = _alpaca_news_record(
                    raw,
                    symbol_to_asset=symbol_to_asset,
                    include_content=self._include_news_content,
                )
                created_at = datetime.fromisoformat(
                    str(mapped["created_at"]).replace("Z", "+00:00")
                )
                if not start_date <= created_at.date() <= end_date:
                    raise ProviderUnavailableError(
                        "Alpaca returned news outside the requested range"
                    )
                identity = str(mapped["news_id"])
                if identity in seen_news:
                    continue
                seen_news.add(identity)
                records.append(mapped)
            token_value = payload.get("next_page_token")
            if token_value in {None, ""}:
                return records
            if not isinstance(token_value, str) or token_value in seen_tokens:
                raise ProviderUnavailableError(
                    "Alpaca news pagination token is invalid"
                )
            seen_tokens.add(token_value)
            page_token = token_value
        raise ProviderUnavailableError(
            "Alpaca news pagination exceeded the safety limit"
        )

    def _load_news_page(
        self,
        *,
        symbols: list[str],
        start_date: date,
        end_date: date,
        page_token: str | None,
    ) -> JsonObject:
        parameters: list[tuple[str, str | int]] = [
            ("symbols", ",".join(symbols)),
            ("start", start_date.isoformat()),
            ("end", end_date.isoformat()),
            ("limit", self._news_page_limit),
            ("sort", "asc"),
            ("include_content", str(self._include_news_content).lower()),
        ]
        if page_token is not None:
            parameters.append(("page_token", page_token))
        try:
            payload = json.loads(
                self._http_client.get_text(
                    f"{self._news_url}?{urlencode(parameters)}",
                    accept="application/json",
                    headers=self._headers,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                "Alpaca news response was not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("Alpaca news response must be an object")
        return dict(payload)

    def _load_bars_page(
        self,
        *,
        symbols: list[str],
        start_date: date,
        end_date: date,
        page_token: str | None,
    ) -> JsonObject:
        parameters: list[tuple[str, str | int]] = [
            ("symbols", ",".join(symbols)),
            ("timeframe", "1Day"),
            ("start", start_date.isoformat()),
            ("end", end_date.isoformat()),
            ("limit", self._page_limit),
            ("adjustment", self._adjustment),
            ("feed", self._feed),
            ("sort", "asc"),
        ]
        if page_token is not None:
            parameters.append(("page_token", page_token))
        try:
            payload = json.loads(
                self._http_client.get_text(
                    f"{self._bars_url}?{urlencode(parameters)}",
                    accept="application/json",
                    headers=self._headers,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                "Alpaca bars response was not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("Alpaca bars response must be an object")
        return dict(payload)


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


def _alpaca_symbol_mapping(asset_ids: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in asset_ids:
        asset_id = AssetId(value)
        if asset_id.market is not Market.US:
            raise ValueError("Alpaca supports canonical US asset IDs only")
        symbol = str(asset_id).split(":", maxsplit=1)[1]
        existing = mapping.get(symbol)
        if existing is not None and existing != str(asset_id):
            raise ValueError("multiple canonical assets map to one Alpaca symbol")
        mapping[symbol] = str(asset_id)
    return mapping


def _alpaca_bar_record(
    asset_id: str,
    value: object,
    *,
    feed: str,
    adjustment: str,
) -> tuple[ProviderRecord, date]:
    if not isinstance(value, dict):
        raise ProviderUnavailableError("Alpaca bar must be an object")
    timestamp = value.get("t")
    if not isinstance(timestamp, str):
        raise ProviderUnavailableError("Alpaca bar timestamp is required")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderUnavailableError("Alpaca bar timestamp must be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ProviderUnavailableError("Alpaca bar timestamp must include a timezone")
    trade_date = parsed.date()
    return (
        {
            "asset_id": asset_id,
            "market": "US",
            "trade_date": trade_date.isoformat(),
            "open": value.get("o"),
            "high": value.get("h"),
            "low": value.get("l"),
            "close": value.get("c"),
            "adj_close": None,
            "volume": value.get("v"),
            "turnover": None,
            "vwap": value.get("vw"),
            "feed_identity": feed,
            "coverage_scope": (
                f"{_alpaca_coverage_scope(feed)}; adjustment={adjustment}"
            ),
        },
        trade_date,
    )


def _alpaca_coverage_scope(feed: str) -> str:
    if feed == "iex":
        return "IEX single-exchange US equity feed; not consolidated SIP"
    return "SIP consolidated US equity feed"


def _alpaca_news_record(
    value: object,
    *,
    symbol_to_asset: Mapping[str, str],
    include_content: bool,
) -> ProviderRecord:
    if not isinstance(value, dict):
        raise ProviderUnavailableError("Alpaca news item must be an object")
    news_id = str(value.get("id") or "").strip()
    headline = str(value.get("headline") or "").strip()
    created_at = _required_aware_iso(value.get("created_at"), "news created_at")
    updated_at = _required_aware_iso(value.get("updated_at"), "news updated_at")
    source_url = str(value.get("url") or "").strip()
    symbols = value.get("symbols")
    if not news_id or not headline or not source_url or not isinstance(symbols, list):
        raise ProviderUnavailableError("Alpaca news item is missing required fields")
    requested = [
        symbol_to_asset[str(symbol).upper()]
        for symbol in symbols
        if str(symbol).upper() in symbol_to_asset
    ]
    if not requested:
        raise ProviderUnavailableError("Alpaca news item has no requested symbol")
    asset_id = requested[0]
    summary = str(value.get("summary") or "").strip()
    content = str(value.get("content") or "").strip() if include_content else ""
    author = str(value.get("author") or "").strip() or None
    original_source = str(value.get("source") or "").strip() or "unknown"
    raw_text = "\n\n".join(part for part in (headline, summary, content) if part)
    locator = f"alpaca:news:{news_id}"
    return {
        "record_type": "news_evidence",
        "news_id": news_id,
        "document_id": f"alpaca-news-{news_id}",
        "asset_id": asset_id,
        "market": "US",
        "doc_type": "news",
        "title": headline,
        "headline": headline,
        "summary": summary,
        "content": content or None,
        "author": author,
        "language": "en",
        "publisher": original_source,
        "original_source": original_source,
        "publish_ts": created_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "source_url": source_url,
        "source_locator": locator,
        "raw_text": raw_text,
        "metadata": {
            "provider_locator": locator,
            "news_id": news_id,
            "original_source": original_source,
            "symbols": [str(symbol).upper() for symbol in symbols],
        },
    }


def _required_aware_iso(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProviderUnavailableError(f"Alpaca {field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderUnavailableError(f"Alpaca {field} must be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderUnavailableError(f"Alpaca {field} must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _normalize_cik(value: str) -> str:
    digits = value.strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError("SEC CIK must contain at most ten digits")
    return digits.zfill(10)


@dataclass(frozen=True, slots=True)
class _SECFactCandidate:
    """One validated Company Facts value kept inside the SEC Adapter."""

    field_name: str
    value: float
    unit: str
    filed_date: date
    period_end: date
    period_start: date | None
    accession: str
    report_type: str
    concept_priority: int


_SEC_FACT_CONCEPTS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "revenue",
        "us-gaap",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ),
        "USD",
    ),
    ("gross_profit", "us-gaap", ("GrossProfit",), "USD"),
    ("operating_income", "us-gaap", ("OperatingIncomeLoss",), "USD"),
    ("net_income", "us-gaap", ("NetIncomeLoss", "ProfitLoss"), "USD"),
    ("eps_basic", "us-gaap", ("EarningsPerShareBasic",), "USD/shares"),
    ("total_assets", "us-gaap", ("Assets",), "USD"),
    ("current_assets", "us-gaap", ("AssetsCurrent",), "USD"),
    ("total_liabilities", "us-gaap", ("Liabilities",), "USD"),
    ("current_liabilities", "us-gaap", ("LiabilitiesCurrent",), "USD"),
    (
        "total_debt",
        "us-gaap",
        (
            "LongTermDebtAndFinanceLeaseObligations",
            "LongTermDebt",
        ),
        "USD",
    ),
    (
        "shareholders_equity",
        "us-gaap",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "USD",
    ),
    (
        "operating_cash_flow",
        "us-gaap",
        ("NetCashProvidedByUsedInOperatingActivities",),
        "USD",
    ),
    (
        "shares_outstanding",
        "dei",
        ("EntityCommonStockSharesOutstanding",),
        "shares",
    ),
)


def _sec_requested_assets(asset_ids: Sequence[str]) -> set[str]:
    requested: set[str] = set()
    for value in asset_ids:
        asset_id = AssetId(value)
        if asset_id.market is not Market.US:
            raise ValueError("SEC EDGAR supports canonical US asset IDs only")
        requested.add(str(asset_id))
    return requested


def _sec_fundamental_records(
    asset_id: str,
    cik: str,
    payload: JsonObject,
    *,
    start_date: date,
    end_date: date,
    accepted_by_accession: Mapping[str, datetime],
) -> list[tuple[date, str, ProviderRecord]]:
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise ProviderUnavailableError("SEC Company Facts response has no facts object")
    if not isinstance(facts.get("us-gaap"), dict):
        raise ProviderUnavailableError(
            "SEC Company Facts response has no us-gaap taxonomy"
        )

    grouped: dict[
        tuple[str, date, str, date],
        dict[str, _SECFactCandidate],
    ] = {}
    for field_name, taxonomy, concepts, expected_unit in _SEC_FACT_CONCEPTS:
        taxonomy_facts = facts.get(taxonomy)
        if taxonomy_facts is None and taxonomy == "dei":
            continue
        if not isinstance(taxonomy_facts, dict):
            raise ProviderUnavailableError("SEC XBRL taxonomy must be an object")
        for priority, concept in enumerate(concepts):
            concept_payload = taxonomy_facts.get(concept)
            if concept_payload is None:
                continue
            if not isinstance(concept_payload, dict):
                raise ProviderUnavailableError("SEC XBRL concept must be an object")
            units = concept_payload.get("units")
            if not isinstance(units, dict):
                raise ProviderUnavailableError("SEC XBRL concept has no units object")
            raw_values = units.get(expected_unit)
            if raw_values is None:
                continue
            if not isinstance(raw_values, list):
                raise ProviderUnavailableError("SEC XBRL unit values must be an array")
            for raw_value in raw_values:
                candidate = _sec_fact_candidate(
                    field_name,
                    raw_value,
                    expected_unit=expected_unit,
                    concept_priority=priority,
                    start_date=start_date,
                    end_date=end_date,
                )
                if candidate is None:
                    continue
                key = (
                    candidate.accession,
                    candidate.period_end,
                    candidate.report_type,
                    candidate.filed_date,
                )
                selected = grouped.setdefault(key, {}).get(field_name)
                if selected is None or _prefer_sec_candidate(candidate, selected):
                    grouped[key][field_name] = candidate

    result: list[tuple[date, str, ProviderRecord]] = []
    archive_cik = str(int(cik))
    for (accession, period_end, report_type, filed_date), values in grouped.items():
        accession_path = accession.replace("-", "")
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{accession_path}/"
        )
        record: ProviderRecord = {
            "asset_id": asset_id,
            "market": "US",
            "fiscal_period_end": period_end.isoformat(),
            "report_type": report_type,
            "filing_url": filing_url,
            "filing_date": filed_date.isoformat(),
            "accepted_at": (
                accepted_by_accession[accession].isoformat()
                if accession in accepted_by_accession
                else None
            ),
            "source_record_id": f"sec:accession:{accession}",
        }
        record.update({field: candidate.value for field, candidate in values.items()})
        result.append((filed_date, accession, record))
    return result


def _sec_acceptance_by_accession(payload: JsonObject) -> dict[str, datetime]:
    """Map recent SEC accessions to their official accepted timestamps."""

    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        return {}
    accessions = recent.get("accessionNumber")
    accepted = recent.get("acceptanceDateTime")
    filed = recent.get("filingDate")
    if not isinstance(accessions, list) or not isinstance(accepted, list):
        return {}
    result: dict[str, datetime] = {}
    for index, accession in enumerate(accessions):
        if index >= len(accepted):
            break
        filed_date = (
            _iso_date(filed[index])
            if isinstance(filed, list) and index < len(filed)
            else None
        )
        if filed_date is None:
            continue
        result[str(accession)] = datetime.fromisoformat(
            _sec_acceptance_timestamp(accepted[index], filed_date)
        )
    return result


def _sec_fact_candidate(
    field_name: str,
    value: object,
    *,
    expected_unit: str,
    concept_priority: int,
    start_date: date,
    end_date: date,
) -> _SECFactCandidate | None:
    if not isinstance(value, dict):
        raise ProviderUnavailableError("SEC XBRL fact must be an object")
    form = str(value.get("form") or "")
    report_type = _sec_report_type(form)
    if report_type is None:
        return None
    filed_date = _iso_date(value.get("filed"))
    if filed_date is None or not start_date <= filed_date <= end_date:
        return None
    period_end = _iso_date(value.get("end"))
    accession = str(value.get("accn") or "")
    if period_end is None or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ProviderUnavailableError(
            "SEC XBRL fact is missing a valid period end or accession"
        )
    raw_number = value.get("val")
    if isinstance(raw_number, bool) or not isinstance(raw_number, int | float):
        raise ProviderUnavailableError("SEC XBRL fact value must be numeric")
    number = float(raw_number)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ProviderUnavailableError("SEC XBRL fact value must be finite")
    return _SECFactCandidate(
        field_name=field_name,
        value=number,
        unit=expected_unit,
        filed_date=filed_date,
        period_end=period_end,
        period_start=_iso_date(value.get("start")),
        accession=accession,
        report_type=report_type,
        concept_priority=concept_priority,
    )


def _sec_report_type(value: str) -> str | None:
    if value in {"10-Q", "10-Q/A"}:
        return "10-Q"
    if value in {"10-K", "10-K/A"}:
        return "10-K"
    return None


def _prefer_sec_candidate(
    candidate: _SECFactCandidate,
    selected: _SECFactCandidate,
) -> bool:
    if candidate.concept_priority != selected.concept_priority:
        return candidate.concept_priority < selected.concept_priority
    candidate_days = _sec_duration_days(candidate)
    selected_days = _sec_duration_days(selected)
    if candidate.report_type == "10-K":
        return candidate_days > selected_days
    return candidate_days < selected_days


def _sec_duration_days(candidate: _SECFactCandidate) -> int:
    if candidate.period_start is None:
        return 0
    return max((candidate.period_end - candidate.period_start).days, 0)


def _decode_http_payload(payload: bytes, content_encoding: str) -> str:
    return decode_http_payload(payload, content_encoding)


def _recent_filings(recent: JsonObject) -> list[JsonObject]:
    columns = {key: value for key, value in recent.items() if isinstance(value, list)}
    if not columns:
        return []
    length = min(len(value) for value in columns.values())
    return [
        {key: values[index] for key, values in columns.items()}
        for index in range(length)
    ]


def _iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _page_overlaps_window(
    descriptor: Mapping[str, object],
    start_date: date,
    end_date: date,
) -> bool:
    filing_from = _iso_date(descriptor.get("filingFrom"))
    filing_to = _iso_date(descriptor.get("filingTo"))
    if filing_from is None or filing_to is None:
        return False
    return filing_from <= end_date and filing_to >= start_date


def _sec_acceptance_timestamp(value: object, filing_date: date) -> str:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.combine(filing_date, datetime.min.time(), tzinfo=UTC)
    return parsed.isoformat()


class _FilingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


def _html_to_text(value: str) -> str:
    parser = _FilingHTMLParser()
    parser.feed(value)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
