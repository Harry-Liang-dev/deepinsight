"""G90 exact AAPL source normalization into existing Phase5D document contracts.

Original NativeReceipts are immutable. Accession-selected acquisition views are
explicit normalization artifacts over the same bytes/clocks, not new HTTP receipts.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from src.schemas.common import SourceReference
from src.schemas.evidence_closure import (
    DocumentChunkProofV2,
    SourceDocumentWitnessV2,
    SourceIdentityV2,
    TemporalProvenanceV2,
)
from src.schemas.phase5d_evidence import (
    AcquisitionReceipt,
    DocumentExtraction,
    PitEvidenceInput,
)
from src.schemas.research_data import DataSourceReference, ResearchDataBundle
from src.schemas.research_v2_shared import canonical, digest
from src.services.document_processing import _chunk_id
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.phase5d_normalization import normalize_authority
from src.services.phase5d_temporal import receipt_bytes, source_time
from src.services.research_data_bundle import _evidence_item
from src.services.sec_native_financial import (
    NativeFinancialProof,
    SECRegistration,
    extract_financial_proof,
)


class NativeSource:
    """Pinned retained source; independently re-extract each original native fact."""

    def __init__(self, root: Path, recovery: Path, at: datetime) -> None:
        self.at = at
        manifest = json.loads(
            (root / "contracts/g89-real-memory-preflight-v1.json").read_bytes()
        )
        if (
            blob_hash(
                (root / "contracts/g89-real-memory-preflight-v1.json").read_bytes()
            )
            != "c53bc7e495830e23b304fa16106d9903e1e7fc9a52ade5f69e74b18d1d98bb5f"
        ):
            raise ValueError("G90_G89_MANIFEST")
        prefix = "artifacts/g89/preflight-v2/"
        for row in manifest["complete_inventory"]:
            if (
                row["path"].startswith(prefix)
                and blob_hash((root / row["path"]).read_bytes()) != row["sha256"]
            ):
                raise ValueError("G90_G89_SOURCE_BYTES")
        base = root / prefix
        audit = json.loads((base / "source-audit.json").read_bytes())
        self.registration = SECRegistration.model_validate_json(
            (base / "sec-registration.json").read_bytes()
        )
        r = self.registration
        if r.owner != "US:AAPL" or r.accession != "0000320193-26-000020":
            raise ValueError("G90_EXACT_FILING")
        shutil.copytree(base / "native-recovery", recovery)
        s = json.loads((recovery / "session.json").read_bytes())
        self.store = NativePreserver(
            recovery,
            provider=s["provider"],
            owner=s["owner"],
            run_id=s["run_id"],
            retention_authority=s["retention_authority"],
            allowed_endpoints=tuple(s["endpoints"]),
            normalization_version=s["normalization_version"],
        )
        for key in (r.manifest, r.submissions_manifest):
            self.store.recover(key)
        self.document = self.store.verify(r.manifest)
        self.submissions = self.store.verify(r.submissions_manifest)
        self.raw = receipt_bytes(self.document.acquisition).decode("utf-8")
        raw_meta = json.loads(receipt_bytes(self.submissions.acquisition))
        recent = raw_meta["filings"]["recent"]
        self.index = recent["accessionNumber"].index(r.accession)
        available, _, _ = source_time(recent["acceptanceDateTime"][self.index])
        if (
            available is None
            or not available
            <= self.document.acquisition.observed_at
            <= self.document.ingested_at
            <= at
        ):
            raise ValueError("G90_SOURCE_CLOCK")
        self.available: datetime = available
        self.proofs = []
        for row in audit["native_proofs"]:
            p = NativeFinancialProof.model_validate_json(canonical(row["proof"]))
            actual = extract_financial_proof(
                self.store,
                r,
                registered_identity=digest(r),
                fact_id=p.fact_id,
                expected=p.context,
            )
            if actual != p or digest(p) != row["identity"]:
                raise ValueError("G90_NATIVE_DRIFT")
            self.proofs.append(p)
        # Accession is a selected logical filing revision, not the HTTP body revision.
        self.pub_view = AcquisitionReceipt.model_validate(
            {
                **self.submissions.acquisition.model_dump(exclude={"content_identity"}),
                "revision_id": r.accession,
            }
        )
        self.doc_view = AcquisitionReceipt.model_validate(
            {
                **self.document.acquisition.model_dump(exclude={"content_identity"}),
                "revision_id": r.accession,
            }
        )
        self.document_id = "sec-" + r.accession
        self.parent = _evidence_item(
            subject_id=r.owner,
            field_path="filings.primary_document",
            effective_at=self.available,
            observed_at=self.submissions.acquisition.observed_at,
            value=r.primary_document,
            unit=None,
            currency=None,
            source=DataSourceReference(
                provider_name="sec_edgar",
                normalized_record_type="SECNativeFiling",
                normalized_record_key=self.document_id,
                provider_locator=r.target.urls[0],
                source_url=r.document_url,
            ),
        )
        self.witness = SourceDocumentWitnessV2(
            document_id=self.document_id,
            owner_subject=r.owner,
            raw_text=self.raw,
            raw_document_sha256=blob_hash(self.raw.encode()),
            publication_clock_literal=recent["acceptanceDateTime"][self.index],
            repository_created_clock_literal=at.isoformat(),
        )
        self.chunks: list[DocumentChunkProofV2] = []
        self.proof_chunks: dict[str, tuple[str, ...]] = {}
        segments: dict[tuple[int, int], str] = {}
        for p in self.proofs:
            ids = []
            for tag, ident in [
                ("ix:nonFraction", p.fact_id),
                ("xbrli:context", p.context.context_id),
                ("xbrli:unit", p.context.unit_id),
            ]:
                matches = list(
                    re.finditer(
                        r"<"
                        + re.escape(tag)
                        + r'\b[^>]*\bid="'
                        + re.escape(ident)
                        + r'"[^>]*>.*?</'
                        + re.escape(tag)
                        + r">",
                        self.raw,
                        re.S,
                    )
                )
                if len(matches) != 1:
                    raise ValueError("G90_EXACT_NATIVE_SPAN:" + ident)
                start, end = matches[0].span()
                if (start, end) not in segments:
                    text = self.raw[start:end]
                    i = len(self.chunks)
                    key = _chunk_id(self.document_id, i, text)
                    chunk = DocumentChunkProofV2(
                        document_id=self.document_id,
                        document_owner=r.owner,
                        source_evidence_id=self.parent.evidence_id,
                        source_evidence_hash=self.parent.content_hash,
                        canonical_id=key,
                        object_type="filing",
                        chunk_index=i,
                        chunk_text=text,
                        chunk_text_sha256=blob_hash(text.encode()),
                        offset_convention="PYTHON_UNICODE_CODEPOINTS_SLICE_STRIP_V1",
                        char_start=start,
                        char_end=end,
                        raw_document_sha256=self.witness.raw_document_sha256,
                        exact_citation_reference=SourceReference(
                            document_id=self.document_id,
                            excerpt_ref=key,
                            provider="sec_edgar",
                            source_url=r.document_url,
                        ),
                        source_identity=SourceIdentityV2(
                            provider="sec_edgar",
                            normalized_record_id=self.document_id,
                            source_url=r.document_url,
                            raw_receipt_identity=self.witness.raw_document_sha256,
                            snapshot_identity=self.witness.raw_document_sha256,
                        ),
                        temporal_provenance=TemporalProvenanceV2(
                            effective_at=self.available,
                            available_at=self.available,
                            observed_at=self.document.acquisition.observed_at,
                            ingested_at=self.document.ingested_at,
                            clock_evidence_refs=(r.manifest, r.submissions_manifest),
                        ),
                    )
                    self.chunks.append(chunk)
                    segments[(start, end)] = key
                ids.append(segments[(start, end)])
            self.proof_chunks[digest(p)] = tuple(ids)
        self.extraction = DocumentExtraction(
            receipt=self.doc_view,
            document_id=self.document_id,
            extraction="UTF8_IDENTITY_V1",
            extracted_text_sha256=self.witness.raw_document_sha256,
            ingested_at=self.document.ingested_at,
            materialized_at=at,
            chunk_materialized_at=at,
        )

    def manifest(self) -> dict[str, Any]:
        """Expose normalization lineage without altering either original receipt."""
        return dict(
            schema="G90_RETAINED_NATIVE_SOURCE_V1",
            registration=self.registration,
            proofs=self.proofs,
            original_receipts=[self.submissions, self.document],
            selected_accession_views=[self.pub_view, self.doc_view],
            selection_locator=f"/filings/recent/accessionNumber/{self.index}",
            new_http_requests=0,
            original_publication_assertion=None,
            verified_sec_acceptance_at=self.available,
            normalization_at=self.at,
            scope="DEVELOPMENT_ONLY_NOT_FORMAL_PIT",
            chunks=self.chunks,
        )

    def bundle(self, cutoff: datetime) -> ResearchDataBundle:
        """Create a one-filing bundle; every other capability remains missing."""
        from src.schemas.research_data import DataCapability

        sections = {}
        for cap in DataCapability:
            present = cap.value == "filings"
            sections[cap.value] = dict(
                capability=cap,
                status="present" if present else "missing",
                as_of=cutoff,
                freshness=dict(
                    status="unknown",
                    evaluated_at=cutoff,
                    policy_name="g90-retained",
                    policy_version="1",
                    reason="Retained filing only; no claim of current fundamentals",
                ),
                quality=(
                    dict(
                        status="pass",
                        observation_count=1,
                        source_count=1,
                        completeness_ratio=1,
                        validity_ratio=1,
                        lineage_coverage_ratio=1,
                        temporal_coverage_ratio=1,
                    )
                    if present
                    else dict(
                        status="unknown",
                        observation_count=0,
                        source_count=0,
                        reason="Not acquired",
                    )
                ),
                requested_field_count=1 if present else 0,
                available_field_count=1 if present else 0,
                items=(self.parent,) if present else (),
            )
        identity = digest((self.manifest(), cutoff))
        return ResearchDataBundle.model_validate(
            dict(
                bundle_id="rdb_" + identity[:24],
                input_fingerprint=identity,
                asset_id="US:AAPL",
                as_of=cutoff,
                window_start=self.available.date(),
                window_end=cutoff.date(),
                dataset_version="g90-native-v1",
                **sections,
            )
        )

    def authorities(self, envelope: PitEvidenceInput) -> PitEvidenceInput:
        """Invoke original Phase5D normalization on actual retained bytes and clocks."""
        values = []
        for node in envelope.closure.nodes:
            values.append(
                normalize_authority(
                    envelope,
                    node,
                    receipt=self.pub_view,
                    policy_id="SEC_ACCESSION_EXPLICIT_OFFSET_V1",
                    revision_locator=f"/filings/recent/accessionNumber/{self.index}",
                    primary_document_locator=f"/filings/recent/primaryDocument/{self.index}",
                    canonical_value_locator=(
                        f"/filings/recent/primaryDocument/{self.index}"
                        if node.structured_payload
                        else None
                    ),
                    ingested_at=self.submissions.ingested_at,
                    materialized_at=self.at,
                    document=self.extraction if node.document_payload else None,
                    mode="HISTORICAL_REPLAY",
                )
            )
        return PitEvidenceInput.model_validate(
            {
                **envelope.model_dump(exclude={"content_identity"}),
                "authorities": tuple(values),
            }
        )

    def expected_text(self, p: NativeFinancialProof) -> str:
        """Compare prospective grammar; never render a model answer."""
        c = p.context
        return (
            f"{c.concept.rsplit(chr(125),1)[-1]} = {c.lexical_value} USD millions; "
            f'period={c.period_kind}; start={c.start or "none"}; end={c.end}.'
        )

    def verify_claims(
        self, claims: tuple[Any, ...], *, memory_id: str | None = None
    ) -> None:
        """Add a strict native compatibility check; never edit model-selected facts."""
        if memory_id is None and (
            len(claims) != 3
            or {c.claim_text for c in claims}
            != {self.expected_text(p) for p in self.proofs}
        ):
            raise ValueError("G90_FROZEN_THREE_FACT_TASK_POPULATION")
        for c in claims:
            found = [p for p in self.proofs if c.claim_text == self.expected_text(p)]
            if len(found) != 1:
                raise ValueError("G90_MODEL_NATIVE_VALUE_UNIT_PERIOD_OR_CONCEPT")
            p = found[0]
            expected = {memory_id} if memory_id else set(self.proof_chunks[digest(p)])
            if set(c.evidence_ids) != expected:
                raise ValueError("G90_MODEL_NATIVE_CITATION")
            if any(s.document_id != self.document_id for s in c.source_references):
                raise ValueError("G90_MODEL_NATIVE_DOCUMENT")
