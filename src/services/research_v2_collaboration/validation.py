"""Reference-only boundary to existing Claim/Evidence and W3 validators."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Protocol

from src.agents.evidence import numeric_literals
from src.agents.numeric_grounding import (
    NativeNumericBinding,
    validate_numeric_grounding,
)
from src.models.enums import ClaimIntent
from src.schemas.agents import RoleEvidenceManifestEntry, ValidatedClaim
from src.schemas.common import SourceReference
from src.schemas.evidence_closure import DocumentChunkProofV2
from src.schemas.research_data import ResearchEvidenceItem
from src.schemas.research_v2_collaboration import (
    AnalystResult,
    Contradiction,
    Question,
    ResearchPlan,
    Statement,
    SynthesisState,
)
from src.schemas.research_v2_shared import (
    ClaimDecision,
    EvidenceDecision,
    Reference,
    Revision,
    RunBinding,
    canonical,
)


class EvidenceResolver(Protocol):
    """W3 shared envelope plus opaque, independently validated receipt boundary."""

    def artifact(self, ref: Reference) -> bytes:
        """Resolve exact versioned immutable bytes or raise an integrity error."""
        ...

    def resolve_evidence(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> EvidenceDecision:
        """Verify canonical lineage/owner/PIT and retain unusable reasons."""
        ...

    def resolve_claim(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> ClaimDecision:
        """Validate accepted Claim through all required upstream Evidence."""
        ...

    def validate_receipt(
        self, ref: Reference, binding: RunBinding, revision: Revision
    ) -> None:
        """Independently validate receipt meaning, not just its digest shape."""
        ...


class ReferenceValidator:
    """Check every returned sibling before deciding its usage; never filter first."""

    def __init__(
        self,
        resolver: EvidenceResolver,
        binding: RunBinding,
        *,
        native_numeric: NativeNumericBinding | None = None,
    ) -> None:
        """Inject canonical validators; no providers, gateway or database handle."""
        self.native_numeric = native_numeric
        self.resolver = resolver
        self.binding = binding
        self._local: dict[Reference, bytes] = {}
        self._resolved: dict[Reference, bytes] = {}

    @property
    def local_artifacts(self) -> dict[Reference, bytes]:
        """Return a copy of runtime-owned immutable bytes for local replay/export."""
        return dict(self._local)

    @property
    def resolved_artifacts(self) -> dict[Reference, bytes]:
        """Preserve every consumed source and runtime artifact for export."""
        return {**self._resolved, **self._local}

    def bind(self, ref: Reference, value: object) -> None:
        """Register runtime-owned immutable bytes without replacing source authority."""
        raw = canonical(value)
        if hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("LOCAL_ARTIFACT_HASH")
        old = self._local.get(ref)
        if old is not None and old != raw:
            raise ValueError("LOCAL_ARTIFACT_CONFLICT")
        self._local[ref] = raw

    def artifact(self, ref: Reference) -> bytes:
        """Verify actual resolved bytes for the exact namespace/version/key."""
        raw = self._local[ref] if ref in self._local else self.resolver.artifact(ref)
        if hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("REFERENCE_HASH_MISMATCH")
        self._resolved[ref] = raw
        return raw

    def receipt(self, ref: Reference, revision: Revision) -> None:
        """Check both receipt bytes and validator-owned authority semantics."""
        ref.require("RECEIPT")
        self.artifact(ref)
        self.resolver.validate_receipt(ref, self.binding, revision)

    def context(self, plan: ResearchPlan) -> None:
        """Read canonical v1 State/Episode without implicitly upgrading its Claims."""
        from src.schemas.research_episode import ResearchEpisode
        from src.schemas.research_state import ResearchStateSnapshot

        raw = self.artifact(plan.episode)
        if plan.episode.version == "research_episode_v1":
            episode = ResearchEpisode.model_validate_json(raw)
            if (
                episode.episode_id != plan.episode.id
                or episode.research_as_of > plan.research_as_of
                or episode.created_at > plan.research_as_of
                or str(episode.asset_id) not in plan.requested_assets
            ):
                raise ValueError("LEGACY_EPISODE_CONTEXT")
        elif (
            plan.episode.version == "synthetic_episode_fixture_v1"
            and self.binding.mode == "SYNTHETIC_OFFLINE"
        ):
            fixture = json.loads(raw)
            if (
                fixture.get("mode") != "SYNTHETIC_OFFLINE"
                or fixture.get("episode_id") != plan.episode.id
            ):
                raise ValueError("SYNTHETIC_EPISODE_CONTEXT")
        else:
            raise ValueError("UNSUPPORTED_EPISODE_VERSION")
        for ref in plan.input_snapshots:
            if ref.namespace == "STATE" and ref.version == "research_state_snapshot_v1":
                state = ResearchStateSnapshot.model_validate_json(self.artifact(ref))
                if (
                    state.research_state_id != ref.id
                    or state.research_as_of > plan.research_as_of
                    or str(state.asset_id) not in plan.requested_assets
                ):
                    raise ValueError("LEGACY_STATE_CONTEXT")

    def evidence(
        self, ref: Reference, revision: Revision, owner: str, *, factual: bool = True
    ) -> EvidenceDecision:
        """Require exact plan/run/read revision, owner and independently valid proof."""
        ref.require("EVIDENCE")
        self.artifact(ref)
        d = self.resolver.resolve_evidence(ref, self.binding, revision)
        if (
            d.binding != self.binding
            or d.state_revision != revision
            or d.evidence != ref
            or d.owner_asset_id != owner
        ):
            raise ValueError("EVIDENCE_BINDING_MISMATCH")
        self.artifact(d.source)
        self.receipt(d.validation_receipt, revision)
        if d.temporal_authority:
            self.receipt(d.temporal_authority, revision)
        if not d.independently_valid or d.research_usage == "QUARANTINED":
            raise ValueError("UNUSABLE_EVIDENCE")
        if factual and (
            d.participation != "PIT_COUNTED_EVIDENCE"
            or d.research_usage != "ACCEPTED_FACT_SUPPORT"
            or not d.required_slot_satisfied
            or d.temporal_authority is None
        ):
            raise ValueError("EVIDENCE_CANNOT_SUPPORT_PIT_FACT")
        return d

    def claim(self, ref: Reference, revision: Revision, owner: str) -> ValidatedClaim:
        """Reuse canonical accepted Claim model and resolve its complete closure."""
        ref.require("CLAIM")
        claim = ValidatedClaim.model_validate_json(self.artifact(ref))
        d = self.resolver.resolve_claim(ref, self.binding, revision)
        if (
            d.binding != self.binding
            or d.state_revision != revision
            or d.claim != ref
            or d.owner_asset_id != owner
            or not d.eligible_for_pit_count
        ):
            raise ValueError("CLAIM_BINDING_OR_ELIGIBILITY")
        self.receipt(d.validation_receipt, revision)
        if claim.claim_id != ref.id:
            raise ValueError("CLAIM_IDENTITY_MISMATCH")
        if not d.required_evidence or set(claim.evidence_ids) != {
            r.id for r in d.required_evidence
        }:
            raise ValueError("CLAIM_REQUIRED_EVIDENCE_CLOSURE")
        for evidence in d.required_evidence:
            self.evidence(evidence, revision, owner)
        return claim

    def statement(self, statement: Statement, revision: Revision, owner: str) -> None:
        """Kinds do not grant new numeric authority; FACT also requires exact text."""
        texts = []
        native_entries: list[RoleEvidenceManifestEntry] = []
        entries: list[RoleEvidenceManifestEntry] = []
        for ref in (
            *statement.support,
            *statement.counter_evidence,
            *statement.confidence.support,
        ):
            if ref.namespace == "CLAIM":
                claim = self.claim(ref, revision, owner)
                if (
                    statement.kind == "FACT"
                    and claim.claim_intent is not ClaimIntent.FACT
                ):
                    raise ValueError("FACT_SUPPORT_INTENT")
                texts.append(claim.claim_text)
                if (
                    self.native_numeric is not None
                    and statement.kind == "FACT"
                    and statement.text == claim.claim_text
                ):
                    # Only an original-validator accepted Claim can supply these
                    # exact source references. No synthesis text gains authority.
                    native_decision = self.resolver.resolve_claim(
                        ref, self.binding, revision
                    )
                    for evidence in native_decision.required_evidence:
                        doc = DocumentChunkProofV2.model_validate_json(
                            self.artifact(evidence)
                        )
                        native_entries.append(
                            RoleEvidenceManifestEntry(
                                evidence_id=doc.canonical_id,
                                evidence_type="document",
                                source=doc.exact_citation_reference,
                                short_description=doc.chunk_text,
                                numeric_tokens=numeric_literals(doc.chunk_text),
                            )
                        )
                entries.append(
                    RoleEvidenceManifestEntry(
                        evidence_id=ref.id,
                        evidence_type="structured_direct",
                        source=SourceReference(
                            provider="VALIDATED_CLAIM", excerpt_ref=ref.id
                        ),
                        short_description=claim.claim_text,
                        numeric_tokens=claim.numeric_literals,
                    )
                )
            elif ref.namespace == "EVIDENCE":
                decision = self.evidence(
                    ref, revision, owner, factual=statement.kind == "FACT"
                )
                if (
                    decision.participation == "PIT_COUNTED_EVIDENCE"
                    and decision.required_slot_satisfied
                    and decision.temporal_authority
                ):
                    raw = json.loads(self.artifact(ref))
                    if ref.version == "canonical_evidence_v1":
                        entries.append(RoleEvidenceManifestEntry.model_validate(raw))
                    elif ref.version == "ResearchEvidenceItem/1.0":
                        item = ResearchEvidenceItem.model_validate(raw)
                        entries.append(
                            RoleEvidenceManifestEntry(
                                evidence_id=ref.id,
                                evidence_type="structured_direct",
                                source=item.to_source_reference(),
                                short_description=str(item.value),
                                numeric_tokens=numeric_literals(str(item.value)),
                            )
                        )
            elif ref.namespace == "HYPOTHESIS" and statement.kind != "FACT":
                self.artifact(ref)
            else:
                raise ValueError("STATEMENT_REFERENCE_KIND")
        if statement.kind == "FACT" and statement.text not in texts:
            raise ValueError("NEW_UNVALIDATED_SYNTHESIS_FACT")
        # Presentation-only ordered-list markers are not financial quantities.
        # Dates/identifiers retain the existing grounder's semantic treatment;
        # there is no hypothetical forecast/assumption-number exception.
        lines = statement.text.splitlines()
        markers = [re.fullmatch(r"\s*(\d+)[.)]\s+([A-Za-z].*)", line) for line in lines]
        text = statement.text
        if len(markers) > 1 and all(markers):
            parsed = [m for m in markers if m is not None]
            if [int(m.group(1)) for m in parsed] == list(range(1, len(parsed) + 1)):
                text = "\n".join(m.group(2) for m in parsed)
        grounding = validate_numeric_grounding(text, entries)
        if native_entries:
            grounding = validate_numeric_grounding(
                text, native_entries, native_binding=self.native_numeric
            )
        if grounding.ungrounded_literals:
            raise ValueError(
                "UNSUPPORTED_STATEMENT_NUMERIC:"
                + ",".join(grounding.ungrounded_literals)
            )

    def contradiction(
        self, value: Contradiction, revision: Revision, owner: str
    ) -> None:
        """Keep hypotheses separate and delegate fact comparability."""
        for ref in [value.left, value.right]:
            if value.kind == "HYPOTHESIS_DISAGREEMENT":
                self.artifact(ref)
            else:
                self.claim(ref, revision, owner)
        if value.comparability_receipt:
            self.receipt(value.comparability_receipt, revision)
            # The independently checked receipt must also attest the exact pair/type.

            proof = json.loads(self.artifact(value.comparability_receipt))
            if (
                proof.get("kind") != value.kind
                or proof.get("left") != value.left.model_dump(mode="json")
                or proof.get("right") != value.right.model_dump(mode="json")
            ):
                raise ValueError("CONTRADICTION_KIND_OR_PAIR_MISMATCH")
        for ref in value.resolution_refs:
            self.receipt(ref, revision)

    def question(self, value: Question, revision: Revision) -> None:
        """A question's RESOLVED status needs proof of its original requirement."""
        for ref in value.subject_refs:
            self.artifact(ref)
        for ref in value.resolution_refs:
            self.receipt(ref, revision)
        if value.status == "RESOLVED":
            if not value.resolution_refs:
                raise ValueError("QUESTION_RESOLUTION_PROOF")
            for ref in value.resolution_refs:
                proof = json.loads(self.artifact(ref))
                if (
                    proof.get("question_id") != value.id
                    or proof.get("required_resolution") != value.required_resolution
                    or proof.get("satisfied") is not True
                ):
                    raise ValueError("QUESTION_ORIGINAL_CONDITIONS")

    def analyst(self, result: AnalystResult, revision: Revision) -> None:
        """Validate the complete result before any State write."""
        if (
            result.run_id != self.binding.run_id
            or result.plan != self.binding.plan
            or result.episode != self.binding.episode
            or result.research_as_of != self.binding.research_as_of
            or result.read_state != revision.state
        ):
            raise ValueError("ANALYST_BINDING_MISMATCH")
        for ref in [
            result.model,
            result.prompt,
            result.producer_build,
            *result.dependencies,
            *result.followup_requests,
        ]:
            self.artifact(ref)
        for c in result.coverage:
            for ref in c.evidence_refs:
                self.evidence(ref, revision, result.scope_id)
        for ref in result.claims:
            self.claim(ref, revision, result.scope_id)
        for ref in result.evidence_refs:
            self.evidence(ref, revision, result.scope_id)
        for s in (*result.findings, *result.hypotheses, *result.uncertainties):
            self.statement(s, revision, result.scope_id)
        for f in result.quantitative_facts:
            self.claim(f.claim, revision, result.scope_id)
            self.receipt(f.grounding_receipt, revision)

            proof = json.loads(self.artifact(f.grounding_receipt))
            if (
                proof.get("claim") != f.claim.model_dump(mode="json")
                or proof.get("value") != f.value
                or proof.get("unit") != f.unit
                or proof.get("period_basis") != f.period_basis
                or proof.get("operand_refs")
                != [r.model_dump(mode="json") for r in f.operand_refs]
            ):
                raise ValueError("QUANTITATIVE_GROUNDING_MISMATCH")
            for ref in f.operand_refs:
                self.artifact(ref)
        for value in result.contradictions:
            self.contradiction(value, revision, result.scope_id)
        for question in result.open_questions:
            self.question(question, revision)
        for trigger in (*result.risks, *result.catalysts):
            self.statement(trigger.statement, revision, result.scope_id)
            for ref in trigger.dependencies:
                self.artifact(ref)
        if any(c.status == "COMPLETE" for c in result.coverage) and (
            any(c.status != "RESOLVED" for c in result.contradictions)
            or any(q.status != "RESOLVED" for q in result.open_questions)
        ):
            raise ValueError("MANDATORY_UNRESOLVED_COVERAGE")

    def synthesis(
        self, value: SynthesisState, revision: Revision, owners: dict[Reference, str]
    ) -> None:
        """Validate all scenarios and opposing reference siblings."""
        if (
            value.state_revision != revision.state
            or value.run_id != self.binding.run_id
            or value.research_as_of != self.binding.research_as_of
        ):
            raise ValueError("SYNTHESIS_REVISION_MISMATCH")
        for scenario in [value.base_case, value.bull_case, value.bear_case]:
            for ref in (*scenario.major_evidence, *scenario.opposing_evidence):
                self.evidence(ref, revision, owners.get(ref, ""), factual=False)
            for s in (
                *scenario.statements,
                *scenario.assumptions,
                *scenario.mechanisms,
                *scenario.uncertainties,
            ):
                owner = next((owners[r] for r in s.support if r in owners), "")
                self.statement(s, revision, owner)
            for trigger in (
                *scenario.catalysts,
                *scenario.risk_triggers,
                *scenario.thesis_change_conditions,
            ):
                owner = next(
                    (owners[r] for r in trigger.statement.support if r in owners),
                    "",
                )
                self.statement(trigger.statement, revision, owner)
                for ref in trigger.dependencies:
                    self.artifact(ref)
            for c in scenario.contradictions:
                self.contradiction(c, revision, owners.get(c.left, ""))
            for question in scenario.open_questions:
                self.question(question, revision)
        for ref in value.dependencies:
            self.artifact(ref)
