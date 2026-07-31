"""Provider-independent normalization into strict domain records."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

from pydantic import ValidationError

from src.adapters import ProviderRecord
from src.models.enums import DocumentType, Market, MarketScope
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.schemas.documents import TextDocumentRecord
from src.schemas.market_data import EodBarRecord, InstrumentRecord


class NormalizationError(ValueError):
    """Raised when a provider record cannot become a domain record."""


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """Canonical document metadata paired with its unmodified raw text."""

    record: TextDocumentRecord
    raw_text: str


class AssetIdentifierNormalizer:
    """Normalize supported market symbols into canonical asset identifiers."""

    _CN_EXCHANGES = {
        "SH": "SH",
        "SSE": "SH",
        "XSHG": "SH",
        "SZ": "SZ",
        "SZSE": "SZ",
        "XSHE": "SZ",
    }

    def normalize(
        self,
        symbol: object,
        market: object,
        exchange_code: object | None = None,
    ) -> AssetId:
        """Return a canonical CN, HK, or US asset identifier.

        Args:
            symbol: Provider symbol or an already canonical identifier.
            market: Provider-independent CN, HK, or US market code.
            exchange_code: Required for bare mainland-China symbols.

        Returns:
            A validated canonical asset identifier.

        Raises:
            NormalizationError: If the market or symbol is unsupported.
        """

        symbol_text = _required_text(symbol, "symbol").upper()
        if ":" in symbol_text:
            try:
                asset_id = AssetId(symbol_text)
            except ValidationError as exc:
                raise NormalizationError("invalid canonical asset_id") from exc
            expected_market = self._market(market)
            if asset_id.market is not expected_market:
                raise NormalizationError("asset_id market does not match market")
            return asset_id

        normalized_market = self._market(market)
        if normalized_market is Market.US:
            candidate = f"US:{symbol_text}"
        elif normalized_market is Market.HK:
            ticker = symbol_text.removesuffix(".HK")
            if not ticker.isdigit() or not 1 <= len(ticker) <= 5:
                raise NormalizationError("invalid Hong Kong symbol")
            candidate = f"HK:{ticker.zfill(4)}.HK"
        else:
            ticker, exchange = self._normalize_cn_symbol(
                symbol_text,
                exchange_code,
            )
            candidate = f"CN:{ticker}.{exchange}"

        try:
            return AssetId(candidate)
        except ValidationError as exc:
            raise NormalizationError("invalid provider asset symbol") from exc

    @staticmethod
    def _market(value: object) -> Market:
        text = _required_text(value, "market").upper()
        try:
            return Market(text)
        except ValueError as exc:
            raise NormalizationError("unsupported market") from exc

    def _normalize_cn_symbol(
        self,
        symbol: str,
        exchange_code: object | None,
    ) -> tuple[str, str]:
        ticker = symbol
        exchange: str | None = None
        if "." in symbol:
            ticker, exchange = symbol.rsplit(".", maxsplit=1)
        elif len(symbol) == 8 and symbol[:2] in {"SH", "SZ"}:
            exchange, ticker = symbol[:2], symbol[2:]
        if exchange is None:
            try:
                exchange = _required_text(exchange_code, "exchange_code").upper()
            except ValueError as exc:
                raise NormalizationError(
                    "mainland-China symbol requires exchange_code"
                ) from exc
        normalized_exchange = self._CN_EXCHANGES.get(exchange)
        if normalized_exchange is None or len(ticker) != 6 or not ticker.isdigit():
            raise NormalizationError("invalid mainland-China symbol")
        return ticker, normalized_exchange


class DataNormalizer:
    """Create strict domain models from the stable adapter vocabulary."""

    def __init__(
        self,
        identifier_normalizer: AssetIdentifierNormalizer | None = None,
    ) -> None:
        """Initialize with an optional asset identity strategy."""

        self._identifiers = identifier_normalizer or AssetIdentifierNormalizer()

    def normalize_instrument(
        self,
        source_id: str,
        raw: ProviderRecord,
    ) -> InstrumentRecord:
        """Normalize one instrument record.

        Args:
            source_id: Stable provider identifier.
            raw: Adapter record using the ingestion vocabulary.

        Returns:
            A validated instrument domain record.
        """

        try:
            market = Market(_required_text(raw.get("market"), "market").upper())
            exchange_code = _required_text(
                raw.get("exchange_code"),
                "exchange_code",
            ).upper()
            asset_id = self._identifiers.normalize(
                raw.get("asset_id", raw.get("symbol")),
                market.value,
                exchange_code,
            )
            return InstrumentRecord(
                asset_id=asset_id,
                market=market,
                ticker=_ticker(asset_id),
                exchange_code=exchange_code,
                company_name=_optional_text(raw.get("company_name")),
                company_name_en=_optional_text(raw.get("company_name_en")),
                sector_l1=_optional_text(raw.get("sector_l1")),
                sector_l2=_optional_text(raw.get("sector_l2")),
                industry_code=_optional_text(raw.get("industry_code")),
                currency=_optional_text(raw.get("currency")),
                is_active=_optional_bool(raw.get("is_active"), default=True),
                source_primary=_required_text(source_id, "source_id"),
                source_secondary=_optional_text(raw.get("source_secondary")),
                listed_date=_optional_date(raw.get("listed_date"), "listed_date"),
                delisted_date=_optional_date(
                    raw.get("delisted_date"),
                    "delisted_date",
                ),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise _normalization_failure(source_id, "instrument", exc) from exc

    def normalize_eod_bar(
        self,
        source_id: str,
        raw: ProviderRecord,
        *,
        received_at: datetime | None = None,
    ) -> EodBarRecord:
        """Normalize and validate one end-of-day bar."""

        try:
            asset_id = self._identifiers.normalize(
                raw.get("asset_id", raw.get("symbol")),
                raw.get("market"),
                raw.get("exchange_code"),
            )
            prices = {
                name: _optional_float(raw.get(name), name)
                for name in ("open", "high", "low", "close", "adj_close", "vwap")
            }
            if all(prices[name] is None for name in ("open", "high", "low", "close")):
                raise ValueError("EOD bar requires at least one OHLC value")
            _validate_prices(prices)
            volume = _optional_float(raw.get("volume"), "volume")
            turnover = _optional_float(raw.get("turnover"), "turnover")
            if volume is not None and volume < 0:
                raise ValueError("volume cannot be negative")
            if turnover is not None and turnover < 0:
                raise ValueError("turnover cannot be negative")
            return EodBarRecord(
                asset_id=asset_id,
                trade_date=_required_date(raw.get("trade_date"), "trade_date"),
                open=prices["open"],
                high=prices["high"],
                low=prices["low"],
                close=prices["close"],
                adj_close=prices["adj_close"],
                volume=volume,
                turnover=turnover,
                vwap=prices["vwap"],
                source_id=_required_text(source_id, "source_id"),
                ingestion_ts=received_at or datetime.now(UTC),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise _normalization_failure(source_id, "eod_bar", exc) from exc

    def normalize_document(
        self,
        source_id: str,
        raw: ProviderRecord,
        *,
        received_at: datetime | None = None,
    ) -> NormalizedDocument:
        """Normalize document metadata while retaining the original text."""

        try:
            raw_text_value = raw.get("raw_text")
            if not isinstance(raw_text_value, str):
                raise ValueError("raw_text must be a string")
            market = MarketScope(_required_text(raw.get("market"), "market").upper())
            asset_value = raw.get("asset_id", raw.get("symbol"))
            asset_id = (
                None
                if asset_value is None
                else self._identifiers.normalize(
                    asset_value,
                    market.value,
                    raw.get("exchange_code"),
                )
            )
            publish_ts = _optional_datetime(raw.get("publish_ts"), "publish_ts")
            title = _required_text(raw.get("title"), "title")
            document_id = _document_id(
                source_id,
                raw,
                title=title,
                publish_ts=publish_ts,
            )
            checksum = hashlib.sha256(raw_text_value.encode("utf-8")).hexdigest()
            metadata = _optional_object(raw.get("metadata"), "metadata")
            return NormalizedDocument(
                record=TextDocumentRecord(
                    document_id=document_id,
                    asset_id=asset_id,
                    market=market,
                    doc_type=DocumentType(
                        _required_text(raw.get("doc_type"), "doc_type").lower()
                    ),
                    title=title,
                    language=_optional_text(raw.get("language")) or "en",
                    publisher=_optional_text(raw.get("publisher")),
                    publish_ts=publish_ts,
                    source_id=_required_text(source_id, "source_id"),
                    source_url=_optional_text(raw.get("source_url")),
                    checksum_sha256=checksum,
                    metadata_json=metadata,
                    created_at=received_at or datetime.now(UTC),
                ),
                raw_text=raw_text_value,
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise _normalization_failure(source_id, "document", exc) from exc


def _normalization_failure(
    source_id: str,
    object_type: str,
    cause: Exception,
) -> NormalizationError:
    detail = str(cause).splitlines()[0]
    return NormalizationError(
        f"{source_id} {object_type} normalization failed: {detail}"
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional text value must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError("boolean value must be true or false")
    return value


def _optional_float(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"{field} must be numeric")
    try:
        normalized = float(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _required_date(value: object, field: str) -> date:
    parsed = _optional_date(value, field)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _optional_date(value: object, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc
    raise TypeError(f"{field} must be a date")


def _optional_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    raise TypeError(f"{field} must be a datetime")


def _optional_object(value: object, field: str) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    return cast(JsonObject, value)


def _ticker(asset_id: AssetId) -> str:
    value = str(asset_id).split(":", maxsplit=1)[1]
    return value.removesuffix(".SH").removesuffix(".SZ").removesuffix(".HK")


def _validate_prices(prices: dict[str, float | None]) -> None:
    for name, value in prices.items():
        if value is not None and value < 0:
            raise ValueError(f"{name} cannot be negative")
    comparison = [
        value
        for name in ("open", "low", "close")
        if (value := prices[name]) is not None
    ]
    high = prices["high"]
    if high is not None and comparison and high < max(comparison):
        raise ValueError("high cannot be below open, low, or close")
    comparison = [
        value
        for name in ("open", "high", "close")
        if (value := prices[name]) is not None
    ]
    low = prices["low"]
    if low is not None and comparison and low > min(comparison):
        raise ValueError("low cannot exceed open, high, or close")


def _document_id(
    source_id: str,
    raw: ProviderRecord,
    *,
    title: str,
    publish_ts: datetime | None,
) -> str:
    supplied = _optional_text(raw.get("document_id"))
    if supplied is not None:
        return supplied
    locator = _optional_text(raw.get("source_record_id")) or _optional_text(
        raw.get("source_url")
    )
    if locator is None:
        locator = f"{title}|{publish_ts.isoformat() if publish_ts else ''}"
    digest = hashlib.sha256(f"{source_id}|{locator}".encode()).hexdigest()
    return f"doc_{digest[:24]}"
