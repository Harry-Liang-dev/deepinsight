"""Offline minimal proposal and trusted assembly, never scientific admission.

No sender, grant installation, semantic repair, or write to business state exists
in this module. CurrentAccessChecker remains a trusted composition dependency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from evidence_v2.mechanism import FixedClaim
from evidence_v2.registry import AccessChecker, Registry, resolve, time
from src.agents.evidence import numeric_literals
from src.agents.numeric_grounding import (
    NativeNumericBinding,
    validate_numeric_grounding,
)
from src.schemas.research_v2_shared import canonical
from src.services.native_preservation import blob_hash
from tools.evidence_v2_runtime import (
    CaptureBinding,
    CurrentAccessChecker,
    verify_capture,
)
from tools.g107_matrix import strict_object
from tools.g113_r9_integrity import prose_errors

VERSION = "MINIMAL_SEMANTIC_PROPOSAL_V1"
Verdict = Literal["SUPPORTED", "UNSUPPORTED", "UNDETERMINED"]


class MinimalSemanticProposal(BaseModel):
    """Only model-owned semantic fields; system identities are forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    verdict: Verdict
    evidence_handles: list[str]
    reasoning: str
    missing_premises: list[str]
    counterevidence_handles: list[str]
    uncertainty: str

    @field_validator("reasoning", "uncertainty")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        """Reject empty reasoning without trimming or rewriting the original."""
        if not value.strip():
            raise ValueError("EMPTY_REASONING")
        return value

    @field_validator("evidence_handles", "counterevidence_handles", "missing_premises")
    @classmethod
    def exact_items(cls, value: list[str]) -> list[str]:
        """Reject empty and duplicate elements; never silently deduplicate."""
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("EMPTY_OR_DUPLICATE_ITEM")
        return value


def proposal_schema() -> dict[str, Any]:
    """Small SDK-portable schema; exact handles and duplicate checks stay local."""
    shape = MinimalSemanticProposal.model_json_schema()
    shape.pop("title", None)
    for field in shape["properties"].values():
        field.pop("title", None)
    return shape


@dataclass(frozen=True)
class TrustedTask:
    """Runtime-owned complete parent and visible registry, never model JSON."""

    claim: FixedClaim
    research_as_of: str
    scope: str
    registry_identity: str


@dataclass
class _NumericEntry:
    evidence_id: str
    short_description: str
    numeric_tokens: tuple[str, ...]


def assemble(
    raw: bytes,
    task: TrustedTask,
    registry: Registry,
    checker: AccessChecker,
    *,
    checked_at: str,
    native_numeric_binding: NativeNumericBinding | None = None,
) -> dict[str, Any]:
    """Bind explicit selections to the original parent; never infer entailment.

    The caller must archive/authenticate raw bytes first (consume_archived does
    so using the existing verifier). This pure adapter is also useful offline.
    Authority exceptions propagate as system stops, not semantic UNSUPPORTED.
    """
    if registry.identity != task.registry_identity or not task.claim.statement:
        raise ValueError("TRUSTED_TASK_REGISTRY_DRIFT")
    if time(task.research_as_of) > time(checked_at):
        raise ValueError("FUTURE_RESEARCH_CUTOFF")
    access = checker.check(registry.identity, task.scope, checked_at)
    if (
        access.registry_id != registry.identity
        or access.scope != task.scope
        or not access.receipt_identity
        or time(access.checked_at) != time(checked_at)
        or time(access.valid_until) < time(checked_at)
        or any(
            dict(access.checks).get(k) != "PASS"
            for k in ("F01", "ACL", "TTL", "CAS", "REVOCATION", "SOURCE_VERSION")
        )
    ):
        raise ValueError("CURRENT_AUTHORITY_REJECTED")
    result: dict[str, Any] = dict(
        assessment_type="TrustedClaimAssessment",
        version=VERSION,
        original_complete_claim=asdict(task.claim),
        system_bound_temporal_metadata=dict(research_as_of=task.research_as_of),
        current_authority=asdict(access),
        source_registry_identity=registry.identity,
        assistant_sha256=blob_hash(raw),
        proposal=None,
        candidate_prediction=None,
        prediction_state="NO_PREDICTION",
        errors=[],
        resolutions=[],
        mechanical_eligibility=False,
        semantic_entailment="NOT_EVALUATED",
        model_temporal_reasoning="NOT_EVALUATED",
        scientific_admission=False,
        formal_numeric_admission=False,
        live_release_authorized=False,
    )
    try:
        proposal = MinimalSemanticProposal.model_validate(
            strict_object(raw.decode("utf-8", errors="strict"))
        )
    except (ValueError, UnicodeError) as exc:
        result["errors"] = [dict(stage="STRICT_PARSE_OR_TYPE", code=type(exc).__name__)]
        return result
    result["proposal"] = proposal.model_dump()
    blockers = []
    for field in ("evidence_handles", "counterevidence_handles"):
        for handle in getattr(proposal, field):
            resolved = resolve(
                registry,
                handle,
                checker,
                scope=task.scope,
                research_as_of=task.research_as_of,
                checked_at=checked_at,
            )
            result["resolutions"].append(dict(field=field, **resolved))
            if resolved["resolution_state"] == "INELIGIBLE":
                # A current-authority/source failure is not a content prediction.
                raise ValueError("CURRENT_SOURCE_OR_AUTHORITY_REJECTED")
            if resolved["resolution_state"] != "EVIDENCE_RESOLVED":
                blockers.append(
                    dict(stage="HANDLE", code="EXACT_HANDLE_REQUIRED", handle=handle)
                )
    if proposal.verdict == "SUPPORTED":
        if not proposal.evidence_handles:
            blockers.append(dict(stage="CONSISTENCY", code="SUPPORT_WITHOUT_EVIDENCE"))
        if proposal.missing_premises:
            blockers.append(dict(stage="CONSISTENCY", code="DECLARED_MISSING_PREMISE"))
    # Numeric literals use only selected real source spans, never all catalog
    # values or system metadata promoted to world-fact authority.
    entries = tuple(
        _NumericEntry(e.handle, e.text, tuple(numeric_literals(e.text)))
        for h in dict.fromkeys(
            proposal.evidence_handles + proposal.counterevidence_handles
        )
        if (e := registry.entries.get(h)) is not None
        and e.authority_kind == "SOURCE_SPAN"
    )
    numeric = validate_numeric_grounding(
        "\n".join(
            [proposal.reasoning, proposal.uncertainty, *proposal.missing_premises]
        ),
        entries,
        native_binding=native_numeric_binding,
    )
    result["numeric_literal_check"] = asdict(numeric)
    result["numeric_scope"] = "SELECTED_SOURCE_LITERAL_MATCH_NOT_FACT_OR_CAUSAL_PROOF"
    if numeric.ungrounded_literals:
        blockers.append(dict(stage="NUMERIC", code="UNGROUNDED_REASONING_NUMERAL"))
    blockers.extend(prose_errors(proposal.model_dump()))
    result["errors"] = blockers
    result["mechanical_eligibility"] = not blockers
    if not blockers:
        result["candidate_prediction"] = proposal.verdict
        result["prediction_state"] = "DEVELOPMENT_CANDIDATE_NOT_GOLD"
    # Even an empty missing_premises list is only the model's assertion, never a
    # machine proof that all premises of the original causal parent were met.
    return result


def consume_archived(
    target: Path, checker: CurrentAccessChecker, binding: CaptureBinding
) -> dict[str, Any]:
    """Reuse original HTTP/Assistant/Meter authentication before parsing."""
    raw = verify_capture(target, checker, binding)
    response = strict_object((target / "response.raw").read_text())
    if response["status"] != "completed":
        return dict(
            prediction_state="NO_PREDICTION",
            candidate_prediction=None,
            error="INCOMPLETE_PROVIDER_OUTPUT",
            assistant_sha256=blob_hash(raw),
            scientific_admission=False,
        )
    return assemble(
        raw,
        TrustedTask(
            checker.claim,
            checker.packet["trusted_research_as_of"],
            "ASSET:US:MSFT",
            checker.registry.identity,
        ),
        checker.registry,
        checker,
        checked_at=checker.checked_at,
    )


def serialize_assessment(value: dict[str, Any]) -> bytes:
    """Deterministic internal diagnostic JSON; no formal Report/State adapter."""
    if value.get("scientific_admission") is not False:
        raise ValueError("SCIENTIFIC_ADMISSION_DENIED")
    return canonical(value)
