"""Opt-in source/task binding over existing native, Mandate and Memory contracts.

This is context provenance, not a scientific validator, registry or dispatcher.
Trusted composition supplies the retained task reader and registered sources.
"""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from urllib.parse import urlparse

from pydantic import Field, field_validator

from src.agents.contracts import AgentInvocation, ResearchTaskRequest
from src.agents.numeric_grounding import (
    NativeNumericBinding,
    validate_numeric_grounding,
)
from src.memory.contracts import ResearchContextBundle
from src.memory.hybrid_contracts import NarrativeProposal, NarrativeRecord
from src.memory.hybrid_sources import NativeLocatorResolver, RegisteredNarrativeSource
from src.memory.vnext import MemoryAccessContext, content_sha256, read_set_from_bundle
from src.memory.vnext_contracts import (
    ArtifactRef,
    Frozen,
    MemoryReadSet,
    ResearchMandate,
    Scope,
)
from src.models.enums import AgentName, ReportMarketScope, ResearchScopeType
from src.models.identifiers import AssetId
from src.models.types import JsonObject
from src.schemas.agents import AgentContext, AgentRequest, RoleEvidenceManifest
from src.services.native_preservation import NativeManifest
from src.services.research_vnext.contracts import RetainedReader, resolve
from src.services.research_vnext.radar import require_mandate


class SourceSelection(Frozen):
    """Explicit pinned source/version plus original locator-bearing proposal."""

    proposal: NarrativeProposal
    receipt_identity: str
    source_revision: str
    available_at: datetime

    @field_validator("available_at")
    @classmethod
    def validate_clock(cls, value: datetime) -> datetime:
        """Reuse frozen UTC contract."""
        return ArtifactRef.utc(value)


class SourceTaskSpec(Frozen):
    """A retained task definition, resolved before inspecting caller run identity."""

    schema_version: Literal["g105_source_task_v1"] = "g105_source_task_v1"
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    run_role: AgentName
    issuer: str = Field(min_length=1)
    cik: str = Field(pattern=r"^\d{10}$")
    scope: Scope
    research_as_of: datetime
    permitted_roles: tuple[AgentName, ...] = Field(min_length=1)
    sources: tuple[SourceSelection, ...] = Field(min_length=1)
    mandate: ArtifactRef | None = None
    disposition: Literal["NO_GO", "SOURCE_BINDING_ONLY", "RESEARCH_ELIGIBLE"]

    @field_validator("research_as_of")
    @classmethod
    def validate_clock(cls, value: datetime) -> datetime:
        """Reuse frozen UTC contract."""
        return ArtifactRef.utc(value)


class SourceReadSet(Frozen):
    """Actual native reads; no canonical Claim, numeric or State authority."""

    schema_version: Literal["g105_source_read_set_v1"] = "g105_source_read_set_v1"
    task: ArtifactRef
    run_id: str
    issuer: str
    cik: str
    scope: Scope
    research_as_of: datetime
    role: AgentName
    records: tuple[NarrativeRecord, ...]
    revisions: tuple[str, ...]
    authority: Literal["SOURCE_ATTRIBUTION_ONLY"] = "SOURCE_ATTRIBUTION_ONLY"
    world_fact_authority: Literal[False] = False
    financial_authority: Literal[False] = False


@dataclass(frozen=True)
class BoundSourceTask:
    """Original request plus explicit provenance sidecars, never an Agent result."""

    spec: SourceTaskSpec
    source_reads: SourceReadSet
    memory_reads: MemoryReadSet
    request: ResearchTaskRequest
    dispatch_block: str | None


class SourceTaskBinder:
    """Recheck existing registered native objects; do not store or grant facts."""

    def __init__(
        self,
        *,
        sources: Mapping[str, RegisteredNarrativeSource],
        issuer_metadata: RegisteredNarrativeSource,
        reader: RetainedReader,
        enabled: bool = False,
        canonical_evidence: (
            Callable[[SourceTaskSpec], RoleEvidenceManifest] | None
        ) = None,
    ) -> None:
        self.sources = dict(sources)
        self.metadata = issuer_metadata
        self.reader = reader
        self.resolver = NativeLocatorResolver(self.sources)
        self.enabled = enabled
        # Trusted original producer resolver, separate from numeric validation.
        # Never obtain this dependency or its records from request/model fields.
        self.canonical_evidence = canonical_evidence

    @staticmethod
    def _native(source: RegisteredNarrativeSource) -> NativeManifest:
        native = source.store.recover(source.manifest_identity)
        if (
            native.status_code != 200
            or native.acquisition.body_sha256 != source.raw_sha256
            or native.acquisition.owner != source.subject
            or native.acquisition.endpoint != source.source_ref.source_url
            or native.acquisition.provider != source.source_ref.provider
        ):
            raise ValueError("G105_REGISTERED_NATIVE_IDENTITY")
        return native

    def _issuer(self, spec: SourceTaskSpec) -> None:
        native = self._native(self.metadata)
        raw = base64.b64decode(native.acquisition.body_base64, validate=True)
        if native.acquisition.content_encoding == "gzip":
            raw = gzip.decompress(raw)
        elif native.acquisition.content_encoding != "identity":
            raise ValueError("G105_UNSUPPORTED_METADATA_ENCODING")
        metadata = json.loads(raw)
        expected_url = f"https://data.sec.gov/submissions/CIK{spec.cik}.json"
        if (
            self.metadata.subject != spec.issuer
            or native.acquisition.endpoint != expected_url
            or f"{int(metadata['cik']):010d}" != spec.cik
            or spec.issuer not in {"US:" + ticker for ticker in metadata["tickers"]}
            or spec.scope.scope_type != ResearchScopeType.ASSET
            or spec.scope.scope_id != "ASSET:" + spec.issuer
        ):
            raise ValueError("G105_ISSUER_CIK_SCOPE")
        if (
            max(native.ingested_at, native.acquisition.observed_at)
            > spec.research_as_of
        ):
            raise ValueError("G105_FUTURE_ISSUER_METADATA")

    def bind(
        self,
        task_ref: ArtifactRef,
        *,
        run_id: str,
        role: AgentName,
        access: MemoryAccessContext,
        memory_bundle: ResearchContextBundle,
        memory_refs: Mapping[str, ArtifactRef],
        model_name: str,
    ) -> BoundSourceTask:
        """Read exact native versions and return original ResearchTaskRequest."""
        if not self.enabled:
            raise ValueError("G105_OPT_IN_REQUIRED")
        spec = SourceTaskSpec.model_validate_json(resolve(task_ref, self.reader))
        task_ref.require_recorded_by(spec.research_as_of)
        if task_ref.artifact_id != spec.task_id or task_ref.owner != spec.issuer:
            raise ValueError("G105_TASK_IDENTITY")
        if run_id != spec.run_id:
            raise ValueError("G105_RUN_IDENTITY")
        if (
            role != spec.run_role
            or role not in spec.permitted_roles
            or access.role != role
        ):
            raise ValueError("G105_ROLE_IDENTITY")
        access.require("READ_HISTORY", spec.scope)
        self._issuer(spec)
        ids = [
            (p.proposal.source_ref.document_id, p.proposal.evidence_locator.sha256)
            for p in spec.sources
        ]
        if len(set(ids)) != len(ids):
            raise ValueError("G105_DUPLICATE_SOURCE")
        records = []
        for selected in spec.sources:
            proposal = selected.proposal
            source = self.sources[proposal.source_ref.document_id or ""]
            native = self._native(source)
            available = max(
                native.ingested_at,
                native.acquisition.observed_at,
                source.published_at or native.ingested_at,
            )
            if (
                source.subject != spec.issuer
                or proposal.subject != spec.issuer
                or proposal.scope != spec.scope
                or proposal.owner != access.owner
                or proposal.research_as_of != spec.research_as_of
                or proposal.kind != "DIRECT_SOURCE"
            ):
                raise ValueError("G105_SOURCE_OWNER_SCOPE_TIME")
            if (
                selected.receipt_identity != source.manifest_identity
                or selected.source_revision != native.acquisition.revision_id
                or selected.available_at != available
                or available > spec.research_as_of
            ):
                raise ValueError("G105_RECEIPT_REVISION_TIME")
            url = urlparse(native.acquisition.endpoint)
            if source.source_type == "SEC_FILING" and (
                url.scheme != "https"
                or url.hostname != "www.sec.gov"
                or not url.path.startswith(f"/Archives/edgar/data/{int(spec.cik)}/")
            ):
                raise ValueError("G105_FILING_CIK")
            records.append(self.resolver.validate(proposal))
        readset = SourceReadSet(
            task=task_ref,
            run_id=run_id,
            issuer=spec.issuer,
            cik=spec.cik,
            scope=spec.scope,
            research_as_of=spec.research_as_of,
            role=role,
            records=tuple(records),
            revisions=tuple(s.source_revision for s in spec.sources),
        )
        cutoff = memory_bundle.retrieval_metadata.as_of
        if (
            cutoff != spec.research_as_of
            or str(memory_bundle.retrieval_metadata.asset_id) != spec.issuer
        ):
            raise ValueError("G105_MEMORY_ASSET_CUTOFF")
        bundle_ref = ArtifactRef(
            artifact_id=run_id + ":memory",
            sha256_digest=content_sha256(memory_bundle),
            version="research_context_bundle_v1",
            owner=access.owner,
            available_at=cutoff,
            observed_at=cutoff,
            ingested_at=cutoff,
        )
        reads = read_set_from_bundle(
            memory_bundle,
            bundle_ref=bundle_ref,
            memory_refs=memory_refs,
            access=access,
            scope=spec.scope,
            agent_run_id=run_id,
            record_id=run_id + ":reads",
            created_at=cutoff,
        )
        block = "G105_NO_GO" if spec.disposition == "NO_GO" else None
        if spec.mandate is None:
            block = block or "G105_MANDATE_MISSING"
        else:
            mandate = ResearchMandate.model_validate_json(
                resolve(spec.mandate, self.reader)
            )
            spec.mandate.require_recorded_by(cutoff)
            for allowed_role in spec.permitted_roles:
                require_mandate(
                    mandate,
                    role=allowed_role,
                    scope=spec.scope,
                    at=cutoff,
                    reader=self.reader,
                )
        if spec.disposition == "SOURCE_BINDING_ONLY":
            block = block or "G105_SOURCE_BINDING_ONLY"
        context = AgentContext(
            report_date=cutoff.date(),
            market_scope=ReportMarketScope.US,
            asset_id=AssetId(spec.issuer),
            structured_features=cast(
                JsonObject,
                {
                    "source_read_set": readset.model_dump(mode="json"),
                    "memory_read_set": reads.model_dump(mode="json"),
                    "fact_authority": "SOURCE_ATTRIBUTION_ONLY",
                },
            ),
            # Source assertions are NOT canonical Claim Evidence. Only an original
            # scientific producer may populate that distinct namespace later.
            role_evidence_manifest=RoleEvidenceManifest(agent_name=role, entries=()),
        )
        request = ResearchTaskRequest(
            task_id=spec.task_id, model_name=model_name, input_context=context
        )
        return BoundSourceTask(spec, readset, reads, request, block)

    def invocation(
        self,
        task_ref: ArtifactRef,
        *,
        run_id: str,
        role: AgentName,
        access: MemoryAccessContext,
        memory_bundle: ResearchContextBundle,
        memory_refs: Mapping[str, ArtifactRef],
        model_name: str,
        evidence: RoleEvidenceManifest,
        native_numeric: NativeNumericBinding | None,
    ) -> tuple[AgentInvocation, BoundSourceTask]:
        """Bind original registered Evidence; no model, acceptance or State write.

        The numeric/source binder is an existing trusted composition dependency,
        never a model field or caller-reported registration flag. Unknown source
        registries remain blocked, including financial text that matches literally.
        """
        bound = self.bind(
            task_ref,
            run_id=run_id,
            role=role,
            access=access,
            memory_bundle=memory_bundle,
            memory_refs=memory_refs,
            model_name=model_name,
        )
        if bound.dispatch_block is not None:
            raise ValueError(bound.dispatch_block)
        if native_numeric is None:
            raise ValueError("G105_NATIVE_NUMERIC_REGISTRATION_REQUIRED")
        if evidence.agent_name != role or not evidence.entries:
            raise ValueError("G105_ORIGINAL_ROLE_EVIDENCE_REQUIRED")
        if self.canonical_evidence is None:
            raise ValueError("G105_R1_CANONICAL_RESOLVER_REQUIRED")
        # Snapshot the original producer's complete typed records, not selected
        # fields certified by a numeric adapter. No new registry or Evidence ID.
        registered = RoleEvidenceManifest.model_validate_json(
            self.canonical_evidence(bound.spec).model_dump_json()
        )
        if registered.agent_name != role:
            raise ValueError("G105_R1_CANONICAL_ROLE_MISMATCH")
        original_by_id = {entry.evidence_id: entry for entry in registered.entries}
        resolved = []
        for supplied in evidence.entries:
            entry = original_by_id.get(supplied.evidence_id)
            if entry is None:
                raise ValueError("G105_R1_CANONICAL_EVIDENCE_UNREGISTERED")
            if supplied.model_dump(mode="json") != entry.model_dump(mode="json"):
                raise ValueError("G105_R1_CANONICAL_AUTHORITY_MISMATCH")
            if entry.as_of is not None and (
                ArtifactRef.utc(entry.as_of) > bound.spec.research_as_of
            ):
                raise ValueError("G105_R1_CANONICAL_EVIDENCE_FUTURE")
            resolved.append(entry)
            matches = [
                r
                for r in bound.source_reads.records
                if (
                    entry.source.document_id == r.proposal.source_ref.document_id
                    and entry.source.provider == r.proposal.source_ref.provider
                    and entry.source.source_url == r.proposal.source_ref.source_url
                    and entry.short_description == r.proposal.evidence_locator.quote
                )
            ]
            if len(matches) != 1:
                raise ValueError("G105_UNREAD_OR_AMBIGUOUS_EVIDENCE")
            # Original native binding verifies exact source/economic population;
            # original grounder also checks any residual literals. No new formula.
            native_numeric.ground(entry.short_description, (entry,))
            if validate_numeric_grounding(
                entry.short_description, (entry,), native_binding=native_numeric
            ).ungrounded_literals:
                raise ValueError("G105_ORIGINAL_NUMERIC_REJECTED")
        context = bound.request.input_context.model_copy(
            update={
                "role_evidence_manifest": RoleEvidenceManifest(
                    agent_name=role, entries=tuple(resolved)
                )
            }
        )
        request = AgentRequest(
            run_id=run_id, agent_name=role, model_name=model_name, input_context=context
        )
        return (
            AgentInvocation(
                run_id=run_id,
                model_name=model_name,
                input_payload=cast(JsonObject, request.model_dump(mode="json")),
            ),
            bound,
        )
