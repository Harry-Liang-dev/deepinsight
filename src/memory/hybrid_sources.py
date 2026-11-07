"""Source locator adapter over existing NativePreserver, not a new registry."""

from __future__ import annotations

import gzip
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from src.adapters.providers import _html_to_text
from src.memory.hybrid_contracts import (
    NarrativeProposal,
    NarrativeRecord,
    SemanticReviewFixture,
)
from src.schemas.common import SourceReference
from src.services.native_preservation import NativePreserver, blob_hash


@dataclass(frozen=True)
class RegisteredNarrativeSource:
    """Trusted composition projection of an existing registered source/receipt."""

    store: NativePreserver
    manifest_identity: str
    source_ref: SourceReference
    raw_sha256: str
    subject: str
    publisher: str
    source_type: Literal[
        "SEC_FILING", "OFFICIAL_RELEASE", "RESEARCH_REPORT", "COMMUNITY", "EVENT"
    ]
    format: Literal["HTML", "UTF8_TEXT", "PDF_UNVERIFIED"]
    relevant_period: str | None
    published_at: datetime | None
    publication_literal: str | None
    origin: Literal["REAL_RETAINED_SOURCE", "SYNTHETIC_ENGINEERING_FIXTURE"]


class NativeLocatorResolver:
    """Resolve only registered IDs; recheck original bytes on every admission/read."""

    def __init__(self, sources: Mapping[str, RegisteredNarrativeSource]) -> None:
        self._sources = dict(sources)

    def validate(
        self, p: NarrativeProposal, review: SemanticReviewFixture | None = None
    ) -> NarrativeRecord:
        """Prove attribution, not economic truth; unknown semantics stay pending."""
        s = self._sources[p.source_ref.document_id or ""]
        n = s.store.recover(s.manifest_identity)
        raw = (s.store.directory / (n.acquisition.body_sha256 + ".raw")).read_bytes()
        if (
            p.source_ref != s.source_ref
            or p.source_sha256 != s.raw_sha256
            or blob_hash(raw) != s.raw_sha256
            or n.status_code != 200
            or n.acquisition.owner != s.subject
            or n.acquisition.endpoint != s.source_ref.source_url
        ):
            raise ValueError("G100_SOURCE_IDENTITY")
        if (
            p.subject != s.subject
            or p.attribution != s.publisher
            or p.relevant_period != s.relevant_period
        ):
            raise ValueError("G100_SUBJECT_ATTRIBUTION_PERIOD")
        available = max(n.ingested_at, n.acquisition.observed_at)
        if (
            max(available, s.published_at or available) > p.research_as_of
            or p.created_at < p.research_as_of
        ):
            raise ValueError("G100_FUTURE_SOURCE")
        body = gzip.decompress(raw) if n.acquisition.content_encoding == "gzip" else raw
        loc = p.evidence_locator
        exact = False
        if loc.kind in ("NORMALIZED_UNICODE", "RAW_UTF8_BYTES"):
            if (
                s.format == "PDF_UNVERIFIED"
                or loc.start is None
                or loc.end is None
                or loc.end <= loc.start
                or loc.page is not None
            ):
                raise ValueError("G100_LOCATOR_SPACE")
            text = _html_to_text(body.decode()) if s.format == "HTML" else body.decode()
            if loc.kind == "NORMALIZED_UNICODE":
                if loc.normalization_sha256 != blob_hash(text.encode()):
                    raise ValueError("G100_NORMALIZATION_IDENTITY")
                if loc.end > len(text) or text[loc.start : loc.end] != loc.quote:
                    raise ValueError("G100_LOCATOR_QUOTE")
            else:
                if (
                    loc.normalization_sha256 is not None
                    or loc.end > len(body)
                    or body[loc.start : loc.end].decode() != loc.quote
                ):
                    raise ValueError("G100_RAW_LOCATOR")
            exact = True
        elif loc.kind == "PDF_PAGE_TEXT" and s.format != "PDF_UNVERIFIED":
            raise ValueError("G100_UNREGISTERED_PAGE_EXTRACTION")
        if not loc.quote.strip():
            raise ValueError("G100_EMPTY_QUOTE")
        authority: Literal[
            "SOURCE_ATTRIBUTED_STATEMENT", "NONE", "REVIEWED_PARAPHRASE_FIXTURE"
        ] = "NONE"
        support: Literal[
            "EXACT_SOURCE_LOCATOR", "LOCATOR_PENDING", "SOURCE_LINK_ONLY"
        ] = ("EXACT_SOURCE_LOCATOR" if exact else "LOCATOR_PENDING")
        status: Literal[
            "SOURCE_BINDING_VERIFIED",
            "PENDING_LOCATOR",
            "PENDING_SEMANTIC_REVIEW",
            "UNVERIFIED_RESEARCH",
            "ENGINEERING_REVIEW_FIXTURE",
        ] = "PENDING_LOCATOR"
        if exact:
            if p.kind == "DIRECT_SOURCE":
                if p.statement != loc.quote:
                    raise ValueError("G100_DIRECT_QUOTE_CHANGED")
                authority = "SOURCE_ATTRIBUTED_STATEMENT"
                status = "SOURCE_BINDING_VERIFIED"
            elif p.kind == "PARAPHRASE":
                status = "PENDING_SEMANTIC_REVIEW"
                support = "SOURCE_LINK_ONLY"
            else:
                status = "UNVERIFIED_RESEARCH"
                support = "SOURCE_LINK_ONLY"
        if review is not None:
            if (
                s.origin != "SYNTHETIC_ENGINEERING_FIXTURE"
                or review.proposal_sha256 != p.sha256
                or not review.faithful
                or p.kind != "PARAPHRASE"
                or not exact
            ):
                raise ValueError("G100_REAL_SEMANTIC_AUTHORITY_NOT_PROVIDED")
            authority = "REVIEWED_PARAPHRASE_FIXTURE"
            status = "ENGINEERING_REVIEW_FIXTURE"
        return NarrativeRecord(
            proposal=p,
            source_receipt_identity=s.manifest_identity,
            source_origin=s.origin,
            publisher=s.publisher,
            source_type=s.source_type,
            published_at=s.published_at,
            publication_literal=s.publication_literal,
            acquired_at=n.ingested_at,
            source_available_at=available,
            fact_authority=authority,
            support_status=support,
            review_status=status,
            research_status=(
                "UNVERIFIED_RESEARCH"
                if p.kind == "RESEARCH_HYPOTHESIS"
                else "NOT_AN_AGENT_RESULT"
            ),
            review_due_at=p.created_at
            + timedelta(
                days={"SHORT": 7, "MEDIUM": 90, "LONG": 365}[p.retention_horizon]
            ),
        )
