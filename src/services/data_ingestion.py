"""Synchronous Phase One ingestion orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from src.adapters import BaseProviderAdapter, ProviderAdapterError
from src.models.enums import IngestionJobType, MarketScope, TaskStatus
from src.repositories import (
    DocumentRepository,
    IngestionJobRecord,
    IngestionJobRepository,
    InstrumentRepository,
    MarketDataRepository,
    RepositoryError,
)
from src.services.data_normalization import DataNormalizer, NormalizationError
from src.services.document_processing import DocumentChunker, RawTextStore


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
    document_start_date: date | None = None
    document_end_date: date | None = None

    def __post_init__(self) -> None:
        """Validate optional document range pairing and order."""

        start = self.document_start_date
        end = self.document_end_date
        if (start is None) is not (end is None):
            raise ValueError("document start and end dates must be supplied together")
        if start is not None and end is not None and end < start:
            raise ValueError("document end date cannot precede start date")


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
            target_date=request.target_date,
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

            if request.target_date is not None:
                for raw in adapter.fetch_eod_bars(
                    list(request.asset_ids),
                    request.target_date,
                ):
                    bar_record = self._normalizer.normalize_eod_bar(
                        adapter.provider_name,
                        raw,
                        received_at=self._clock(),
                    )
                    if bar_record.trade_date != request.target_date:
                        raise NormalizationError(
                            "provider returned an EOD bar outside target_date"
                        )
                    if (
                        request.asset_ids
                        and str(bar_record.asset_id) not in request.asset_ids
                    ):
                        raise NormalizationError(
                            "provider returned an unrequested EOD asset"
                        )
                    self._market_data.upsert_eod_bar(bar_record)
                    rows_written += 1

            if request.document_start_date is not None:
                assert request.document_end_date is not None
                for raw in adapter.fetch_documents(
                    list(request.asset_ids),
                    request.document_start_date,
                    request.document_end_date,
                ):
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
