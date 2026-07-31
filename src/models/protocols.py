"""Structural interfaces connecting Phase One modules."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.models.types import JsonObject
    from src.schemas.documents import TextDocumentRecord
    from src.schemas.llm import LLMRequest, LLMResponse
    from src.schemas.market_data import EodBarRecord, InstrumentRecord
    from src.schemas.memory import (
        MemorySearchRequest,
        MemorySearchResponse,
        MemoryWriteRequest,
        MemoryWriteResult,
    )
    from src.schemas.reports import GenerateReportRequest, ResearchReport

RequestT = TypeVar("RequestT", contravariant=True)
ResponseT = TypeVar("ResponseT", covariant=True)


class ProviderAdapterProtocol(Protocol):
    """Minimum typed interface shared by market data providers."""

    def healthcheck(self) -> JsonObject:
        """Return provider health metadata."""
        ...

    def fetch_instruments(self) -> Iterable[InstrumentRecord]:
        """Return normalized instrument records."""
        ...

    def fetch_eod_bars(
        self,
        asset_ids: list[str],
        target_date: date,
    ) -> Iterable[EodBarRecord]:
        """Return normalized end-of-day bars."""
        ...

    def fetch_documents(
        self,
        asset_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> Iterable[TextDocumentRecord]:
        """Return normalized text documents."""
        ...


class MemoryServiceProtocol(Protocol):
    """Typed boundary for local memory storage and retrieval."""

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Write one memory item."""
        ...

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Search memory namespaces."""
        ...


class LLMGatewayProtocol(Protocol):
    """Typed boundary for structured LLM inference."""

    def invoke_json(self, request: LLMRequest) -> LLMResponse:
        """Invoke an LLM and return a structured response."""
        ...


class AgentProtocol(Protocol[RequestT, ResponseT]):
    """Generic typed interface implemented by analyst and manager agents."""

    def run(self, payload: RequestT) -> ResponseT:
        """Run an agent over a validated request."""
        ...


class ReportPipelineProtocol(Protocol):
    """Typed boundary for the research report pipeline."""

    def execute(self, request: GenerateReportRequest) -> ResearchReport:
        """Generate one research report."""
        ...
