"""Synchronous Phase One ingestion orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable
from uuid import uuid4

from src.adapters import BaseProviderAdapter, ProviderAdapterError, ProviderRecord
from src.models.enums import (
    EventSeverity,
    IngestionJobType,
    Market,
    MarketScope,
    TaskStatus,
)
from src.repositories import (
    DocumentRepository,
    IngestionJobRecord,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
    RepositoryError,
)
from src.schemas.market_data import CorporateEventRecord
from src.services.data_normalization import DataNormalizer, NormalizationError
from src.services.document_processing import DocumentChunker, RawTextStore


@runtime_checkable
class EodRangeProvider(Protocol):
    """Optional Provider capability for bounded EOD range ingestion."""

    def fetch_eod_bars_range(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return provider records for an inclusive date range."""
        ...


@runtime_checkable
class FundamentalRangeProvider(Protocol):
    """Optional Provider capability for bounded filing-date ingestion."""

    def fetch_fundamentals_range(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]:
        """Return fundamental records filed in an inclusive date range."""

        ...


@runtime_checkable
class MacroSeriesProvider(Protocol):
    """Optional Provider capability for vintage-aware macro ingestion."""

    def fetch_macro_series(
        self,
        series_ids: tuple[str, ...],
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> Iterable[ProviderRecord]: ...


@runtime_checkable
class SentimentRangeProvider(Protocol):
    """Optional Provider capability for bounded community-signal ingestion."""

    def fetch_sentiment_range(
        self,
        asset_ids: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> Iterable[ProviderRecord]: ...


class IngestionRunError(RuntimeError):
    """Raised after an ingestion failure has been persisted."""

    def __init__(self, job_id: str) -> None:
        """Create a stable public error tied to the failed job."""

        self.job_id = job_id
        super().__init__(f"ingestion job {job_id} failed")


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    """Validated parameters for one full, incremental, or repair job."""

    job_type: IngestionJobType
    asset_ids: tuple[str, ...] = ()
    target_date: date | None = None
    eod_start_date: date | None = None
    eod_end_date: date | None = None
    fundamental_start_date: date | None = None
    fundamental_end_date: date | None = None
    document_start_date: date | None = None
    document_end_date: date | None = None
    macro_series_ids: tuple[str, ...] = ()
    macro_start_date: date | None = None
    macro_end_date: date | None = None
    macro_as_of: date | None = None
    sentiment_start_date: date | None = None
    sentiment_end_date: date | None = None

    def __post_init__(self) -> None:
        """Validate optional document range pairing and order."""

        start = self.document_start_date
        end = self.document_end_date
        if (start is None) is not (end is None):
            raise ValueError("document start and end dates must be supplied together")
        if start is not None and end is not None and end < start:
            raise ValueError("document end date cannot precede start date")
        eod_start = self.eod_start_date
        eod_end = self.eod_end_date
        if (eod_start is None) is not (eod_end is None):
            raise ValueError("EOD start and end dates must be supplied together")
        if eod_start is not None and eod_end is not None and eod_end < eod_start:
            raise ValueError("EOD end date cannot precede start date")
        if self.target_date is not None and eod_start is not None:
            raise ValueError("target_date and EOD range are mutually exclusive")
        fundamental_start = self.fundamental_start_date
        fundamental_end = self.fundamental_end_date
        if (fundamental_start is None) is not (fundamental_end is None):
            raise ValueError(
                "fundamental start and end dates must be supplied together"
            )
        if (
            fundamental_start is not None
            and fundamental_end is not None
            and fundamental_end < fundamental_start
        ):
            raise ValueError("fundamental end date cannot precede start date")
        macro_values = (self.macro_start_date, self.macro_end_date, self.macro_as_of)
        if any(value is not None for value in macro_values) and not all(
            value is not None for value in macro_values
        ):
            raise ValueError("macro start, end, and as_of must be supplied together")
        if (
            self.macro_start_date is not None
            and self.macro_end_date is not None
            and self.macro_end_date < self.macro_start_date
        ):
            raise ValueError("macro end date cannot precede start date")
        if (
            self.macro_end_date is not None
            and self.macro_as_of is not None
            and self.macro_end_date > self.macro_as_of
        ):
            raise ValueError("macro end date cannot exceed as_of")
        if (self.sentiment_start_date is None) is not (self.sentiment_end_date is None):
            raise ValueError("sentiment start and end dates must be supplied together")
        if (
            self.sentiment_start_date is not None
            and self.sentiment_end_date is not None
            and self.sentiment_end_date < self.sentiment_start_date
        ):
            raise ValueError("sentiment end date cannot precede start date")


class DataIngestionService:
    """Normalize and persist one provider job with explicit lifecycle state."""

    def __init__(
        self,
        *,
        instruments: InstrumentRepository,
        market_data: MarketDataRepository,
        documents: DocumentRepository,
        jobs: IngestionJobRepository,
        normalizer: DataNormalizer,
        raw_text_store: RawTextStore,
        chunker: DocumentChunker,
        clock: Callable[[], datetime] | None = None,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Bind replaceable adapters and storage dependencies."""

        self._instruments = instruments
        self._market_data = market_data
        self._documents = documents
        self._jobs = jobs
        self._normalizer = normalizer
        self._raw_text_store = raw_text_store
        self._chunker = chunker
        self._clock = clock or (lambda: datetime.now(UTC))
        self._job_id_factory = job_id_factory or (lambda: uuid4().hex)

    def run(
        self,
        adapter: BaseProviderAdapter,
        request: IngestionRequest,
    ) -> IngestionJobRecord:
        """Run one provider ingestion job.

        Successfully persisted rows remain attributable if a later provider
        stream fails; the final job record reports ``failed`` and the exact
        number of committed rows.
        """

        job_id = self._job_id_factory()
        started_at = self._clock()
        job = IngestionJobRecord(
            job_id=job_id,
            source_id=adapter.provider_name,
            job_type=request.job_type,
            market_scope=_market_scope(adapter.market_scope),
            target_date=(
                request.target_date
                or request.eod_end_date
                or request.fundamental_end_date
                or request.macro_end_date
                or request.sentiment_end_date
            ),
            status=TaskStatus.RUNNING.value,
            started_at=started_at,
        )
        self._jobs.save(job)
        rows_written = 0
        try:
            for raw in adapter.fetch_instruments():
                instrument_record = self._normalizer.normalize_instrument(
                    adapter.provider_name,
                    raw,
                )
                self._instruments.upsert(instrument_record)
                rows_written += 1

            if request.eod_start_date is not None:
                assert request.eod_end_date is not None
                if not isinstance(adapter, EodRangeProvider):
                    raise ProviderAdapterError(
                        "provider does not support EOD range ingestion"
                    )
                raw_bars = adapter.fetch_eod_bars_range(
                    list(request.asset_ids),
                    request.eod_start_date,
                    request.eod_end_date,
                )
                rows_written += self._persist_eod_bars(
                    adapter,
                    request,
                    raw_bars,
                    request.eod_start_date,
                    request.eod_end_date,
                )
            elif request.target_date is not None:
                rows_written += self._persist_eod_bars(
                    adapter,
                    request,
                    adapter.fetch_eod_bars(
                        list(request.asset_ids),
                        request.target_date,
                    ),
                    request.target_date,
                    request.target_date,
                )

            if request.fundamental_start_date is not None:
                assert request.fundamental_end_date is not None
                if not isinstance(adapter, FundamentalRangeProvider):
                    raise ProviderAdapterError(
                        "provider does not support fundamental range ingestion"
                    )
                rows_written += self._persist_fundamentals(
                    adapter,
                    request,
                    adapter.fetch_fundamentals_range(
                        list(request.asset_ids),
                        request.fundamental_start_date,
                        request.fundamental_end_date,
                    ),
                )

            if request.macro_start_date is not None:
                assert request.macro_end_date is not None
                assert request.macro_as_of is not None
                if not isinstance(adapter, MacroSeriesProvider):
                    raise ProviderAdapterError(
                        "provider does not support macro-series ingestion"
                    )
                for raw in adapter.fetch_macro_series(
                    request.macro_series_ids,
                    request.macro_start_date,
                    request.macro_end_date,
                    request.macro_as_of,
                ):
                    record = self._normalizer.normalize_macro_observation(
                        adapter.provider_name,
                        raw,
                        received_at=self._clock(),
                    )
                    self._market_data.upsert_macro_observation(record)
                    rows_written += 1

            if request.sentiment_start_date is not None:
                assert request.sentiment_end_date is not None
                if not isinstance(adapter, SentimentRangeProvider):
                    raise ProviderAdapterError(
                        "provider does not support sentiment-range ingestion"
                    )
                for raw in adapter.fetch_sentiment_range(
                    request.asset_ids,
                    request.sentiment_start_date,
                    request.sentiment_end_date,
                ):
                    record_type = raw.get("record_type")
                    if record_type == "sentiment_snapshot":
                        snapshot = self._normalizer.normalize_sentiment_snapshot(
                            adapter.provider_name,
                            raw,
                            received_at=self._clock(),
                        )
                        self._market_data.upsert_sentiment_snapshot(snapshot)
                    elif record_type == "sentiment_evidence":
                        evidence = self._normalizer.normalize_sentiment_evidence(
                            adapter.provider_name,
                            raw,
                            received_at=self._clock(),
                        )
                        self._market_data.upsert_sentiment_evidence(evidence)
                    else:
                        raise NormalizationError(
                            "provider returned an unknown sentiment record type"
                        )
                    rows_written += 1

            if request.document_start_date is not None:
                assert request.document_end_date is not None
                for raw in adapter.fetch_documents(
                    list(request.asset_ids),
                    request.document_start_date,
                    request.document_end_date,
                ):
                    if raw.get("record_type") == "news_evidence":
                        news = self._normalizer.normalize_news_evidence(
                            adapter.provider_name,
                            raw,
                            received_at=self._clock(),
                        )
                        self._market_data.upsert_news_evidence(news)
                        rows_written += 1
                    normalized = self._normalizer.normalize_document(
                        adapter.provider_name,
                        raw,
                        received_at=self._clock(),
                    )
                    publish_ts = normalized.record.publish_ts
                    if publish_ts is not None and not (
                        request.document_start_date
                        <= publish_ts.date()
                        <= request.document_end_date
                    ):
                        raise NormalizationError(
                            "provider returned a document outside requested range"
                        )
                    if (
                        request.asset_ids
                        and normalized.record.asset_id is not None
                        and str(normalized.record.asset_id) not in request.asset_ids
                    ):
                        raise NormalizationError(
                            "provider returned an unrequested document asset"
                        )
                    raw_path = self._raw_text_store.write(
                        adapter.provider_name,
                        normalized.record.document_id,
                        normalized.raw_text,
                    )
                    document = normalized.record.model_copy(
                        update={"raw_text_path": raw_path}
                    )
                    self._documents.upsert_document(document)
                    rows_written += 1
                    if document.asset_id is not None and publish_ts is not None:
                        self._market_data.upsert_corporate_event(
                            CorporateEventRecord(
                                event_id=f"event:{document.document_id}",
                                asset_id=document.asset_id,
                                market=Market(document.market.value),
                                event_date=publish_ts,
                                event_type=(
                                    "filing"
                                    if document.doc_type.value == "filing"
                                    else "other"
                                ),
                                severity=EventSeverity.LOW,
                                title=document.title,
                                source_document_id=document.document_id,
                                source_id=document.source_id,
                                has_document=True,
                            )
                        )
                        rows_written += 1
                    for chunk in self._chunker.chunk(
                        document,
                        normalized.raw_text,
                        created_at=self._clock(),
                    ):
                        self._documents.upsert_chunk(chunk)
                        rows_written += 1
        except Exception as exc:
            failed = job.model_copy(
                update={
                    "status": TaskStatus.FAILED.value,
                    "finished_at": self._clock(),
                    "rows_written": rows_written,
                    "error_message": _safe_error_message(exc),
                }
            )
            self._jobs.save(failed)
            raise IngestionRunError(job_id) from exc

        completed = job.model_copy(
            update={
                "status": TaskStatus.COMPLETED.value,
                "finished_at": self._clock(),
                "rows_written": rows_written,
            }
        )
        self._jobs.save(completed)
        return completed

    def _persist_eod_bars(
        self,
        adapter: BaseProviderAdapter,
        request: IngestionRequest,
        raw_bars: Iterable[ProviderRecord],
        start_date: date,
        end_date: date,
    ) -> int:
        """Normalize, validate, and persist one bounded EOD stream."""

        rows_written = 0
        for raw in raw_bars:
            bar_record = self._normalizer.normalize_eod_bar(
                adapter.provider_name,
                raw,
                received_at=self._clock(),
            )
            if not start_date <= bar_record.trade_date <= end_date:
                raise NormalizationError(
                    "provider returned an EOD bar outside requested range"
                )
            if request.asset_ids and str(bar_record.asset_id) not in request.asset_ids:
                raise NormalizationError("provider returned an unrequested EOD asset")
            self._market_data.upsert_eod_bar(bar_record)
            rows_written += 1
        return rows_written

    def _persist_fundamentals(
        self,
        adapter: BaseProviderAdapter,
        request: IngestionRequest,
        raw_records: Iterable[ProviderRecord],
    ) -> int:
        """Normalize and idempotently persist one fundamental stream."""

        rows_written = 0
        for raw in raw_records:
            record = self._normalizer.normalize_fundamental(
                adapter.provider_name,
                raw,
                received_at=self._clock(),
            )
            if request.asset_ids and str(record.asset_id) not in request.asset_ids:
                raise NormalizationError(
                    "provider returned an unrequested fundamental asset"
                )
            self._market_data.upsert_fundamental(record)
            rows_written += 1
        return rows_written


def _market_scope(value: str) -> MarketScope:
    try:
        return MarketScope(value.upper())
    except ValueError as exc:
        raise ValueError("provider has unsupported market_scope") from exc


def _safe_error_message(error: Exception) -> str:
    if not isinstance(
        error,
        ProviderAdapterError | NormalizationError | RepositoryError,
    ):
        if isinstance(error, OSError):
            return "raw text persistence failed"
        return f"unexpected {type(error).__name__} during ingestion"
    message = str(error).replace("\n", " ").strip()
    if not message:
        message = type(error).__name__
    return message[:1000]
