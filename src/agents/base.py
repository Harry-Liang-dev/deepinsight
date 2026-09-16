"""Shared Agent execution, retrieval, validation, and audit behavior."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
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
from src.agents.evidence import numeric_literals
from src.agents.input_contracts import AGENT_OUTPUT_SCHEMA_VERSION
from src.agents.numeric_grounding import validate_numeric_grounding
from src.models.compliance import infer_claim_intent, prohibited_claim_intent
from src.models.enums import AgentName, AgentStatus, ClaimIntent
from src.models.types import DomainModel, JsonObject, JsonValue
from src.repositories.records import AgentRunRecord
from src.schemas.agents import (
    ClaimEvidenceBinding,
    RejectedClaim,
    RoleEvidenceManifest,
    RoleEvidenceManifestEntry,
)
from src.schemas.common import ErrorInfo, SourceReference
from src.schemas.llm import LLMRunMetadata
from src.schemas.memory import MemorySearchRequest, MemorySearchResponse
from src.services.llm_gateway import LLMCacheError, LLMSchemaValidationError
from src.services.llm_provider import (
    LLMInvalidJSONError,
    LLMProviderError,
    LLMTimeoutError,
)


class AgentOutputError(RuntimeError):
    """Raised when an Agent produces unsupported or unattributable output."""


class ClaimMinimumError(AgentOutputError):
    """Raised when quarantine leaves fewer Claims than the role policy allows."""

    def __init__(self, message: str, rejected_claims: list[JsonObject]) -> None:
        super().__init__(message)
        self.rejected_claims = rejected_claims


class AgentGateway(Protocol):
    """Narrow public LLM Gateway boundary used by Agents."""

    def invoke_json(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[DomainModel],
    ) -> JsonObject:
        """Return structured JSON through the configured Gateway."""
        ...


class AgentGatewayRunResult(Protocol):
    """Structured Gateway result used without importing service internals."""

    content: JsonObject
    metadata: LLMRunMetadata


class AgentMetadataGateway(Protocol):
    """Metadata-capable Gateway boundary used by production Agents."""

    def invoke_json_with_metadata(
        self,
        model: str,
        system_prompt: str,
        input_payload: JsonObject,
        *,
        prompt_version: str,
        schema_version: str,
        response_model: type[DomainModel],
    ) -> AgentGatewayRunResult:
        """Return validated content and credential-free run metadata."""

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
    gateway_response_model: type[DomainModel] | None = None
    claim_list_paths: tuple[str, ...] = ()
    scalar_claim_paths: tuple[str, ...] = ()
    response_citation_path: str | None = None
    claim_evidence_path: str | None = None
    uncertainty_path: str | None = None
    inherit_input_citations = False
    claim_collection_path: str | None = None
    minimum_valid_claims = 0
    provenance_mode = "raw_evidence"

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
        llm_run_metadata: LLMRunMetadata | None = None
        structured_output_attempts = 1
        repair_attempted = False
        rejected_claims: list[JsonObject] = []

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
            inference_payload = self._inference_input_payload(
                cast(JsonObject, request.model_dump(mode="json"))
            )
            response_model = self._response_model_for_gateway(enriched)
            try:
                raw_output, llm_run_metadata = _invoke_gateway(
                    self._llm_gateway,
                    model=payload.model_name,
                    system_prompt=prompt.system_prompt,
                    input_payload=inference_payload,
                    prompt_version=prompt.version,
                    response_model=response_model,
                )
                raw_output, quarantined = self._quarantine_inference_output(
                    enriched, raw_output
                )
                rejected_claims.extend(quarantined)
                output, evidence = self._validate_inference_output(enriched, raw_output)
                output = self._attach_rejected_claims(output, rejected_claims)
            except (LLMSchemaValidationError, ValidationError) as initial_error:
                if not _supports_structured_repair(self._llm_gateway):
                    raise
                structured_output_attempts = 2
                repair_attempted = True
                raw_output, llm_run_metadata = _invoke_gateway(
                    self._llm_gateway,
                    model=payload.model_name,
                    system_prompt=_repair_system_prompt(
                        prompt.system_prompt, initial_error
                    ),
                    input_payload=inference_payload,
                    prompt_version=f"{prompt.version}:repair1",
                    response_model=response_model,
                )
                raw_output, quarantined = self._quarantine_inference_output(
                    enriched, raw_output
                )
                rejected_claims.extend(quarantined)
                output, evidence = self._validate_inference_output(enriched, raw_output)
                output = self._attach_rejected_claims(output, rejected_claims)
                if llm_run_metadata is not None:
                    llm_run_metadata = llm_run_metadata.model_copy(
                        update={
                            "structured_output_attempts": 2,
                            "repair_attempted": True,
                        }
                    )
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
                llm_run_metadata=llm_run_metadata,
                rejected_claims=rejected_claims,
            )
            error_message = None
        except LLMSchemaValidationError as exc:
            details: JsonObject = {
                "schema_name": exc.schema_name,
                "schema_version": exc.schema_version,
                "validation_errors": [
                    {"path": path, "error_type": error_type}
                    for path, error_type in exc.validation_errors
                ],
                "contract_diff": exc.contract_diff,
            }
            result = self._error_result(
                payload.run_id,
                code=exc.code,
                message="LLM response failed Agent schema validation.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                rejected_claims=rejected_claims,
                details=details,
            )
            error_message = _gateway_schema_error_summary(exc)
        except LLMInvalidJSONError as exc:
            result = self._error_result(
                payload.run_id,
                code=exc.code,
                message="LLM response was not valid JSON.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                rejected_claims=rejected_claims,
            )
            error_message = "LLM response was not valid JSON."
        except LLMTimeoutError as exc:
            result = self._error_result(
                payload.run_id,
                code=exc.code,
                message="LLM request timed out.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                rejected_claims=rejected_claims,
                retryable=True,
            )
            error_message = "LLM request timed out."
        except LLMCacheError as exc:
            result = self._error_result(
                payload.run_id,
                code=exc.code,
                message="LLM cache failed.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                retryable=True,
                rejected_claims=rejected_claims,
            )
            error_message = "LLM cache failed."
        except LLMProviderError as exc:
            result = self._error_result(
                payload.run_id,
                code=exc.code,
                message="LLM provider request failed.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                retryable=exc.code in {"connection", "rate_limit", "remote_error"},
                rejected_claims=rejected_claims,
            )
            error_message = f"LLM provider request failed ({exc.code})."
        except ValidationError as exc:
            result = self._error_result(
                payload.run_id,
                code="schema_validation",
                message="Agent input or output failed schema validation.",
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                rejected_claims=rejected_claims,
            )
            error_message = _validation_error_summary(exc)
        except AgentOutputError as exc:
            if isinstance(exc, ClaimMinimumError):
                rejected_claims.extend(exc.rejected_claims)
            result = self._error_result(
                payload.run_id,
                code="evidence_validation",
                message=str(exc),
                missing_data=missing_data,
                uncertainties=retrieval_uncertainties,
                rejected_claims=rejected_claims,
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
                rejected_claims=rejected_claims,
            )
            error_message = "Agent execution failed."

        result = result.model_copy(
            update={
                "structured_output_attempts": structured_output_attempts,
                "repair_attempted": repair_attempted,
            }
        )
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
                prompt_tokens=(
                    None if llm_run_metadata is None else llm_run_metadata.input_tokens
                ),
                completion_tokens=(
                    None if llm_run_metadata is None else llm_run_metadata.output_tokens
                ),
                cache_hit=(
                    False if llm_run_metadata is None else llm_run_metadata.cache_hit
                ),
                error_message=error_message,
            )
        )
        return result

    def _validate_inference_output(
        self,
        input_payload: JsonObject,
        raw_output: JsonObject,
    ) -> tuple[JsonObject, list[EvidenceLink]]:
        """Validate one generated response and its exact Evidence bindings."""

        normalized = self._normalize_gateway_output(raw_output)
        response = self.response_model.model_validate(normalized)
        self._validate_role(response)
        output = cast(JsonObject, response.model_dump(mode="json"))
        _reject_trading_output(output)
        evidence = self._build_evidence(input_payload, output)
        return output, evidence

    def _quarantine_inference_output(
        self,
        input_payload: JsonObject,
        raw_output: JsonObject,
    ) -> tuple[JsonObject, list[JsonObject]]:
        """Drop only independently invalid Claim objects before final validation.

        This producer-side quarantine never repairs a Claim or Evidence ID. It
        records the original text, IDs, literals, and rejection reason, then
        lets the unchanged strict validator process the retained output.
        """

        if self.claim_collection_path is None:
            return raw_output, []
        raw_claims = _value_at_path(raw_output, self.claim_collection_path)
        if not isinstance(raw_claims, list):
            return raw_output, []
        manifest = _role_evidence_manifest(input_payload)
        if self.provenance_mode == "raw_evidence" and manifest is None:
            return raw_output, []
        entries = (
            {}
            if manifest is None
            else {entry.evidence_id: entry for entry in manifest.entries}
        )
        upstream = _upstream_claim_index(input_payload)
        retained: list[JsonObject] = []
        rejected: list[JsonObject] = []
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            rejection = (
                _validate_manager_claim_candidate(item, upstream)
                if self.provenance_mode == "upstream_claims"
                else _validate_claim_candidate(item, entries)
            )
            if rejection is None:
                retained.append(item)
            else:
                rejected.append(rejection)
        if len(retained) < self.minimum_valid_claims:
            raise ClaimMinimumError(
                f"{self.agent_name.value} retained {len(retained)} valid claims; "
                f"minimum is {self.minimum_valid_claims}.",
                rejected,
            )
        normalized = _copy_json(raw_output)
        _set_value_at_path(
            normalized,
            self.claim_collection_path,
            cast(JsonValue, retained),
        )
        return normalized, rejected

    def _normalize_gateway_output(self, output: JsonObject) -> JsonObject:
        """Convert a role-specific generation contract to its public response."""

        return output

    def _attach_rejected_claims(
        self,
        output: JsonObject,
        rejected_claims: list[JsonObject],
    ) -> JsonObject:
        """Expose quarantine records without making them factual output."""

        del rejected_claims
        return output

    def _response_model_for_gateway(
        self,
        input_payload: JsonObject,
    ) -> type[DomainModel]:
        """Select the generation schema without changing the public response."""

        del input_payload
        return self.gateway_response_model or self.response_model

    def _inference_input_payload(self, input_payload: JsonObject) -> JsonObject:
        """Build the bounded, role-visible payload supplied to the LLM."""

        return _llm_input_payload(input_payload)

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
        if self.provenance_mode == "upstream_claims":
            return self._build_upstream_claim_evidence(input_payload, output)
        manifest = _role_evidence_manifest(input_payload)
        if manifest is not None:
            return self._build_manifest_evidence(output, manifest)

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
        _validate_numeric_claims(
            input_payload,
            output,
            claim_paths,
            citations,
        )
        return [
            EvidenceLink(
                claim_path=claim_path,
                claim_id=f"{self.agent_name.value}:{claim_path}",
                citations=citations,
            )
            for claim_path in claim_paths
        ]

    def _build_upstream_claim_evidence(
        self,
        input_payload: JsonObject,
        output: JsonObject,
    ) -> list[EvidenceLink]:
        """Resolve Manager provenance recursively through upstream Claims."""

        if self.claim_evidence_path is None:
            raise AgentOutputError("Manager Claim collection is unavailable.")
        raw = _value_at_path(output, self.claim_evidence_path)
        if not isinstance(raw, list):
            raise AgentOutputError("Manager Claims are required.")
        upstream = _upstream_claim_index(input_payload)
        normalized: list[ClaimEvidenceBinding] = []
        links: list[EvidenceLink] = []
        claim_paths = self._text_claim_paths(output)
        if len(raw) != len(claim_paths):
            raise AgentOutputError("Manager Claims do not match textual claims.")
        for item in raw:
            if not isinstance(item, dict):
                raise AgentOutputError("Manager Claim is invalid.")
            binding = ClaimEvidenceBinding.model_validate(item)
            text = _value_at_indexed_path(output, binding.claim_path)
            if not isinstance(text, str) or text != binding.claim_text:
                raise AgentOutputError("Manager Claim text does not match its output.")
            if binding.evidence_ids or not binding.upstream_claim_ids:
                raise AgentOutputError(
                    "Manager Claim requires upstream Claim IDs only."
                )
            parents = [upstream.get(item_id) for item_id in binding.upstream_claim_ids]
            if any(parent is None for parent in parents):
                raise AgentOutputError(
                    "Manager Claim references an unknown upstream Claim."
                )
            parent_claims = [parent for parent in parents if parent is not None]
            literals = numeric_literals(binding.claim_text)
            if any(
                not any(literal in parent.numeric_literals for parent in parent_claims)
                for literal in literals
            ):
                raise AgentOutputError(
                    "Manager Claim introduced a new numeric literal."
                )
            citations = _unique_sources(
                source
                for parent in parent_claims
                for source in parent.source_references
            )
            if not citations:
                raise AgentOutputError(
                    "Manager Claim provenance did not reach Evidence."
                )
            intent = infer_claim_intent(binding.claim_text, analytical=True)
            accepted = binding.model_copy(
                update={
                    "numeric_literals": literals,
                    "source_references": tuple(citations),
                    "claim_intent": intent,
                }
            )
            normalized.append(accepted)
            links.append(
                EvidenceLink(
                    claim_path=accepted.claim_path,
                    claim_id=accepted.claim_id
                    or f"{self.agent_name.value}:{accepted.claim_path}",
                    citations=citations,
                    claim_intent=intent,
                    upstream_claim_ids=accepted.upstream_claim_ids,
                    numeric_literals=literals,
                )
            )
        _set_value_at_path(
            output,
            self.claim_evidence_path,
            [cast(JsonValue, claim.model_dump(mode="json")) for claim in normalized],
        )
        return links

    def _build_manifest_evidence(
        self,
        output: JsonObject,
        manifest: RoleEvidenceManifest,
    ) -> list[EvidenceLink]:
        """Validate exact per-claim bindings against one role-local manifest."""

        if manifest.agent_name is not self.agent_name:
            raise AgentOutputError("Role Evidence manifest does not match the Agent.")
        manifest_entries = {entry.evidence_id: entry for entry in manifest.entries}
        manifest_citation_keys = {
            _citation_key(entry.source) for entry in manifest.entries
        }
        if self.response_citation_path is not None:
            supplied_citations = _citations_at_path(output, self.response_citation_path)
            if any(
                _citation_key(citation) not in manifest_citation_keys
                for citation in supplied_citations
            ):
                raise AgentOutputError(
                    "Agent output cited evidence absent from its input."
                )
        if self.claim_evidence_path is None:
            raise AgentOutputError("Agent claim Evidence contract is unavailable.")
        raw_bindings = _value_at_path(output, self.claim_evidence_path)
        if not isinstance(raw_bindings, list):
            raise AgentOutputError("Agent claim Evidence bindings are required.")
        try:
            bindings = [
                ClaimEvidenceBinding.model_validate(item)
                for item in raw_bindings
                if isinstance(item, dict)
            ]
        except ValidationError:
            raise AgentOutputError(
                "Agent claim Evidence bindings are invalid."
            ) from None
        if len(bindings) != len(raw_bindings):
            raise AgentOutputError("Agent claim Evidence bindings are invalid.")

        claim_paths = self._text_claim_paths(output)
        uncertainty_paths = self._uncertainty_claim_paths(output)
        binding_paths = [binding.claim_path for binding in bindings]
        binding_path_set = set(binding_paths)
        allowed_paths = set(claim_paths) | set(uncertainty_paths)
        if (
            len(binding_paths) != len(binding_path_set)
            or not set(claim_paths) <= binding_path_set
            or not binding_path_set <= allowed_paths
        ):
            raise AgentOutputError(
                "Agent claim Evidence bindings do not match its textual claims."
            )
        if any(
            evidence_id not in manifest_entries
            for binding in bindings
            for evidence_id in binding.evidence_ids
        ):
            raise AgentOutputError("Agent output cited evidence absent from its input.")

        links: list[EvidenceLink] = []
        normalized_bindings: list[ClaimEvidenceBinding] = []
        union: dict[tuple[str, str], SourceReference] = {}
        by_path = {binding.claim_path: binding for binding in bindings}
        for claim_path in claim_paths:
            claim = _value_at_indexed_path(output, claim_path)
            binding = by_path[claim_path]
            if not isinstance(claim, str) or binding.claim_text != claim:
                raise AgentOutputError(
                    "Agent claim Evidence binding text does not match its claim."
                )
            expected_literals = numeric_literals(claim)
            intent = infer_claim_intent(
                claim,
                analytical=_claim_path_is_analytical(claim_path),
            )
            normalized_bindings.append(
                binding.model_copy(
                    update={
                        "claim_id": binding.claim_id
                        or f"{self.agent_name.value}:{claim_path}",
                        "numeric_literals": expected_literals,
                        "claim_intent": intent,
                        "source_references": tuple(
                            manifest_entries[item].source
                            for item in binding.evidence_ids
                        ),
                    }
                )
            )
            bound_entries = [manifest_entries[item] for item in binding.evidence_ids]
            unsupported = [
                literal
                for literal in expected_literals
                if not any(literal in entry.numeric_tokens for entry in bound_entries)
            ]
            if unsupported:
                raise AgentOutputError(
                    f"Agent numeric claim was absent from evidence ({claim_path})."
                )
            citations = [entry.source for entry in bound_entries]
            for citation in citations:
                union[_citation_key(citation)] = citation
            links.append(
                EvidenceLink(
                    claim_path=claim_path,
                    claim_id=binding.claim_id
                    or f"{self.agent_name.value}:{claim_path}",
                    citations=citations,
                    claim_intent=intent,
                    evidence_ids=binding.evidence_ids,
                    numeric_literals=expected_literals,
                )
            )

        if claim_paths and not union:
            raise AgentOutputError("Agent conclusions require attributable citations.")
        _set_value_at_path(
            output,
            self.claim_evidence_path,
            [
                cast(JsonValue, binding.model_dump(mode="json"))
                for binding in normalized_bindings
            ],
        )
        if self.response_citation_path is not None:
            _set_value_at_path(
                output,
                self.response_citation_path,
                [
                    cast(JsonValue, citation.model_dump(mode="json"))
                    for citation in union.values()
                ],
            )
        scalar_citations = list(union.values())
        links.extend(
            EvidenceLink(
                claim_path=claim_path,
                claim_id=f"{self.agent_name.value}:{claim_path}",
                citations=scalar_citations,
                claim_intent=ClaimIntent.ANALYTICAL_INFERENCE,
            )
            for claim_path in self.scalar_claim_paths
            if scalar_citations
        )
        return links

    def _claim_paths(self, output: JsonObject) -> list[str]:
        paths = list(self.scalar_claim_paths)
        paths.extend(self._text_claim_paths(output))
        return paths

    def _text_claim_paths(self, output: JsonObject) -> list[str]:
        paths: list[str] = []
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

    def _uncertainty_claim_paths(self, output: JsonObject) -> list[str]:
        if self.uncertainty_path is None:
            return []
        value = _value_at_path(output, self.uncertainty_path)
        if not isinstance(value, list):
            return []
        return [f"{self.uncertainty_path}[{index}]" for index in range(len(value))]

    def _error_result(
        self,
        run_id: str,
        *,
        code: str,
        message: str,
        missing_data: list[str],
        uncertainties: list[str],
        retryable: bool = False,
        details: JsonObject | None = None,
        rejected_claims: list[JsonObject] | None = None,
    ) -> AgentExecutionResult:
        return AgentExecutionResult(
            run_id=run_id,
            agent_name=self.agent_name,
            status=AgentStatus.ERROR,
            missing_data=missing_data,
            uncertainties=uncertainties,
            rejected_claims=[] if rejected_claims is None else rejected_claims,
            error=ErrorInfo(
                code=code,
                message=message,
                retryable=retryable,
                details=details,
            ),
        )


def _invoke_gateway(
    gateway: AgentGateway,
    *,
    model: str,
    system_prompt: str,
    input_payload: JsonObject,
    prompt_version: str,
    response_model: type[DomainModel],
) -> tuple[JsonObject, LLMRunMetadata | None]:
    metadata_call = getattr(gateway, "invoke_json_with_metadata", None)
    if callable(metadata_call):
        result = cast(AgentMetadataGateway, gateway).invoke_json_with_metadata(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version=AGENT_OUTPUT_SCHEMA_VERSION,
            response_model=response_model,
        )
        return result.content, result.metadata
    return (
        gateway.invoke_json(
            model,
            system_prompt,
            input_payload,
            prompt_version=prompt_version,
            schema_version=AGENT_OUTPUT_SCHEMA_VERSION,
            response_model=response_model,
        ),
        None,
    )


def _supports_structured_repair(gateway: AgentGateway) -> bool:
    """Return explicit Gateway repair capability without assuming Provider type."""

    return getattr(gateway, "supports_structured_repair", False) is True


def _repair_system_prompt(
    original_prompt: str,
    error: LLMSchemaValidationError | ValidationError,
) -> str:
    """Append one bounded contract correction without adding Evidence or facts."""

    if isinstance(error, LLMSchemaValidationError):
        detail = ", ".join(
            f"{path}:{error_type}" for path, error_type in error.validation_errors[:10]
        )
    elif isinstance(error, ValidationError):
        detail = _validation_error_summary(error)
    return (
        f"{original_prompt}\n\n"
        "STRUCTURED OUTPUT REPAIR (attempt 1 of 1): The previous JSON was "
        f"rejected for this contract violation: {detail} "
        "Use exactly the same supplied facts. Return the complete JSON response "
        "again, correcting only JSON structure or schema format. Do not add "
        "facts, identifiers, calculations, aliases, or external information."
    )


def _copy_json(value: JsonObject) -> JsonObject:
    return cast(JsonObject, _copy_json_value(value))


def _copy_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _copy_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _llm_input_payload(payload: JsonObject) -> JsonObject:
    """Project one complete audit contract into a bounded inference payload.

    The original invocation remains unchanged for local validation and durable
    audit.  The model receives each directly citable structured Evidence item
    once, without duplicated section items or transformation-parent lineage.
    """

    projected = _copy_json(payload)
    contract = projected.get("research_contract")
    if not isinstance(contract, dict):
        return projected
    if _contract_contains_upstream_claims(contract):
        return _manager_inference_payload(projected, contract)
    manifest = _role_evidence_manifest(projected)
    allowed_ids = (
        None if manifest is None else {entry.evidence_id for entry in manifest.entries}
    )
    _compact_contract(contract, allowed_ids)
    return projected


def _contract_contains_upstream_claims(contract: JsonObject) -> bool:
    context = contract.get("context")
    if isinstance(context, dict) and isinstance(context.get("analyst_outputs"), list):
        return True
    return any(
        isinstance(contract.get(key), dict)
        for key in ("research_output", "bull_output", "bear_output")
    )


def _manager_inference_payload(
    projected: JsonObject,
    contract: JsonObject,
) -> JsonObject:
    """Expose Managers only accepted upstream Claims and bounded context."""

    claims: list[JsonValue] = []
    seen_claim_ids: set[str] = set()

    def collect(value: JsonValue) -> None:
        if isinstance(value, dict):
            raw = value.get("validated_claims")
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    claim_id = item.get("claim_id")
                    if not isinstance(claim_id, str) or claim_id in seen_claim_ids:
                        continue
                    seen_claim_ids.add(claim_id)
                    claims.append(item)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(contract)
    context = contract.get("context")
    context = context if isinstance(context, dict) else {}
    coverage = context.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    memory = context.get("memory")
    memory = memory if isinstance(memory, dict) else {}
    sector_context = context.get("sector_context")
    compact_sector_context: JsonValue = None
    if isinstance(sector_context, dict):
        compact_sector_context = _copy_json(sector_context)
        compact_sector_context.pop("validated_claims", None)
        compact_sector_context.pop("context_claims", None)
    projected["research_contract"] = {
        "schema_version": contract.get("schema_version"),
        "agent_name": contract.get("agent_name"),
        "research_context": {
            "scope": context.get("scope"),
            "missing_data": coverage.get("missing_data", []),
            "missing_context": coverage.get("missing_context", []),
            "memory_context": memory.get("items", []),
            "sector_context": compact_sector_context,
        },
        "validated_upstream_claims": claims,
    }
    for key in (
        "analyst_outputs",
        "research_summary",
        "bull_output",
        "bear_output",
    ):
        projected.pop(key, None)
    input_context = projected.get("input_context")
    if isinstance(input_context, dict):
        input_context["structured_evidence"] = []
        input_context["retrieved_documents"] = []
        input_context["role_evidence_manifest"] = None
    return projected


def _compact_contract(
    contract: JsonObject,
    allowed_evidence_ids: set[str] | None = None,
) -> None:
    context = contract.get("context")
    owner = context if isinstance(context, dict) else contract
    data = owner.get("data")
    if isinstance(data, dict):
        sections = data.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict):
                    section.pop("items", None)
    evidence_index = owner.get("data_evidence_index")
    if isinstance(evidence_index, dict):
        owner["data_evidence_index"] = {
            evidence_id: _compact_evidence(evidence_id, item)
            for evidence_id, item in evidence_index.items()
            if isinstance(evidence_id, str)
            and isinstance(item, dict)
            and (allowed_evidence_ids is None or evidence_id in allowed_evidence_ids)
        }


def _compact_evidence(evidence_id: str, item: JsonObject) -> JsonObject:
    source = item.get("source")
    compact_source: JsonObject = {}
    if isinstance(source, dict):
        for key in (
            "provider_name",
            "normalized_record_key",
            "provider_locator",
            "source_url",
        ):
            value = source.get(key)
            if value is not None:
                compact_source[key] = cast(JsonValue, value)
    compact: JsonObject = {"evidence_id": evidence_id, "source": compact_source}
    for key in (
        "field_path",
        "effective_at",
        "value",
        "unit",
        "currency",
    ):
        value = item.get(key)
        if value is not None:
            compact[key] = cast(JsonValue, value)
    return compact


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
        "structured_evidence": (
            context.get("structured_evidence")
            if isinstance(context.get("structured_evidence"), list)
            else []
        ),
    }


def _missing_data(payload: JsonObject) -> list[str]:
    context = _context(payload)
    missing: list[str] = []
    contract = payload.get("research_contract")
    # The versioned role contract owns section-specific data coverage. Legacy
    # global structured_features are consulted only by callers without it.
    if not isinstance(contract, dict):
        features = context.get("structured_features")
        if not isinstance(features, dict) or not features:
            missing.append("structured_features")
        else:
            missing.extend(
                f"structured_features.{key}"
                for key, value in features.items()
                if value is None
            )
    if not isinstance(contract, dict):
        documents = context.get("retrieved_documents")
        if not isinstance(documents, list) or not documents:
            missing.append("retrieved_documents")
        memories = context.get("retrieved_memories")
        if not isinstance(memories, list) or not memories:
            missing.append("retrieved_memories")
    if isinstance(contract, dict):
        contract_context = contract.get("context")
        coverage_owner = (
            contract_context if isinstance(contract_context, dict) else contract
        )
        coverage = coverage_owner.get("coverage")
        if isinstance(coverage, dict):
            data_gaps = coverage.get("missing_data")
            if isinstance(data_gaps, list):
                missing.extend(
                    str(item["field_path"])
                    for item in data_gaps
                    if isinstance(item, dict)
                    and isinstance(item.get("field_path"), str)
                )
            memory_gaps = coverage.get("missing_context")
            if isinstance(memory_gaps, list):
                missing.extend(
                    f"memory.{item['section']}"
                    for item in memory_gaps
                    if isinstance(item, dict) and isinstance(item.get("section"), str)
                )
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
    structured = context.get("structured_evidence")
    if isinstance(structured, list):
        for item in structured:
            if not isinstance(item, dict):
                continue
            try:
                reference = SourceReference.model_validate(item)
            except ValidationError:
                continue
            allowed.add(_citation_key(reference))
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


def _role_evidence_manifest(payload: JsonObject) -> RoleEvidenceManifest | None:
    value = _context(payload).get("role_evidence_manifest")
    if value is None:
        return None
    try:
        return RoleEvidenceManifest.model_validate(value)
    except ValidationError:
        raise AgentOutputError("Role Evidence manifest is invalid.") from None


def _validate_numeric_claims(
    input_payload: JsonObject,
    output: JsonObject,
    claim_paths: list[str],
    citations: list[SourceReference],
) -> None:
    """Reject claim numbers that cannot be found verbatim in cited evidence."""

    evidence = _citation_text(input_payload, citations)
    for claim_path in claim_paths:
        claim = _value_at_indexed_path(output, claim_path)
        if not isinstance(claim, str):
            continue
        unsupported = [
            token
            for token in _numeric_tokens(claim)
            if not any(token in _numeric_tokens(text) for text in evidence)
        ]
        if unsupported:
            raise AgentOutputError(
                f"Agent numeric claim was absent from evidence ({claim_path})."
            )


def _citation_text(
    payload: JsonObject,
    citations: list[SourceReference],
) -> list[str]:
    requested = {_citation_key(citation) for citation in citations}
    context = _context(payload)
    texts: list[str] = []
    documents = context.get("retrieved_documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, dict):
                continue
            key = (
                str(document.get("document_id") or ""),
                str(document.get("chunk_id") or ""),
            )
            text = document.get("chunk_text")
            if key in requested and isinstance(text, str):
                texts.append(text)
    memories = context.get("retrieved_memories")
    if isinstance(memories, list):
        for memory in memories:
            if not isinstance(memory, dict):
                continue
            source = memory.get("source_ref_json")
            if not isinstance(source, dict):
                continue
            key = (
                str(source.get("document_id") or ""),
                str(source.get("excerpt_ref") or ""),
            )
            summary = memory.get("summary_text")
            if key in requested and isinstance(summary, str):
                texts.append(summary)
    contract = payload.get("research_contract")
    if isinstance(contract, dict):
        contract_context = contract.get("context")
        evidence_owner = (
            contract_context if isinstance(contract_context, dict) else contract
        )
        evidence_index = evidence_owner.get("data_evidence_index")
        if isinstance(evidence_index, dict):
            for evidence_id, item in evidence_index.items():
                if not isinstance(evidence_id, str) or not isinstance(item, dict):
                    continue
                source = item.get("source")
                if not isinstance(source, dict):
                    continue
                key = (
                    str(source.get("normalized_record_key") or ""),
                    evidence_id,
                )
                if key not in requested:
                    continue
                value = item.get("value")
                unit = item.get("unit")
                currency = item.get("currency")
                field_path = item.get("field_path")
                texts.append(
                    " ".join(
                        str(part)
                        for part in (field_path, value, unit, currency)
                        if part is not None
                    )
                )
    return texts


def _numeric_tokens(value: str) -> set[str]:
    return set(numeric_literals(value))


def _value_at_indexed_path(value: JsonObject, path: str) -> JsonValue | None:
    current: JsonValue = value
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)])?", part)
        if match is None or not isinstance(current, dict):
            return None
        current = current.get(match.group(1))
        index = match.group(2)
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                return None
            current = current[int(index)]
    return current


def _value_at_path(value: JsonObject, path: str) -> JsonValue | None:
    current: JsonValue = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_value_at_path(value: JsonObject, path: str, replacement: JsonValue) -> None:
    current = value
    parts = path.split(".")
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            raise AgentOutputError("Agent citation output path is unavailable.")
        current = nested
    current[parts[-1]] = replacement


def _invocation_audit_payload(payload: AgentInvocation) -> JsonObject:
    return cast(JsonObject, payload.model_dump(mode="json"))


def _reject_trading_output(output: JsonObject) -> None:
    bindings = _claim_binding_objects(output)
    for claim in bindings:
        text = claim.get("claim_text")
        declared = claim.get("claim_intent")
        if declared in {
            ClaimIntent.SYSTEM_RECOMMENDATION.value,
            ClaimIntent.EXECUTION_INSTRUCTION.value,
        } or (isinstance(text, str) and prohibited_claim_intent(text) is not None):
            raise AgentOutputError("Agent output contained a trading instruction.")
    if bindings:
        return
    for text in _legacy_claim_texts(output):
        if prohibited_claim_intent(text) is not None:
            raise AgentOutputError("Agent output contained a trading instruction.")


def _validate_claim_candidate(
    item: JsonObject,
    entries: Mapping[str, object],
) -> JsonObject | None:
    """Return a rejection record or None for one exact Claim candidate."""

    claim_path = item.get("claim_path")
    claim_text = item.get("claim_text")
    path = claim_path if isinstance(claim_path, str) and claim_path else "<unknown>"
    text = (
        claim_text if isinstance(claim_text, str) and claim_text else "<invalid claim>"
    )
    ids_value = item.get("evidence_ids")
    evidence_ids = (
        tuple(item_id for item_id in ids_value if isinstance(item_id, str))
        if isinstance(ids_value, list)
        else ()
    )
    literals = tuple(numeric_literals(text))

    def rejected(reason: str) -> JsonObject:
        return cast(
            JsonObject,
            RejectedClaim(
                claim_path=path,
                claim_text=text,
                reason=reason,
                evidence_ids=evidence_ids,
                numeric_literals=literals,
            ).model_dump(mode="json"),
        )

    try:
        binding = ClaimEvidenceBinding.model_validate(item)
    except ValidationError:
        return rejected("claim_schema_invalid")
    for evidence_id in binding.evidence_ids:
        if evidence_id not in entries:
            return rejected("unknown_or_cross_role_evidence_id")
    bound_entries = [
        cast(RoleEvidenceManifestEntry, entries[evidence_id])
        for evidence_id in binding.evidence_ids
    ]
    grounding = validate_numeric_grounding(text, bound_entries)
    literals = grounding.numeric_literals
    if grounding.ungrounded_literals:
        return rejected(
            f"numeric_literal_not_grounded:{grounding.ungrounded_literals[0]}"
        )
    if prohibited_claim_intent(binding.claim_text) is not None:
        return rejected("prohibited_claim_intent")
    if binding.claim_intent in {
        ClaimIntent.SYSTEM_RECOMMENDATION,
        ClaimIntent.EXECUTION_INSTRUCTION,
    }:
        return rejected("prohibited_claim_intent")
    return None


def _validate_manager_claim_candidate(
    item: JsonObject,
    upstream: Mapping[str, ClaimEvidenceBinding],
) -> JsonObject | None:
    """Quarantine a Manager Claim that cannot derive from accepted parents."""

    path_value = item.get("claim_path")
    text_value = item.get("claim_text")
    path = path_value if isinstance(path_value, str) and path_value else "<unknown>"
    text = (
        text_value if isinstance(text_value, str) and text_value else "<invalid claim>"
    )
    ids_value = item.get("upstream_claim_ids")
    upstream_ids = (
        tuple(item_id for item_id in ids_value if isinstance(item_id, str))
        if isinstance(ids_value, list)
        else ()
    )
    literals = tuple(numeric_literals(text))

    def rejected(reason: str) -> JsonObject:
        return cast(
            JsonObject,
            RejectedClaim(
                claim_path=path,
                claim_text=text,
                reason=reason,
                upstream_claim_ids=upstream_ids,
                numeric_literals=literals,
            ).model_dump(mode="json"),
        )

    try:
        binding = ClaimEvidenceBinding.model_validate(item)
    except ValidationError:
        return rejected("claim_schema_invalid")
    if binding.evidence_ids or not binding.upstream_claim_ids:
        return rejected("manager_requires_upstream_claim_ids")
    parents = [upstream.get(item_id) for item_id in binding.upstream_claim_ids]
    if any(parent is None for parent in parents):
        return rejected("invalid_upstream_claim")
    parent_claims = [parent for parent in parents if parent is not None]
    for literal in literals:
        if not any(literal in parent.numeric_literals for parent in parent_claims):
            return rejected(f"unsupported_new_numeric:{literal}")
    if prohibited_claim_intent(
        binding.claim_text
    ) is not None or binding.claim_intent in {
        ClaimIntent.SYSTEM_RECOMMENDATION,
        ClaimIntent.EXECUTION_INSTRUCTION,
    }:
        return rejected("prohibited_claim_intent")
    return None


def _upstream_claim_index(payload: JsonObject) -> dict[str, ClaimEvidenceBinding]:
    """Return accepted upstream Claims from the versioned research contract."""

    found: dict[str, ClaimEvidenceBinding] = {}

    def visit(value: JsonValue) -> None:
        if isinstance(value, dict):
            for key in ("validated_claims", "claim_evidence"):
                raw_claims = value.get(key)
                if not isinstance(raw_claims, list):
                    continue
                for item in raw_claims:
                    if not isinstance(item, dict):
                        continue
                    try:
                        claim = ClaimEvidenceBinding.model_validate(item)
                    except ValidationError:
                        continue
                    if claim.claim_id:
                        found[claim.claim_id] = claim
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def _unique_sources(values: Iterable[SourceReference]) -> list[SourceReference]:
    unique: dict[tuple[str, str], SourceReference] = {}
    for value in values:
        unique.setdefault(_citation_key(value), value)
    return list(unique.values())


def _claim_binding_objects(output: JsonObject) -> list[JsonObject]:
    """Return accepted Claim bindings without scanning presentation metadata."""

    bindings: list[JsonObject] = []
    for path in (
        "claims",
        "analysis.claims",
        "claim_evidence",
        "analysis.claim_evidence",
    ):
        raw = _value_at_path(output, path)
        if isinstance(raw, list):
            bindings.extend(item for item in raw if isinstance(item, dict))
    return bindings


def _legacy_claim_texts(output: JsonObject) -> list[str]:
    """Read only historical business-claim fields when bindings are absent."""

    paths = (
        "analysis.facts",
        "analysis.key_points",
        "analysis.risk_points",
        "analysis.summary_points",
        "analysis.conflicts",
        "bull_thesis",
        "bear_thesis",
        "conditions_required",
        "invalidators",
        "confirmed_risks",
        "scenario_risks",
        "watch_items",
    )
    return [
        item
        for path in paths
        for value in [_value_at_path(output, path)]
        if isinstance(value, list)
        for item in value
        if isinstance(item, str)
    ]


def _claim_path_is_analytical(claim_path: str) -> bool:
    """Map presentation categories to intent without changing claim type."""

    return any(
        marker in claim_path
        for marker in (
            "key_points",
            "summary_points",
            "conflicts",
            "thesis",
            "conditions_required",
            "invalidators",
            "scenario_risks",
            "watch_items",
        )
    )


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


def _gateway_schema_error_summary(error: LLMSchemaValidationError) -> str:
    """Return Gateway schema identity and field paths without rejected values."""

    detail = ", ".join(
        f"{path}:{error_type}" for path, error_type in error.validation_errors[:5]
    )
    return (
        f"LLM schema validation failed "
        f"({error.schema_name}/{error.schema_version}: {detail or 'unknown'})."
    )
