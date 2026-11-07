"""Resolve selected evidence without granting support or repairing model prose."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evidence_v2.models import ClaimProposal
from evidence_v2.registry import AccessChecker, Registry, resolve, sha
from src.schemas.research_v2_shared import canonical
from tools.g107_matrix import strict_object


@dataclass(frozen=True)
class FixedClaim:
    """The exact system-owned target survives paraphrase or weaker subfacts."""

    claim_id: str
    statement: str
    target_json: str
    original_input_sha256: str

    @property
    def fingerprint(self) -> str:
        """Bind original text, strength/scope preparation and actual input."""
        return sha(canonical(asdict(self)))


def link(
    claim: FixedClaim,
    proposal: ClaimProposal,
    registry: Registry,
    checker: AccessChecker,
    *,
    checked_at: str,
    research_as_of: str,
    scope: str,
) -> dict[str, Any]:
    """Preserve authored reasoning and independent resolutions; never entailment.

    A single unresolved selection cannot erase other evidence or readable
    reasoning. No missing premise, subfact or causal conclusion is invented.
    Original meaning review remains mandatory even if every handle resolves.
    """
    if proposal.claim_id != claim.claim_id:
        raise ValueError("ORIGINAL_CLAIM_IDENTITY")
    groups: list[tuple[str, Any]] = [
        ("evidence", proposal.evidence),
        ("counterevidence", proposal.counterevidence),
    ]
    groups += [
        (f"supported_subfacts/{i}/evidence", s.evidence)
        for i, s in enumerate(proposal.supported_subfacts)
    ]
    groups += [
        (f"premises/{i}/evidence", p.evidence) for i, p in enumerate(proposal.premises)
    ]
    resolutions = []
    for path, selections in groups:
        for ordinal, selection in enumerate(selections):
            result = resolve(
                registry,
                selection.handle,
                checker,
                scope=scope,
                research_as_of=research_as_of,
                checked_at=checked_at,
            )
            resolutions.append(
                {
                    "selection_path": f"/{path}/{ordinal}",
                    "model_authored": selection.model_dump(mode="json"),
                    **result,
                }
            )
    blockers = []
    if not proposal.evidence:
        blockers.append("NO_PRIMARY_EVIDENCE_SELECTED")
    if any(r["resolution_state"] != "EVIDENCE_RESOLVED" for r in resolutions):
        blockers.append("UNRESOLVED_OR_INELIGIBLE_SELECTION_REQUIRES_REVIEW")
    if (
        proposal.judgment.original_complete_claim == "SUPPORTED"
        and proposal.missing_necessary_premises
    ):
        blockers.append("MODEL_DECLARED_SUPPORT_WITH_MISSING_PREMISES")
    return {
        "original_claim": {
            **asdict(claim),
            "fingerprint": claim.fingerprint,
            "owner": "SYSTEM_BOUND",
            "evaluation_target": "ORIGINAL_COMPLETE_MEANING",
        },
        "model_authored_proposal": proposal.model_dump(mode="json"),
        "evidence_resolutions": resolutions,
        "resolved_evidence_count": sum(
            r["resolution_state"] == "EVIDENCE_RESOLVED" for r in resolutions
        ),
        "technical_or_consistency_blockers": blockers,
        "claim_supported": None,
        "support_review_state": "PENDING_SEMANTIC_REVIEW_OF_ORIGINAL_COMPLETE_CLAIM",
        "required_review": [
            "original meaning/strength preserved despite interpretation",
            "each necessary explicit and implicit premise",
            "selected evidence actual entailment/scope",
            "counterevidence and supported subfacts",
            "conditional possibility versus observed condition/occurrence",
        ],
        "semantic_prediction": proposal.judgment.original_complete_claim,
        "independent_gold": None,
        "scientific_admission": "NOT_PERFORMED_NO_AUTHORITY",
        "business_writes": False,
    }


def consume(
    raw: bytes,
    archive: Path,
    claims: tuple[FixedClaim, ...],
    registry: Registry,
    checker: AccessChecker,
    *,
    submission_context_registry_id: str,
    checked_at: str,
    research_as_of: str,
    scope: str,
) -> dict[str, Any]:
    """Archive exact original bytes and retain independent proposal outcomes.

    The caller must authenticate the capture/registry association. A registry ID
    argument is not a new authorization system. W1 owns actual runtime identity.
    """
    archive.mkdir(parents=True, exist_ok=False)
    (archive / "submission.raw").write_bytes(raw)
    result: dict[str, Any] = {
        "raw_sha256": sha(raw),
        "registry_id": registry.identity,
        "raw_state": "NOT_PARSED",
        "items": [],
        "missing_claim_ids": [c.claim_id for c in claims],
        "task_complete": False,
        "scientific_admission": False,
    }
    try:
        if submission_context_registry_id != registry.identity:
            raise ValueError("CAPTURE_REGISTRY_BINDING_MISMATCH")
        obj = strict_object(raw.decode("utf-8", errors="strict"))
        if set(obj) != {"proposals"} or not isinstance(obj["proposals"], list):
            raise ValueError("SUBMISSION_ENVELOPE")
        result["raw_state"] = "STRICT_JSON_PARSED"
        known = {c.claim_id: c for c in claims}
        seen: list[str] = []
        for ordinal, item in enumerate(obj["proposals"]):
            row: dict[str, Any] = {"ordinal": ordinal, "original_item": item}
            try:
                proposal = ClaimProposal.model_validate(item)
                if proposal.claim_id not in known or proposal.claim_id in seen:
                    raise ValueError("UNKNOWN_OR_DUPLICATE_CLAIM_ID")
                seen.append(proposal.claim_id)
                row["application"] = link(
                    known[proposal.claim_id],
                    proposal,
                    registry,
                    checker,
                    checked_at=checked_at,
                    research_as_of=research_as_of,
                    scope=scope,
                )
            except (ValidationError, ValueError, TypeError) as exc:
                row["error"] = str(exc)
            result["items"].append(row)
        # Do not turn a partial population or duplicate result into completion.
        result["missing_claim_ids"] = sorted(set(known) - set(seen))
        result["task_complete"] = (
            not result["missing_claim_ids"]
            and len(result["items"]) == len(claims)
            and all(
                "error" not in r
                and not r["application"]["technical_or_consistency_blockers"]
                for r in result["items"]
            )
        )
        result["task_complete_meaning"] = (
            "STRUCTURAL_PROPOSAL_COVERAGE_ONLY_NOT_COMPLETE_RESEARCH_OR_SCIENTIFIC_SUCCESS"
        )
    except (ValueError, TypeError, KeyError) as exc:
        result["error"] = str(exc)
    (archive / "mechanism-result.json").write_bytes(canonical(result))
    return result
