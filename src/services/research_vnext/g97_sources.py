("G97 retained AVGO source projection; no provider or " "Memory fact authority.")

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agents.evidence import numeric_literals
from src.schemas.agents import RoleEvidenceManifestEntry
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
from src.schemas.research_data import (
    DataCapability,
    DataSourceReference,
    ResearchDataBundle,
)
from src.schemas.research_v2_shared import digest
from src.services.document_processing import _chunk_id
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.phase5d_normalization import normalize_authority
from src.services.phase5d_temporal import source_time
from src.services.research_data_bundle import _evidence_item
from src.services.research_vnext.mandate_baseline import source_text, verify_fact
from src.services.research_vnext.public_baseline_closure import (
    recover_announcement,
    validate_announcement_fact,
    validate_c10,
)

G96_COMMIT = "48fed1363dbb33b0ff74171bf320bd9d976aecf6"
BASELINE_SHA = "c49534595ff70d16bcc747804ecee181eb877599b59dfdcddaf32cb38b21dc92"
HANDOFF_SHA = "59b37a359060219be02dcd05e44ce643af28e83eb5805730b4a7225cec623b9d"
ROLES = ("fundamental_analyst", "news_event_analyst")


def read(path: Path) -> Any:
    """Read an immutable retained JSON artifact."""
    return json.loads(path.read_bytes())


def verify_handoff(root: Path) -> dict[str, Any]:
    """Check every original handoff member's bytes, size and path."""
    p = root / "artifacts/g96/G96_W3_W5_HANDOFF.json"
    if blob_hash(p.read_bytes()) != HANDOFF_SHA:
        raise ValueError("G97_HANDOFF_SHA")
    handoff = read(p)
    seen = set()
    for row in handoff["files"]:
        p = root / row["path"]
        if (
            row["path"] in seen
            or p.is_symlink()
            or not p.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("G97_HANDOFF_PATH")
        seen.add(row["path"])
        raw = p.read_bytes()
        if len(raw) != row["bytes"] or blob_hash(raw) != row["sha256"]:
            raise ValueError("G97_HANDOFF_MEMBER:" + row["path"])
    if (
        blob_hash((root / handoff["baseline_path"]).read_bytes()) != BASELINE_SHA
        or handoff["model_calls_authorized"] != 0
    ):
        raise ValueError("G97_BASELINE_SHA_OR_OLD_AUTHORITY")
    return {
        "schema": "G97_INPUT_VERIFICATION_V1",
        "members_verified": len(seen),
        "handoff_sha256": HANDOFF_SHA,
        "baseline_sha256": BASELINE_SHA,
        "g96_model_calls_authorized": 0,
    }


def recover(root: Path, source: dict[str, Any]) -> Any:
    ("Recover the original physical native receipt from the " "local handoff.")
    p = root / source["path"]
    receipt = read(p)["receipt"]
    parts = Path(source["path"]).parts
    families = {
        "g94": "sec-requests",
        "g95": "sec-requests",
        "g96": "corporate-requests",
    }
    if len(parts) != 3 or parts[0] != "artifacts" or parts[1] not in families:
        raise ValueError("G97_UNREGISTERED_SOURCE_GENERATION")
    directory = (
        root.joinpath(*parts[:2])
        / families[parts[1]]
        / f"{receipt['request']['attempt']:02}-native"
    )
    manifest = directory / (receipt["manifest_sha256"] + ".manifest.json")
    if (
        not manifest.is_file()
        or manifest.is_symlink()
        or not manifest.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("G97_EXACT_REGISTERED_RECEIPT_REQUIRED")
    session = read(directory / "session.json")
    return NativePreserver(
        directory,
        provider=session["provider"],
        owner=session["owner"],
        run_id=session["run_id"],
        retention_authority=session["retention_authority"],
        allowed_endpoints=tuple(session["endpoints"]),
        normalization_version=session["normalization_version"],
    ).recover(receipt["manifest_sha256"])


class AVGOSources:
    (
        "Bind exact original text, retained acquisition and "
        "separate publication proof."
    )

    def __init__(self, root: Path, at: datetime) -> None:
        self.root, self.at = root, at
        self.verification = verify_handoff(root)
        self.baseline = read(root / "artifacts/g96/delivery/baseline.json")
        self.sources = self.baseline["sources"]
        self.texts = {
            key: (
                recover_announcement(root, s, at)
                if key == "B"
                else source_text(root, s, at)
            )
            for key, s in self.sources.items()
        }
        self.parents: dict[str, Any] = {}
        self.witnesses: dict[str, SourceDocumentWitnessV2] = {}
        self.native: dict[str, Any] = {}
        self.publication: dict[str, tuple[Any, int] | None] = {}
        self.chunks: list[DocumentChunkProofV2] = []
        self.fact_chunks: dict[str, DocumentChunkProofV2] = {}
        self.entries: list[RoleEvidenceManifestEntry] = []
        self.facts = {f["id"]: f for f in self.baseline["facts"]}
        for key, src in self.sources.items():
            native = recover(root, src)
            self.native[key] = native
            publication = None
            accession = src.get("accession", native.acquisition.revision_id)
            available = None
            if key != "B":
                metadata = read(root / src["SEC_metadata_file"])
                recent = json.loads(metadata["decoded"])["filings"]["recent"]
                indices = [
                    i for i, a in enumerate(recent["accessionNumber"]) if a == accession
                ]
                if len(indices) != 1:
                    raise ValueError("G97_SEC_ACCESSION")
                i = indices[0]
                pub = recover(root, {**src, "path": src["SEC_metadata_file"]})
                available = source_time(recent["acceptanceDateTime"][i])[0]
                if (
                    available is None
                    or available > native.acquisition.observed_at
                    or recent["primaryDocument"][i] != src["url"].rsplit("/", 1)[1]
                ):
                    raise ValueError("G97_SEC_PUBLICATION_OR_DOCUMENT")
                publication = (pub, i)
            self.publication[key] = publication
            did = "sec-" + accession if key != "B" else "g96-joint-" + src["raw_sha256"]
            parent = _evidence_item(
                subject_id="US:AVGO",
                field_path="filings.g97_" + key,
                effective_at=available or native.acquisition.observed_at,
                observed_at=native.acquisition.observed_at,
                value=src["url"].rsplit("/", 1)[1],
                unit=None,
                currency=None,
                source=DataSourceReference(
                    provider_name=native.acquisition.provider,
                    normalized_record_type="RetainedOfficialDocument",
                    normalized_record_key=did,
                    provider_locator=src["url"],
                    source_url=src["url"],
                ),
            )
            self.parents[key] = parent
            self.witnesses[key] = SourceDocumentWitnessV2(
                document_id=did,
                owner_subject="US:AVGO",
                raw_text=self.texts[key],
                raw_document_sha256=blob_hash(self.texts[key].encode()),
                publication_clock_literal=src.get(
                    "acceptance_timestamp_raw", src["publication_date"]
                ),
                repository_created_clock_literal=at.isoformat(),
            )
            for f in self.baseline["facts"]:
                if f["source_id"] != key:
                    continue
                if f["id"] == "C10":
                    validate_c10(self.texts[key], f, src)
                elif key == "B":
                    validate_announcement_fact(self.texts[key], f, src)
                else:
                    verify_fact(f, self.texts[key])
                start, end = f["text_span"]
                chunk = DocumentChunkProofV2(
                    document_id=did,
                    document_owner="US:AVGO",
                    source_evidence_id=parent.evidence_id,
                    source_evidence_hash=parent.content_hash,
                    canonical_id=_chunk_id(did, len(self.chunks), f["quote"]),
                    object_type="filing",
                    chunk_index=len(self.chunks),
                    chunk_text=f["quote"],
                    chunk_text_sha256=blob_hash(f["quote"].encode()),
                    offset_convention="PYTHON_UNICODE_CODEPOINTS_SLICE_STRIP_V1",
                    char_start=start,
                    char_end=end,
                    raw_document_sha256=self.witnesses[key].raw_document_sha256,
                    exact_citation_reference=SourceReference(
                        document_id=did,
                        excerpt_ref=_chunk_id(did, len(self.chunks), f["quote"]),
                        provider=native.acquisition.provider,
                        source_url=src["url"],
                    ),
                    source_identity=SourceIdentityV2(
                        provider=native.acquisition.provider,
                        normalized_record_id=did,
                        source_url=src["url"],
                        raw_receipt_identity=self.witnesses[key].raw_document_sha256,
                        snapshot_identity=self.witnesses[key].raw_document_sha256,
                    ),
                    temporal_provenance=TemporalProvenanceV2(
                        effective_at=available,
                        available_at=available,
                        observed_at=native.acquisition.observed_at,
                        ingested_at=native.ingested_at,
                        clock_evidence_refs=(src["receipt"]["manifest_sha256"],),
                        unavailable_reason=(
                            "Date-only announcement; publication clock UNKNOWN"
                            if available is None
                            else None
                        ),
                    ),
                )
                self.chunks.append(chunk)
                self.fact_chunks[f["id"]] = chunk
                self.entries.append(
                    RoleEvidenceManifestEntry(
                        evidence_id=chunk.canonical_id,
                        evidence_type="document",
                        source=chunk.exact_citation_reference,
                        short_description=chunk.chunk_text,
                        numeric_tokens=numeric_literals(chunk.chunk_text),
                    )
                )
        if len(self.chunks) != 31:
            raise ValueError("G97_FULL_FACT_POPULATION")

    def projection(self) -> dict[str, Any]:
        ("Keep all facts; remove only repeated nested " "source/receipt metadata.")
        return dict(
            schema="G97_FULL_BASELINE_DEDUPLICATED_VIEW_V1",
            baseline_file_sha256=BASELINE_SHA,
            algorithm=(
                "Keep every fact and all fields except nested source; "
                "source metadata appears once, by exact source_id. Native "
                "quote spans refer to normalized Unicode text, not raw "
                "HTTP bytes."
            ),
            sources=self.sources,
            facts=[
                {
                    **{k: v for k, v in f.items() if k != "source"},
                    "evidence_id": self.fact_chunks[f["id"]].canonical_id,
                }
                for f in self.baseline["facts"]
            ],
            limitations={
                k: v for k, v in self.baseline.items() if k not in ("facts", "sources")
            },
            qualified_agent_memory=[],
        )

    def bundle(self, cutoff: datetime) -> ResearchDataBundle:
        (
            "Populate retained documents only; all other Data Plane "
            "slots stay missing."
        )
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
                    policy_name="g97-retained",
                    policy_version="1",
                    reason="Frozen G96 sources; no current-source completeness claim",
                ),
                quality=(
                    dict(
                        status="pass",
                        observation_count=4,
                        source_count=4,
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
                requested_field_count=4 if present else 0,
                available_field_count=4 if present else 0,
                items=tuple(self.parents.values()) if present else (),
            )
        identity = digest((BASELINE_SHA, cutoff))
        return ResearchDataBundle.model_validate(
            dict(
                bundle_id="rdb_" + identity[:24],
                input_fingerprint=identity,
                asset_id="US:AVGO",
                as_of=cutoff,
                window_start=min(
                    datetime.fromisoformat(s["publication_date"]).date()
                    for s in self.sources.values()
                ),
                window_end=cutoff.date(),
                dataset_version="g97-retained-g96-v1",
                **sections,
            )
        )

    def authorities(self, envelope: PitEvidenceInput) -> PitEvidenceInput:
        (
            "Use original Phase5D policy; unknown B publication "
            "remains retrieval-only."
        )
        values = []
        for node in envelope.closure.nodes:
            key = next(
                k
                for k, p in self.parents.items()
                if (
                    node.document_payload
                    and node.document_payload.source_evidence_id == p.evidence_id
                )
                or node.canonical_id == p.evidence_id
            )
            src, native = self.sources[key], self.native[key]
            pub = self.publication[key]
            revision = src.get("accession", native.acquisition.revision_id)
            doc_receipt = AcquisitionReceipt.model_validate(
                {
                    **native.acquisition.model_dump(exclude={"content_identity"}),
                    "revision_id": revision,
                }
            )
            extraction = DocumentExtraction(
                receipt=doc_receipt,
                document_id=self.witnesses[key].document_id,
                extraction="HTML_TEXT_V1",
                extracted_text_sha256=self.witnesses[key].raw_document_sha256,
                ingested_at=native.ingested_at,
                materialized_at=self.at,
                chunk_materialized_at=self.at,
            )
            if pub is not None:
                publication, i = pub
                receipt = AcquisitionReceipt.model_validate(
                    {
                        **publication.acquisition.model_dump(
                            exclude={"content_identity"}
                        ),
                        "revision_id": revision,
                    }
                )
                values.append(
                    normalize_authority(
                        envelope,
                        node,
                        receipt=receipt,
                        policy_id="SEC_ACCESSION_EXPLICIT_OFFSET_V1",
                        revision_locator=f"/filings/recent/accessionNumber/{i}",
                        primary_document_locator=f"/filings/recent/primaryDocument/{i}",
                        canonical_value_locator=(
                            f"/filings/recent/primaryDocument/{i}"
                            if node.structured_payload
                            else None
                        ),
                        ingested_at=publication.ingested_at,
                        materialized_at=self.at,
                        document=extraction if node.document_payload else None,
                        mode="HISTORICAL_REPLAY",
                    )
                )
            else:
                values.append(
                    normalize_authority(
                        envelope,
                        node,
                        receipt=doc_receipt,
                        policy_id="DOCUMENT_RETRIEVAL_WITNESS_V1",
                        revision_locator="RETRIEVAL_ONLY",
                        ingested_at=native.ingested_at,
                        materialized_at=self.at,
                        document=extraction if node.document_payload else None,
                        mode="HISTORICAL_REPLAY",
                    )
                )
        return PitEvidenceInput.model_validate(
            {
                **envelope.model_dump(exclude={"content_identity"}),
                "authorities": tuple(values),
            }
        )
