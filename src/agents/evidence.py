"""Role-local Evidence manifests for Agent inference and claim validation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from src.agents.input_contracts import (
    AgentInputBaseV1,
    BearManagerInputV1,
    BullManagerInputV1,
    ManagerResearchContextV1,
    ResearchManagerInputV1,
    RiskManagerInputV1,
    VersionedUpstreamOutputV1,
)
from src.models.enums import AgentStatus
from src.schemas.agents import (
    AgentContext,
    RoleEvidenceManifest,
    RoleEvidenceManifestEntry,
    RoleEvidenceType,
)
from src.schemas.common import SourceReference

type ManifestContract = (
    AgentInputBaseV1
    | ResearchManagerInputV1
    | BullManagerInputV1
    | BearManagerInputV1
    | RiskManagerInputV1
)


def numeric_literals(value: str) -> tuple[str, ...]:
    """Return unique numeric literals in source order without deriving values."""

    return tuple(
        dict.fromkeys(
            token.replace(",", "")
            for token in re.findall(
                r"(?<![\w.])(?:"
                r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
                r"|[-+]?\d[\d,]*(?:\.\d+)?%?)",
                value,
            )
        )
    )


def build_role_evidence_manifest(
    context: AgentContext,
    contract: ManifestContract,
) -> RoleEvidenceManifest:
    """Build the canonical raw-Evidence namespace for Analyst roles only."""

    role_context = _role_context(contract)
    if not isinstance(contract, AgentInputBaseV1) or isinstance(
        contract, ManagerResearchContextV1
    ):
        return RoleEvidenceManifest(agent_name=role_context.agent_name, entries=())
    upstream_ids = _successful_upstream_evidence_ids(contract)
    restrict_data = False
    entries: dict[str, RoleEvidenceManifestEntry] = {}

    for evidence_id, item in role_context.data_evidence_index.items():
        if restrict_data and evidence_id not in upstream_ids:
            continue
        source = item.to_source_reference()
        description = " ".join(
            str(part)
            for part in (item.field_path, item.value, item.unit, item.currency)
            if part is not None
        )
        evidence_type: RoleEvidenceType = (
            "structured_derived"
            if item.source.authorization_class == "derived_from_normalized_data"
            or item.source.provider_locator.startswith("derived:")
            else "structured_direct"
        )
        entries[evidence_id] = RoleEvidenceManifestEntry(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            source=source,
            as_of=item.effective_at,
            short_description=description,
            numeric_tokens=_evidence_numeric_tokens(description, item.effective_at),
        )

    for document in context.retrieved_documents:
        evidence_id = document.chunk_id or document.document_id
        if restrict_data and evidence_id not in upstream_ids:
            continue
        entries[evidence_id] = RoleEvidenceManifestEntry(
            evidence_id=evidence_id,
            evidence_type="document",
            source=SourceReference(
                document_id=document.document_id,
                excerpt_ref=document.chunk_id,
            ),
            short_description=f"{document.title}: {document.chunk_text}",
            numeric_tokens=numeric_literals(document.chunk_text),
        )

    for memory in context.retrieved_memories:
        entries[memory.memory_id] = RoleEvidenceManifestEntry(
            evidence_id=memory.memory_id,
            evidence_type="memory",
            source=memory.source_ref_json,
            as_of=memory.effective_ts,
            short_description=memory.summary_text,
            numeric_tokens=_evidence_numeric_tokens(
                memory.summary_text, memory.effective_ts
            ),
        )

    return RoleEvidenceManifest(
        agent_name=role_context.agent_name,
        entries=tuple(entries[key] for key in sorted(entries)),
    )


def _role_context(contract: ManifestContract) -> AgentInputBaseV1:
    if isinstance(contract, AgentInputBaseV1):
        return contract
    return contract.context


def _evidence_numeric_tokens(
    description: str, effective_at: datetime
) -> tuple[str, ...]:
    """Expose exact values plus canonical full/date-only Evidence timestamps."""

    utc_iso = effective_at.isoformat().replace("+00:00", "Z")
    return tuple(
        dict.fromkeys(
            (
                *numeric_literals(description),
                effective_at.date().isoformat(),
                effective_at.isoformat(),
                utc_iso,
            )
        )
    )


def _successful_upstream_evidence_ids(contract: ManifestContract) -> set[str]:
    if isinstance(contract, AgentInputBaseV1) and not isinstance(
        contract, ManagerResearchContextV1
    ):
        return set()
    outputs: Iterable[VersionedUpstreamOutputV1]
    if isinstance(contract, ResearchManagerInputV1):
        outputs = contract.context.analyst_outputs
    elif isinstance(contract, (BullManagerInputV1, BearManagerInputV1)):
        outputs = (*contract.context.analyst_outputs, contract.research_output)
    elif isinstance(contract, RiskManagerInputV1):
        outputs = (
            *contract.context.analyst_outputs,
            contract.research_output,
            contract.bull_output,
            contract.bear_output,
        )
    else:
        outputs = contract.analyst_outputs
    return {
        evidence_id
        for output in outputs
        if output.status is AgentStatus.OK
        for evidence_id in output.evidence_ids
    }
