"""G100 opt-in envelopes; G84 levels, scopes and scientific contracts stay frozen."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.memory.vnext_contracts import Frozen, Scope
from src.schemas.common import SourceReference
from src.schemas.research_v2_shared import Clock


class EvidenceLocator(Frozen):
    """Coordinate spaces are explicit; unsupported extraction is never invented."""

    kind: Literal["NORMALIZED_UNICODE", "RAW_UTF8_BYTES", "PDF_PAGE_TEXT", "UNRESOLVED"]
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    normalization_sha256: str | None = None
    quote: str


class NarrativeProposal(Frozen):
    """Source-observation command, expressly not an AgentRun or validated Claim."""

    schema_version: Literal["g100_source_observation_v1"] = "g100_source_observation_v1"
    record_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    supersedes_memory_id: str | None = None
    owner: str
    scope: Scope
    episode_id: str
    research_state_id: str
    created_at: Clock
    research_as_of: Clock
    subject: str
    statement: str = Field(min_length=1)
    source_ref: SourceReference
    evidence_locator: EvidenceLocator
    source_sha256: str
    attribution: str
    relevant_period: str | None
    kind: Literal["DIRECT_SOURCE", "PARAPHRASE", "RESEARCH_HYPOTHESIS"]
    retention_horizon: Literal["SHORT", "MEDIUM", "LONG"]


class SemanticReviewFixture(Frozen):
    """Injected engineering fixture only; never a genuine independent review."""

    origin: Literal["SYNTHETIC_ENGINEERING_FIXTURE"] = "SYNTHETIC_ENGINEERING_FIXTURE"
    proposal_sha256: str
    faithful: bool
    reviewer: Literal["ENGINEERING_TEST_ONLY"] = "ENGINEERING_TEST_ONLY"


class NarrativeRecord(Frozen):
    """Authority, research status and retention are independent axes."""

    schema_version: Literal["g100_hybrid_record_v1"] = "g100_hybrid_record_v1"
    admission_channel: Literal["SOURCE_ANCHORED_NARRATIVE"] = (
        "SOURCE_ANCHORED_NARRATIVE"
    )
    proposal: NarrativeProposal
    source_receipt_identity: str
    source_origin: Literal["REAL_RETAINED_SOURCE", "SYNTHETIC_ENGINEERING_FIXTURE"]
    publisher: str
    source_type: Literal[
        "SEC_FILING", "OFFICIAL_RELEASE", "RESEARCH_REPORT", "COMMUNITY", "EVENT"
    ]
    published_at: Clock | None
    publication_literal: str | None
    acquired_at: Clock
    source_available_at: Clock
    availability_basis: Literal["CONSERVATIVE_LOCAL_OBSERVATION_NOT_PUBLICATION"] = (
        "CONSERVATIVE_LOCAL_OBSERVATION_NOT_PUBLICATION"
    )
    fact_authority: Literal[
        "SOURCE_ATTRIBUTED_STATEMENT", "NONE", "REVIEWED_PARAPHRASE_FIXTURE"
    ]
    support_status: Literal[
        "EXACT_SOURCE_LOCATOR", "LOCATOR_PENDING", "SOURCE_LINK_ONLY"
    ]
    review_status: Literal[
        "SOURCE_BINDING_VERIFIED",
        "PENDING_LOCATOR",
        "PENDING_SEMANTIC_REVIEW",
        "UNVERIFIED_RESEARCH",
        "ENGINEERING_REVIEW_FIXTURE",
    ]
    research_status: Literal["NOT_AN_AGENT_RESULT", "UNVERIFIED_RESEARCH"]
    review_due_at: Clock
    world_fact_authority: Literal[False] = False
    research_result_accepted: Literal[False] = False
    scientific_memory_admitted: Literal[False] = False
    numeric_policy: Literal["STRICT_VALIDATION_REQUIRED_FOR_WORLD_FACT"] = (
        "STRICT_VALIDATION_REQUIRED_FOR_WORLD_FACT"
    )
