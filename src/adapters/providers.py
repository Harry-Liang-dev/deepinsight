"""Phase One provider placeholders and the deterministic offline provider."""

from __future__ import annotations

import gzip
import json
import re
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
        max_documents: int = 1,
        fetch_text: Callable[[str], str] | None = None,
    ) -> None:
        """Configure identified, bounded access to official SEC endpoints."""

        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError("SEC user agent must include a contact email")
        if not cik_by_asset:
            raise ValueError("at least one SEC asset/CIK mapping is required")
        if request_timeout <= 0:
            raise ValueError("SEC request timeout must be positive")
        if max_documents <= 0:
            raise ValueError("SEC max_documents must be positive")
        self._user_agent = user_agent.strip()
        self._cik_by_asset = {
            asset_id.upper(): _normalize_cik(cik)
            for asset_id, cik in cik_by_asset.items()
        }
        self._request_timeout = request_timeout
        self._max_documents = max_documents
        self._fetch_text = fetch_text or self._request
        self._submissions: dict[str, JsonObject] = {}

    def healthcheck(self) -> JsonObject:
        """Return configured status without making a network request."""

        return {
            "provider": self.provider_name,
            "market_scope": self.market_scope,
            "status": "configured",
            "access_mode": self.access_mode,
            "network_attempted": False,
            "asset_count": len(self._cik_by_asset),
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
            filings = submissions.get("filings")
            recent = filings.get("recent") if isinstance(filings, dict) else None
            if not isinstance(recent, dict):
                raise ProviderUnavailableError(
                    "SEC submissions response has no recent filings"
                )
            for filing in _recent_filings(recent):
                filing_date = _iso_date(filing.get("filingDate"))
                if (
                    filing.get("form") not in {"10-K", "10-Q"}
                    or filing_date is None
                    or not start_date <= filing_date <= end_date
                ):
                    continue
                accession = str(filing.get("accessionNumber") or "")
                primary_document = str(filing.get("primaryDocument") or "")
                if not accession or not primary_document:
                    continue
                archive_cik = str(int(cik))
                accession_path = accession.replace("-", "")
                source_url = (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{archive_cik}/{accession_path}/{primary_document}"
                )
                raw_text = _html_to_text(self._fetch_text(source_url))
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
                        "publisher": "U.S. Securities and Exchange Commission",
                        "publish_ts": accepted,
                        "source_url": source_url,
                        "raw_text": raw_text,
                        "metadata": {
                            "cik": cik,
                            "accession_number": accession,
                            "primary_document": primary_document,
                            "form": form,
                            "filing_date": filing_date.isoformat(),
                        },
                    }
                )
                if len(records) >= self._max_documents:
                    return records
        return records

    def _load_submissions(self, cik: str) -> JsonObject:
        cached = self._submissions.get(cik)
        if cached is not None:
            return cached
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            decoded = json.loads(self._fetch_text(url))
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                "SEC submissions response was not valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderUnavailableError("SEC submissions response must be an object")
        result = dict(decoded)
        self._submissions[cik] = result
        return result

    def _request(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json,text/html",
            },
        )
        try:
            with urlopen(request, timeout=self._request_timeout) as response:
                return _decode_http_payload(
                    response.read(),
                    response.headers.get("Content-Encoding", ""),
                )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError("SEC EDGAR request failed") from exc


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


def _normalize_cik(value: str) -> str:
    digits = value.strip()
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError("SEC CIK must contain at most ten digits")
    return digits.zfill(10)


def _decode_http_payload(payload: bytes, content_encoding: str) -> str:
    encoding = content_encoding.lower().strip()
    if encoding == "gzip":
        payload = gzip.decompress(payload)
    elif encoding == "deflate":
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            payload = zlib.decompress(payload, -zlib.MAX_WBITS)
    return payload.decode("utf-8", errors="replace")


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
