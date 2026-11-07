"""G101 opt-in presentation over existing contracts, never an admission authority.

This module neither dispatches Agents nor writes Memory/State. The original
G86 mandate and G100 controlled delivery must already exist. No format-specific
Prompt, semantic rule or financial validator is introduced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from src.memory.hybrid import HybridRead, SourceAdmission
from src.memory.hybrid_sources import NativeLocatorResolver
from src.memory.vnext import MemoryAccessContext
from src.memory.vnext_contracts import ResearchMandate
from src.repositories.memory_journal import MemoryJournalRepository
from src.schemas.research_v2_shared import canonical, digest
from src.services.research_vnext.contracts import RetainedReader
from src.services.research_vnext.radar import require_mandate

Objective = Literal[
    "SOURCE_ORGANIZATION", "INVESTIGATION_PLANNING", "ECONOMIC_MECHANISM"
]


def exploratory_task_view(
    *,
    objective: Objective,
    questions: tuple[str, ...],
    mandate: ResearchMandate,
    reader: RetainedReader,
    delivery: HybridRead,
    resolver: NativeLocatorResolver,
    journal: MemoryJournalRepository,
    access: MemoryAccessContext,
    at: datetime,
    enabled: bool = False,
) -> dict[str, Any]:
    """Project a controlled delivery into an unverified, advisory research task.

    The view does not select roles or override the original ImpactPlan,
    Coordinator or full-state dependencies.
    Text pooling preserves every source/Memory identity, locator and authority.
    """
    if not enabled:
        raise ValueError("G101_DEVELOPMENT_OPT_IN_REQUIRED")
    # G102: the existing access context supplies its already assigned role.
    # Objectives describe the task only; they never choose or replace a role.
    if (
        objective
        not in ("SOURCE_ORGANIZATION", "INVESTIGATION_PLANNING", "ECONOMIC_MECHANISM")
        or not questions
        or any(not q.strip() for q in questions)
    ):
        raise ValueError("G101_OBJECTIVE_OR_QUESTION")
    require_mandate(
        mandate, role=access.role, scope=mandate.scope, at=at, reader=reader
    )
    access.require("READ_HISTORY", delivery.read_set.scope)
    cutoff = delivery.bundle.retrieval_metadata.as_of
    if (
        delivery.sha256,
        delivery.model_dump_json(),
    ) not in journal.entries("g100-deliveries") or (
        access.owner != delivery.read_set.owner
        or access.role != delivery.read_set.agent_role
        or cutoff > at
        or delivery.read_set.created_at > at
    ):
        raise ValueError("G101_CONTROLLED_DELIVERY_REQUIRED")
    texts: dict[str, str] = {}
    records = []
    pool_keys: dict[str, str] = {}
    for receipt in delivery.supplied_records:
        record = resolver.validate(receipt.record.proposal)
        if record != receipt.record:
            raise ValueError("G101_RECORD_CHANGED")
        if (
            mandate.scope.scope_id != "ASSET:" + record.proposal.subject
            or receipt.persisted_at > cutoff
            or record.source_available_at > cutoff
            or at >= record.review_due_at
        ):
            raise ValueError("G101_SCOPE_OR_TIME")
        for _, body in journal.entries("g100-source-catalog"):
            newer = SourceAdmission.model_validate_json(body)
            if (
                newer.persisted_at <= at
                and newer.record.proposal.supersedes_memory_id
                == receipt.result.memory_id
            ):
                raise ValueError("G101_SUPERSEDED_DELIVERY")
        # Identical strings are pooled only inside the SAME evidence/authority
        # identity. Equal amounts from different contracts never get merged.
        identity = {
            "source": record.proposal.source_ref.model_dump(mode="json"),
            "sha256": record.proposal.source_sha256,
            "locator": record.proposal.evidence_locator.model_dump(mode="json"),
            "authority": record.fact_authority,
            "review": record.review_status,
            "publisher": record.publisher,
            "period": record.proposal.relevant_period,
        }
        view = record.model_dump(mode="json")
        for target, field in (
            (view["proposal"], "statement"),
            (view["proposal"]["evidence_locator"], "quote"),
        ):
            value = target.pop(field)
            identity_key = digest({"identity": identity, "text": value})
            key = pool_keys.setdefault(identity_key, "text:" + str(len(pool_keys)))
            texts[key] = value
            target[field + "_text_ref"] = key
        records.append(
            {
                "memory_id": receipt.result.memory_id,
                "admission_sha256": receipt.sha256,
                "record_sha256": record.sha256,
                "persisted_at": receipt.persisted_at.isoformat(),
                "source_record_view": view,
            }
        )
    unpooled = [
        {**view, "source_record_view": receipt.record.model_dump(mode="json")}
        for view, receipt in zip(records, delivery.supplied_records, strict=True)
    ]
    return {
        "schema_version": "g102_exploratory_task_view_v1",
        "mode": "ISOLATED_DEVELOPMENT_ONLY_NOT_G102_REVIEWED",
        "research_objective": objective,
        "scope": mandate.scope.model_dump(mode="json"),
        "as_of": cutoff.isoformat(),
        "constructed_at": at.isoformat(),
        "opportunity": mandate.opportunity.model_dump(mode="json"),
        "mandate_sha256": mandate.sha256,
        "source_bundle": {"texts": texts, "records": records},
        "known_facts": "NO_WORLD_FACT_AUTHORITY; source-attributed records only",
        "memory_context": {
            "delivery_sha256": delivery.sha256,
            "read_set": delivery.read_set.model_dump(mode="json"),
        },
        "open_questions": questions,
        "allowed_actions": [
            "ORGANIZE_ATTRIBUTED_SOURCES",
            "PROPOSE_UNVERIFIED_RESEARCH",
        ],
        "evidence_authority": "ORIGINAL_RECEIPTS_ONLY_NO_NEW_CLAIMS",
        "role_selection_refactor": "DEFERRED_BY_USER",
        "agent_dispatch_policy": "UNCHANGED",
        "dispatch_authorized": False,
        "formal_impact_plan_override": False,
        "scientific_acceptance": False,
        "measurement": {
            "unpooled_record_bytes": len(canonical({"texts": {}, "records": unpooled})),
            "pooled_record_bytes": len(canonical({"texts": texts, "records": records})),
            "unpooled_quote_occurrences": 2 * len(records),
            "pooled_text_entries": len(texts),
            "real_tokens": "NOT_MEASURED",
        },
    }
