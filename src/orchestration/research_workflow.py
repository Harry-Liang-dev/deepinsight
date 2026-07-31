"""Application orchestration for one Phase One single-asset research report."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol, cast
from uuid import uuid4

import pandas as pd  # type: ignore[import-untyped]

from src.adapters import BaseProviderAdapter
from src.agents import ResearchTaskRequest, ResearchTaskResult
from src.models.enums import AgentStatus, IngestionJobType, MemoryLevel, ReportType
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.reports import ReportAssemblyInput
from src.repositories.records import IngestionJobRecord
from src.schemas.agents import AgentContext
from src.schemas.documents import (
    DocumentChunkRecord,
    RetrievedDocument,
    TextDocumentRecord,
)
from src.schemas.market_data import EodBarRecord, FundamentalRecord
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse
from src.schemas.reports import GenerateReportRequest, ResearchReport
from src.services import IngestionRequest

_FUNDAMENTAL_COLUMNS = (
    "fiscal_period_end",
    "report_type",
    "revenue",
    "net_income",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "current_ratio",
    "pe_ttm",
    "pb",
)
_BAR_COLUMNS = ("trade_date", "close")


class ResearchWorkflowError(RuntimeError):
    """Base error for a report request that cannot complete the workflow."""


class UnsupportedResearchRequestError(ResearchWorkflowError):
    """Raised when a request shape is outside the implemented MVP boundary."""


class MissingResearchEvidenceError(ResearchWorkflowError):
    """Raised when ingestion produces no attributable document evidence."""


class AgentResearchError(ResearchWorkflowError):
    """Raised when the fixed Agent collaboration cannot complete."""


class IngestionRunner(Protocol):
    """Required data-ingestion application boundary."""

    def run(
        self,
        adapter: BaseProviderAdapter,
        request: IngestionRequest,
    ) -> IngestionJobRecord:
        """Normalize and persist one provider ingestion request."""
        ...


class ResearchDataReader(Protocol):
    """Read normalized feature inputs without exposing SQL."""

    def list_eod_bars(
        self,
        asset_id: AssetId,
        *,
        end_date: date,
        limit: int = 60,
    ) -> list[EodBarRecord]:
        """Return recent normalized EOD bars."""
        ...

    def list_fundamentals(
        self,
        asset_id: AssetId,
        *,
        end_date: date,
    ) -> list[FundamentalRecord]:
        """Return normalized fundamental observations."""
        ...


class ResearchDocumentReader(Protocol):
    """Read normalized documents and their chunk sidecars."""

    def list_documents(
        self,
        asset_id: AssetId,
        *,
        end_date: date,
    ) -> list[TextDocumentRecord]:
        """Return documents available for the research date."""
        ...

    def list_chunks(self, document_id: str) -> list[DocumentChunkRecord]:
        """Return ordered chunks for one document."""
        ...


class DocumentIndexer(Protocol):
    """Index pending document chunks before they become research evidence."""

    def index_document(self, document_id: str) -> list[DocumentChunkRecord]:
        """Index and return all chunks for one document."""
        ...


class ResearchMemory(Protocol):
    """Retrieve attributable Memory evidence."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Return ranked Memory results."""
        ...


class FeatureOperator(Protocol):
    """Compute deterministic JSON features from normalized rows."""

    def compute(self, frame: pd.DataFrame) -> JsonObject:
        """Return deterministic feature values and missing-data labels."""
        ...


class AgentCoordinator(Protocol):
    """Run the fixed Phase One Agent collaboration."""

    def run(self, request: ResearchTaskRequest) -> ResearchTaskResult:
        """Return structured Analyst and Manager outputs."""
        ...


class ReportFinalizer(Protocol):
    """Assemble and persist a completed report."""

    def execute(self, payload: ReportAssemblyInput) -> ResearchReport:
        """Return one completed, persisted report."""
        ...


class ResearchWorkflowService:
    """Connect existing Phase One modules without embedding their logic."""

    def __init__(
        self,
        *,
        provider: BaseProviderAdapter,
        ingestion: IngestionRunner,
        market_data: ResearchDataReader,
        documents: ResearchDocumentReader,
        document_indexer: DocumentIndexer,
        memory: ResearchMemory,
        fundamental_features: FeatureOperator,
        technical_features: FeatureOperator,
        coordinator: AgentCoordinator,
        report_pipeline: ReportFinalizer,
        model_name: str,
        clock: Callable[[], datetime] | None = None,
        report_id_factory: Callable[[], str] | None = None,
        task_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Bind replaceable services required by the report request path."""

        if not model_name.strip():
            raise ValueError("model_name cannot be empty")
        self._provider = provider
        self._ingestion = ingestion
        self._market_data = market_data
        self._documents = documents
        self._document_indexer = document_indexer
        self._memory = memory
        self._fundamental_features = fundamental_features
        self._technical_features = technical_features
        self._coordinator = coordinator
        self._report_pipeline = report_pipeline
        self._model_name = model_name
        self._clock = clock or (lambda: datetime.now(UTC))
        self._report_id_factory = report_id_factory or (lambda: f"rep_{uuid4().hex}")
        self._task_id_factory = task_id_factory or (lambda: f"task_{uuid4().hex}")

    def generate(self, request: GenerateReportRequest) -> ResearchReport:
        """Execute the minimum request-to-report Phase One workflow.

        Args:
            request: Validated report-generation request from the API.

        Returns:
            A completed, persisted and attributable research report.

        Raises:
            ResearchWorkflowError: If the request, evidence, or Agent chain
                cannot satisfy the Phase One report contract.
        """

        asset_id = _single_asset(request)
        self._ingestion.run(
            self._provider,
            IngestionRequest(
                job_type=IngestionJobType.INCREMENTAL,
                asset_ids=(str(asset_id),),
                target_date=request.report_date,
                document_start_date=request.report_date,
                document_end_date=request.report_date,
            ),
        )

        documents = self._documents.list_documents(
            asset_id,
            end_date=request.report_date,
        )
        retrieved_documents = self._index_and_collect_documents(documents)
        if not retrieved_documents:
            raise MissingResearchEvidenceError(
                "No attributable document evidence was available."
            )

        features = self._build_features(asset_id, request.report_date)
        memory_query = _memory_query(asset_id, request.report_date)
        memories = self._memory.search(memory_query).results
        context = AgentContext(
            report_date=request.report_date,
            market_scope=request.market_scope,
            asset_id=asset_id,
            structured_features=features,
            retrieved_documents=retrieved_documents,
            retrieved_memories=memories,
        )

        report_id = _required_identifier(
            self._report_id_factory(),
            "report ID",
        )
        task_id = _required_identifier(self._task_id_factory(), "task ID")
        agent_result = self._coordinator.run(
            ResearchTaskRequest(
                task_id=task_id,
                report_id=report_id,
                model_name=self._model_name,
                input_context=context,
            )
        )
        if agent_result.status is not AgentStatus.OK:
            raise AgentResearchError("Agent research did not complete.")

        return self._report_pipeline.execute(
            ReportAssemblyInput(
                report_id=report_id,
                request=request,
                input_context=context,
                agent_result=agent_result,
                created_at=self._clock(),
            )
        )

    def _index_and_collect_documents(
        self,
        documents: list[TextDocumentRecord],
    ) -> list[RetrievedDocument]:
        retrieved: list[RetrievedDocument] = []
        for document in documents:
            indexed = self._document_indexer.index_document(document.document_id)
            for chunk in indexed:
                retrieved.append(
                    RetrievedDocument(
                        document_id=document.document_id,
                        chunk_id=chunk.chunk_id,
                        title=document.title,
                        chunk_text=chunk.chunk_text,
                    )
                )
        return retrieved

    def _build_features(
        self,
        asset_id: AssetId,
        report_date: date,
    ) -> JsonObject:
        fundamentals = self._market_data.list_fundamentals(
            asset_id,
            end_date=report_date,
        )
        bars = self._market_data.list_eod_bars(
            asset_id,
            end_date=report_date,
        )
        fundamental = dict(
            self._fundamental_features.compute(
                _frame(fundamentals, _FUNDAMENTAL_COLUMNS)
            )
        )
        technical = dict(self._technical_features.compute(_frame(bars, _BAR_COLUMNS)))
        fundamental_missing = fundamental.pop("missing_data", [])
        technical_missing = technical.pop("missing_data", [])
        return cast(
            JsonObject,
            {
                **fundamental,
                **technical,
                "fundamental_missing_data": fundamental_missing,
                "technical_missing_data": technical_missing,
            },
        )


def _single_asset(request: GenerateReportRequest) -> AssetId:
    if request.report_type is not ReportType.SINGLE_ASSET:
        raise UnsupportedResearchRequestError(
            "Only single_asset reports are implemented."
        )
    if request.asset_ids is None or len(request.asset_ids) != 1:
        raise UnsupportedResearchRequestError(
            "A single_asset report requires exactly one asset."
        )
    asset_id = request.asset_ids[0]
    if request.market_scope.value != asset_id.market.value:
        raise UnsupportedResearchRequestError(
            "Report market scope does not match the asset."
        )
    return asset_id


def _memory_query(
    asset_id: AssetId,
    report_date: date,
) -> MemorySearchRequest:
    market = asset_id.market.value
    return MemorySearchRequest(
        memory_levels=[MemoryLevel.L1, MemoryLevel.L2, MemoryLevel.L4],
        namespace_keys=["GLOBAL", market, str(asset_id)],
        asset_ids=[asset_id],
        query_text=(
            f"Research evidence for {asset_id} through " f"{report_date.isoformat()}"
        ),
        top_k=8,
        min_importance_score=0.0,
    )


def _frame(
    records: list[EodBarRecord] | list[FundamentalRecord],
    columns: tuple[str, ...],
) -> pd.DataFrame:
    rows = [
        {column: getattr(record, column) for column in columns} for record in records
    ]
    return pd.DataFrame(rows, columns=list(columns))


def _required_identifier(value: str, name: str) -> str:
    if not value.strip():
        raise ResearchWorkflowError(f"{name} cannot be empty")
    return value
