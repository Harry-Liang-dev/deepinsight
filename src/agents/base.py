"""Shared Agent execution, retrieval, validation, and audit behavior."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol, cast

from pydantic import ValidationError

from src.agents.contracts import (
    AgentExecutionResult,
    AgentInvocation,
    EvidenceLink,
    PromptTemplate,
)
from src.models.enums import AgentName, AgentStatus
from src.models.types import DomainModel, JsonObject, JsonValue
from src.repositories.records import AgentRunRecord
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse


class AgentOutputError(RuntimeError):
    """Raised when an Agent produces unsupported or unattributable output."""


class AgentGateway(Protocol):
    """Narrow public LLM Gateway boundary used by Agents."""

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        """Return structured JSON through the configured Gateway."""
        ...


class AgentMemory(Protocol):
    """Narrow public Memory boundary used by Agents."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResponse:
        """Return attributable Memory search results."""
        ...


class AgentPromptLoader(Protocol):
    """Prompt configuration boundary used by Agents."""

    def load(self, agent_name: AgentName) -> PromptTemplate:
        """Return one versioned system prompt."""
        ...


class AgentRunLogger(Protocol):
    """Persistence boundary for Agent execution audit records."""

    def save(self, record: AgentRunRecord) -> None:
        """Persist one Agent run state."""
        ...


class BaseAgent:
    """Execute one role through public Memory and LLM interfaces."""

    agent_name: AgentName
    agent_role: str
    request_model: type[DomainModel]
    response_model: type[DomainModel]
    claim_list_paths: tuple[str, ...] = ()
    scalar_claim_paths: tuple[str, ...] = ()
    response_citation_path: str | None = None
    uncertainty_path: str | None = None
    inherit_input_citations = False

    def __init__(
        self,
        llm_gateway: AgentGateway,
        memory_service: AgentMemory,
        prompt_loader: AgentPromptLoader,
        run_logger: AgentRunLogger,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind replaceable public dependencies.

        Args:
            llm_gateway: Sole structured text-inference entry point.
            memory_service: Public attributable semantic Memory service.
            prompt_loader: Versioned prompt configuration loader.
            run_logger: Agent run persistence boundary.
            clock: Optional deterministic UTC clock for tests.
        """

        self._llm_gateway = llm_gateway
        self._memory_service = memory_service
        self._prompt_loader = prompt_loader
        self._run_logger = run_logger
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(self, payload: AgentInvocation) -> AgentExecutionResult:
        """Run the Agent and return a validated, evidence-linked result.

        Args:
            payload: Unified invocation with typed model and optional Memory query.

        Returns:
            Successful structured output or a stable explicit error result.
        """

        started_at = self._clock()
        timer = monotonic()
        prompt_version = "unavailable"
        enriched = _copy_json(payload.input_payload)
        retrieval_context: JsonObject = {"memories": []}
        retrieval_uncertainties: list[str] = []

        if payload.memory_query is not None:
            try:
                memory_response = self._memory_service.search(payload.memory_query)
                memories: list[JsonValue] = [
                    cast(JsonObject, item.model_dump(mode="json"))
                    for item in memory_response.results
                ]
                retrieval_context = {"memories": memories}
                _merge_memories(enriched, memories)
            except Exception:
                retrieval_uncertainties.append("Memory retrieval was unavailable.")

        retrieval_context = _retrieval_context(enriched)
        missing_data = _missing_data(enriched)
        try:
            request = self.request_model.model_validate(enriched)
            self._validate_role(request)
            prompt = self._prompt_loader.load(self.agent_name)
            prompt_version = prompt.version
            raw_output = self._llm_gateway.invoke_json(
                payload.model_name,
                prompt.system_prompt,
                cast(JsonObject, request.model_dump(mode="json")),
            )
            response = self.response_model.model_validate(raw_output)
            self._validate_role(response)
            output = cast(JsonObject, response.model_dump(mode="json"))
            _reject_trading_output(output)
            evidence = self._build_evidence(enriched, output)
            uncertainties = _unique(
                retrieval_uncertainties + self._output_uncertainties(output)
            )
            result = AgentExecutionResult(
                run_id=payload.run_id,
                agent_name=self.agent_name,
                status=AgentStatus.OK,
                output=output,
                evidence=evidence,
                missing_data=missing_data,
                uncertainties=uncertainties,
            )
            error_message = None
        except ValidationError as exc:
            result = self._error_result(
                payload.run_id,
                code="schema_validation",
                message="Agent input or output failed schema validation.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
            )
            error_message = _validation_error_summary(exc)
        except AgentOutputError as exc:
            result = self._error_result(
                payload.run_id,
                code="evidence_validation",
                message=str(exc),
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
            )
            error_message = str(exc)
        except Exception:
            result = self._error_result(
                payload.run_id,
                code="agent_execution",
                message="Agent execution failed.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                retryable=True,
            )
            error_message = "Agent execution failed."

        finished_at = self._clock()
        latency_ms = max(0, round((monotonic() - timer) * 1000))
        self._run_logger.save(
            AgentRunRecord(
                run_id=payload.run_id,
                report_id=payload.report_id,
                agent_name=self.agent_name,
                agent_role=self.agent_role,
                model_name=payload.model_name,
                prompt_template_ver=prompt_version,
                input_payload=_invocation_audit_payload(payload),
                retrieved_context=retrieval_context,
                output_payload=result.output,
                status=result.status.value,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        )
        return result

    def _validate_role(self, model: DomainModel) -> None:
        configured_name: object = getattr(model, "agent_name", None)
        if (
            isinstance(configured_name, AgentName)
            and configured_name is not self.agent_name
        ):
            raise AgentOutputError(
                "Agent payload role does not match the invoked Agent."
            )
        configured_status: object = getattr(model, "status", None)
        if (
            isinstance(configured_status, AgentStatus)
            and configured_status is not AgentStatus.OK
        ):
            raise AgentOutputError("Agent returned a non-success business response.")

    def _build_evidence(
        self,
        input_payload: JsonObject,
        output: JsonObject,
    ) -> list[EvidenceLink]:
        allowed = _allowed_citations(input_payload)
        if self.inherit_input_citations:
            citations = _input_output_citations(input_payload)
        elif self.response_citation_path is not None:
            citations = _citations_at_path(output, self.response_citation_path)
        else:
            citations = []

        invalid = [
            citation for citation in citations if _citation_key(citation) not in allowed
        ]
        if invalid:
            raise AgentOutputError("Agent output cited evidence absent from its input.")

        claim_paths = self._claim_paths(output)
        if claim_paths and not citations:
            raise AgentOutputError("Agent conclusions require attributable citations.")
        return [
            EvidenceLink(claim_path=claim_path, citations=citations)
            for claim_path in claim_paths
        ]

    def _claim_paths(self, output: JsonObject) -> list[str]:
        paths = list(self.scalar_claim_paths)
        for list_path in self.claim_list_paths:
            value = _value_at_path(output, list_path)
            if isinstance(value, list):
                paths.extend(f"{list_path}[{index}]" for index in range(len(value)))
        return paths

    def _output_uncertainties(self, output: JsonObject) -> list[str]:
        if self.uncertainty_path is None:
            return []
        value = _value_at_path(output, self.uncertainty_path)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _error_result(
        self,
        run_id: str,
        *,
        code: str,
        message: str,
        missing_data: list[str],
        uncertainties: list[str],
        retryable: bool = False,
    ) -> AgentExecutionResult:
        return AgentExecutionResult(
            run_id=run_id,
            agent_name=self.agent_name,
            status=AgentStatus.ERROR,
            missing_data=missing_data,
            uncertainties=uncertainties,
            error=ErrorInfo(code=code, message=message, retryable=retryable),
        )


def _copy_json(value: JsonObject) -> JsonObject:
    return cast(JsonObject, _copy_json_value(value))


def _copy_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _copy_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _merge_memories(payload: JsonObject, memories: Sequence[JsonValue]) -> None:
    context: JsonObject
    nested = payload.get("input_context")
    if isinstance(nested, dict):
        context = nested
    else:
        context = payload
    existing = context.get("retrieved_memories")
    existing_memories = existing if isinstance(existing, list) else []
    context["retrieved_memories"] = [*existing_memories, *memories]


def _context(payload: JsonObject) -> JsonObject:
    nested = payload.get("input_context")
    return nested if isinstance(nested, dict) else payload


def _retrieval_context(payload: JsonObject) -> JsonObject:
    context = _context(payload)
    documents = context.get("retrieved_documents")
    memories = context.get("retrieved_memories")
    return {
        "documents": documents if isinstance(documents, list) else [],
        "memories": memories if isinstance(memories, list) else [],
    }


def _missing_data(payload: JsonObject) -> list[str]:
    context = _context(payload)
    missing: list[str] = []
    features = context.get("structured_features")
    if not isinstance(features, dict) or not features:
        missing.append("structured_features")
    elif isinstance(features, dict):
        missing.extend(
            f"structured_features.{key}"
            for key, value in features.items()
            if value is None
        )
    documents = context.get("retrieved_documents")
    if not isinstance(documents, list) or not documents:
        missing.append("retrieved_documents")
    memories = context.get("retrieved_memories")
    if not isinstance(memories, list) or not memories:
        missing.append("retrieved_memories")
    return _unique(missing)


def _allowed_citations(payload: JsonObject) -> set[tuple[str, str]]:
    context = _context(payload)
    allowed: set[tuple[str, str]] = set()
    documents = context.get("retrieved_documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, dict):
                continue
            document_id = document.get("document_id")
            chunk_id = document.get("chunk_id")
            if isinstance(document_id, str):
                excerpt_ref = chunk_id if isinstance(chunk_id, str) else ""
                allowed.add((document_id, excerpt_ref))
    memories = context.get("retrieved_memories")
    if isinstance(memories, list):
        for memory in memories:
            if not isinstance(memory, dict):
                continue
            source = memory.get("source_ref_json")
            if not isinstance(source, dict):
                continue
            document_id = source.get("document_id")
            memory_excerpt_ref = source.get("excerpt_ref")
            if isinstance(document_id, str):
                allowed.add(
                    (
                        document_id,
                        (
                            memory_excerpt_ref
                            if isinstance(memory_excerpt_ref, str)
                            else ""
                        ),
                    )
                )
    return allowed


def _input_output_citations(payload: JsonObject) -> list[SourceReference]:
    found: dict[tuple[str, str], SourceReference] = {}

    def visit(value: JsonValue) -> None:
        if isinstance(value, dict):
            citations = value.get("supporting_citations")
            if isinstance(citations, list):
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    try:
                        parsed = SourceReference.model_validate(citation)
                    except ValidationError:
                        continue
                    found[_citation_key(parsed)] = parsed
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return list(found.values())


def _citations_at_path(output: JsonObject, path: str) -> list[SourceReference]:
    value = _value_at_path(output, path)
    if not isinstance(value, list):
        return []
    return [
        SourceReference.model_validate(item) for item in value if isinstance(item, dict)
    ]


def _citation_key(citation: SourceReference) -> tuple[str, str]:
    return (citation.document_id or "", citation.excerpt_ref or "")


def _value_at_path(value: JsonObject, path: str) -> JsonValue | None:
    current: JsonValue = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _invocation_audit_payload(payload: AgentInvocation) -> JsonObject:
    return cast(JsonObject, payload.model_dump(mode="json"))


def _reject_trading_output(output: JsonObject) -> None:
    forbidden_keys = {
        "order",
        "orders",
        "position",
        "position_size",
        "price_target",
        "target_price",
        "trade",
        "trade_instruction",
    }
    forbidden_phrases = (
        "price target",
        "target price",
        "position size",
        "place an order",
        "execute an order",
        "买入",
        "卖出",
        "目标价",
        "仓位",
        "下单",
    )

    def visit(value: JsonValue) -> None:
        if isinstance(value, dict):
            if forbidden_keys.intersection(key.lower() for key in value):
                raise AgentOutputError("Agent output contained a trading field.")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            normalized = value.casefold()
            contains_direction = re.search(
                r"\b(?:buy|sell)\s+(?:the\s+)?"
                r"(?:shares?|stocks?|securit(?:y|ies)|position)\b",
                normalized,
            )
            if contains_direction is not None or any(
                phrase in normalized for phrase in forbidden_phrases
            ):
                raise AgentOutputError("Agent output contained a trading instruction.")

    visit(output)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _validation_error_summary(error: ValidationError) -> str:
    """Return field paths and error types without rejected values."""

    summaries: list[str] = []
    for item in error.errors(
        include_input=False,
        include_url=False,
    )[:5]:
        location = ".".join(str(part) for part in item["loc"]) or "model"
        summaries.append(f"{location}:{item['type']}")
    detail = ", ".join(summaries) or "unknown_validation_error"
    return f"Agent schema validation failed ({detail})."
