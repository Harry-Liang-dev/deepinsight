"""Offline normalization-time receipt plumbing for future reviewed source bytes.

The caller supplies actual acquisition/ingestion/materialization clocks. This
module never fetches sources, infers publication from retrieval, or upgrades an
old document. Receipts are content-addressed and exclusively created.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.schemas.evidence_closure import ClosureNodeV2
from src.schemas.phase5d_authority import authority
from src.schemas.phase5d_evidence import (
    AcquisitionReceipt,
    DocumentExtraction,
    NormalizationReceipt,
    PitEvidenceInput,
    PolicyId,
    SourceClock,
    TemporalAuthority,
)
from src.schemas.research_data_quality import quality_hash
from src.services.data_normalization import NormalizedDocument
from src.services.phase5d_temporal import (
    parser_identity,
    pointer,
    receipt_bytes,
    source_time,
)


def retain_response(
    directory: Path,
    *,
    body: bytes,
    provider: str,
    endpoint: str,
    owner: str,
    source_run_id: str,
    revision_id: str,
    observed_at: datetime,
    content_encoding: Literal["identity", "gzip", "deflate"] = "identity",
) -> AcquisitionReceipt:
    """Freeze exact returned bytes without credentials, before any source parsing."""
    if "?" in endpoint or "@" in endpoint:
        raise ValueError("CREDENTIAL_FREE_SOURCE_ENDPOINT_REQUIRED")
    digest = hashlib.sha256(body).hexdigest()
    receipt = AcquisitionReceipt(
        artifact_id="source_" + digest,
        provider=provider,
        endpoint=endpoint,
        owner=owner,
        source_run_id=source_run_id,
        revision_id=revision_id,
        body_base64=base64.b64encode(body).decode(),
        body_sha256=digest,
        size_bytes=len(body),
        content_encoding=content_encoding,
        observed_at=observed_at,
    )
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in (
        (digest + ".raw", body),
        (receipt.content_identity + ".json", receipt.model_dump_json().encode()),
    ):
        path = directory / name
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("IMMUTABLE_RECEIPT_COLLISION")
        else:
            with path.open("xb") as stream:
                stream.write(data)
    return receipt


def normalize_authority(
    envelope: PitEvidenceInput,
    node: ClosureNodeV2,
    *,
    receipt: AcquisitionReceipt,
    policy_id: PolicyId,
    revision_locator: str,
    ingested_at: datetime,
    materialized_at: datetime,
    primary_document_locator: str | None = None,
    canonical_value_locator: str | None = None,
    document: DocumentExtraction | None = None,
    mode: Literal["LIVE_ACQUISITION", "HISTORICAL_REPLAY"] = "LIVE_ACQUISITION",
) -> TemporalAuthority:
    """Retain raw field literals and actual clocks; leave unsupported precision null."""
    policies = authority("policies")["policies"]
    policy = next(p for p in policies if p["policy_id"] == policy_id)
    payload = (
        json.loads(receipt_bytes(receipt))
        if policy_id != "DOCUMENT_RETRIEVAL_WITNESS_V1"
        else None
    )
    specs: tuple[
        tuple[
            str,
            Literal[
                "SEC_ACCESSION_ACCEPTANCE",
                "NEWS_PUBLICATION",
                "RETURNED_REVISION_AVAILABILITY",
            ],
        ],
        ...,
    ]
    if policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1":
        prefix, index = revision_locator.rsplit("/accessionNumber/", 1)
        specs = ((prefix + "/acceptanceDateTime/" + index, "SEC_ACCESSION_ACCEPTANCE"),)
    elif policy_id == "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1":
        prefix = revision_locator.removesuffix("/id")
        specs = (
            (prefix + "/created_at", "NEWS_PUBLICATION"),
            (prefix + "/updated_at", "RETURNED_REVISION_AVAILABILITY"),
        )
    elif policy_id == "DOCUMENT_RETRIEVAL_WITNESS_V1":
        specs = ()
    else:
        raise ValueError("DERIVED_AUTHORITY_REQUIRES_OPERAND_RECEIPTS")
    clocks = []
    for locator, semantics in specs:
        literal = pointer(payload, locator)
        if not isinstance(literal, str):
            raise ValueError("SOURCE_TIMESTAMP_NOT_LITERAL")
        normalized, precision, zone = source_time(literal)
        clocks.append(
            SourceClock.model_validate(
                dict(
                    field_locator=locator,
                    literal=literal,
                    semantics=semantics,
                    native_zone=zone,
                    precision=precision,
                    normalized_at=normalized,
                )
            )
        )
    normal = NormalizationReceipt(
        acquisition_identity=receipt.content_identity,
        parser_build_identity=parser_identity(),
        ingested_at=ingested_at,
        materialized_at=materialized_at,
        revision_locator=revision_locator,
        revision_literal=receipt.revision_id,
        primary_document_locator=primary_document_locator,
        primary_document_literal=(
            str(pointer(payload, primary_document_locator))
            if primary_document_locator
            else None
        ),
        canonical_value_locator=canonical_value_locator,
        clocks=tuple(clocks),
    )
    available = (
        max(c.normalized_at for c in clocks if c.normalized_at is not None)
        if clocks and all(c.normalized_at is not None for c in clocks)
        else None
    )
    binding = envelope.closure.binding
    return TemporalAuthority(
        evidence_id=node.canonical_id,
        namespace=node.namespace,
        object_type=node.object_type,
        content_hash=node.content_hash,
        owner=node.owner_subject,
        consumer_asset=binding.consumer_asset,
        capture_id=binding.capture_id,
        consumer_run_id=binding.source_run_id,
        data_bundle_id=binding.data_bundle_id,
        usage_identity=binding.state_episode_usage_binding,
        research_as_of=envelope.original_input.data_bundle.as_of,
        generated_at=envelope.original_input.generated_at,
        mode=mode,
        policy_id=policy_id,
        policy_reference=f"policy://{policy_id}/1.0.0",
        policy_identity=quality_hash(policy),
        acquisition=receipt,
        normalization=normal,
        document=document,
        available_at=available,
    )


def normalize_document_response(
    *,
    publication_receipt: AcquisitionReceipt,
    document_receipt: AcquisitionReceipt,
    policy_id: Literal[
        "SEC_ACCESSION_EXPLICIT_OFFSET_V1",
        "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1",
        "DOCUMENT_RETRIEVAL_WITNESS_V1",
    ],
    revision_locator: str,
    document_id: str,
    title: str,
    ingested_at: datetime,
    materialized_at: datetime,
    chunk_materialized_at: datetime,
    content_locator: str | None = None,
    primary_document_locator: str | None = None,
) -> tuple[NormalizedDocument, DocumentExtraction]:
    """Normalize fresh exact document bytes through the existing canonical path.

    Returned provenance travels with the canonical document through chunking;
    the bridge attaches it to TemporalAuthority, never substitutes legacy SQL
    clocks. Date-only publication is retained with a null canonical clock.
    """
    from typing import cast

    from src.adapters.providers import _html_to_text
    from src.models.types import JsonObject
    from src.services.data_normalization import DataNormalizer

    raw = receipt_bytes(document_receipt).decode("utf-8")
    if (
        document_receipt.owner != publication_receipt.owner
        or document_receipt.provider != publication_receipt.provider
        or document_receipt.revision_id != publication_receipt.revision_id
    ):
        raise ValueError("DOCUMENT_SOURCE_REVISION_OWNER")
    if (
        not max(publication_receipt.observed_at, document_receipt.observed_at)
        <= ingested_at
        <= materialized_at
        <= chunk_materialized_at
    ):
        raise ValueError("DOCUMENT_NORMALIZATION_CHRONOLOGY")
    payload = (
        json.loads(receipt_bytes(publication_receipt))
        if policy_id != "DOCUMENT_RETRIEVAL_WITNESS_V1"
        else None
    )
    publication = None
    literals = []
    if policy_id == "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1":
        if (
            publication_receipt != document_receipt
            or content_locator != revision_locator.removesuffix("/id") + "/content"
        ):
            raise ValueError("NEWS_DOCUMENT_REVISION_BINDING")
        text = _html_to_text(str(pointer(payload, content_locator)))
        prefix = revision_locator.removesuffix("/id")
        literals = [
            str(pointer(payload, prefix + "/created_at")),
            str(pointer(payload, prefix + "/updated_at")),
        ]
        publication = source_time(literals[0])[0]
        revision_time = source_time(literals[1])[0]
        if (
            revision_time is not None
            and publication is not None
            and revision_time < publication
        ):
            raise ValueError("NEWS_REVISION_BEFORE_PUBLICATION")
        extraction = "JSON_HTML_TEXT_V1"
    else:
        text = _html_to_text(raw)
        extraction = "HTML_TEXT_V1"
        if policy_id == "SEC_ACCESSION_EXPLICIT_OFFSET_V1":
            prefix, index = revision_locator.rsplit("/accessionNumber/", 1)
            if (
                primary_document_locator != prefix + "/primaryDocument/" + index
                or publication_receipt.revision_id.replace("-", "")
                not in document_receipt.endpoint
                or not document_receipt.endpoint.endswith(
                    "/" + str(pointer(payload, primary_document_locator))
                )
            ):
                raise ValueError("SEC_DOCUMENT_OWN_ACCESSION")
            literals = [str(pointer(payload, prefix + "/acceptanceDateTime/" + index))]
            publication = source_time(literals[0])[0]
    if (
        payload is not None
        and str(pointer(payload, revision_locator)) != publication_receipt.revision_id
    ):
        raise ValueError("DOCUMENT_PUBLICATION_REVISION_BINDING")
    metadata = {
        "phase5d_policy": policy_id + "/1.0.0",
        "publication_receipt_identity": publication_receipt.content_identity,
        "document_receipt_identity": document_receipt.content_identity,
        "source_clock_literals": literals,
        "ingested_at": ingested_at.isoformat(),
        "materialized_at": materialized_at.isoformat(),
        "publication_proof_missing": publication is None,
    }
    normalized = DataNormalizer().normalize_document(
        document_receipt.provider,
        cast(
            JsonObject,
            {
                "document_id": document_id,
                "asset_id": document_receipt.owner,
                "market": document_receipt.owner.split(":", 1)[0],
                "doc_type": (
                    "news"
                    if policy_id == "ALPACA_NEWS_REVISION_EXPLICIT_OFFSET_V1"
                    else "filing"
                ),
                "title": title,
                "raw_text": text,
                "publish_ts": publication.isoformat() if publication else None,
                "source_url": document_receipt.endpoint,
                "metadata": metadata,
            },
        ),
        received_at=materialized_at,
    )
    proof = DocumentExtraction.model_validate(
        dict(
            receipt=document_receipt,
            document_id=normalized.record.document_id,
            extraction=extraction,
            text_locator=content_locator,
            extracted_text_sha256=normalized.record.checksum_sha256,
            ingested_at=ingested_at,
            materialized_at=materialized_at,
            chunk_materialized_at=chunk_materialized_at,
        )
    )
    return normalized, proof
