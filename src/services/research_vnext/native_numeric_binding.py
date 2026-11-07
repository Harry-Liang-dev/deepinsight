"""G92 opt-in native scale consumption. No model-provided authority is accepted.

Uses the existing SEC parser/receipt validator and G91 typed claim validator.
This is a composition dependency, never a field in model input or model output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from src.agents.numeric_grounding import (
    NumericEvidenceEntry,
    NumericGroundingMatch,
    NumericSemanticKind,
)
from src.agents.numeric_tokens import numeric_literals
from src.schemas.agents import ClaimEvidenceBinding
from src.schemas.research_v2_shared import digest
from src.services.native_preservation import blob_hash
from src.services.phase5d_temporal import receipt_bytes
from src.services.research_vnext.real_native_source import NativeSource
from src.services.research_vnext.typed_financial_admission import MONEY, extract
from src.services.sec_native_financial import (
    NativeFinancialProof,
    _Tree,
    extract_financial_proof,
)


@dataclass(frozen=True)
class VerifiedNativeNumericAspect:
    """Existing proof plus exact byte locator and explicit transform provenance."""

    schema: str
    issuer: str
    accession: str
    evidence_ids: tuple[str, ...]
    raw_sha256: str
    receipt_identity: str
    registration: str
    proof: NativeFinancialProof
    char_span: tuple[int, int]
    byte_span: tuple[int, int]
    raw_node_sha256: str
    format_literal: str | None
    format_qname: str | None
    scale_explicit: bool
    source_clocks: dict[str, Any]


def scaled_decimal(lexical: str, scale: int, sign: str) -> Decimal:
    """Exact supported finite native normalization; never scale arbitrary text."""
    if (
        not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", lexical)
        or len(lexical) > 48
        or type(scale) is not int
        or abs(scale) > 18
        or sign not in ("", "-")
    ):
        raise ValueError("G92_NATIVE_NUMERIC_ATTRIBUTES")
    with localcontext() as ctx:
        ctx.prec = 80
        value = Decimal(lexical.replace(",", "")).scaleb(scale)
        return -value if sign else value


class NativeScaleBinding:
    """Pinned native source; every consumption rechecks bytes, nodes and scope."""

    def __init__(self, source: NativeSource) -> None:
        self.source = source
        self._pin = digest(source.manifest())
        self.aspects = self._verify()

    def _verify(self) -> tuple[VerifiedNativeNumericAspect, ...]:
        s = self.source
        if digest(s.manifest()) != self._pin:
            raise ValueError("G92_NATIVE_SOURCE_MUTATED")
        raw = receipt_bytes(s.store.verify(s.registration.manifest).acquisition)
        if blob_hash(raw) != s.registration.raw_sha256 or raw.decode() != s.raw:
            raise ValueError("G92_RAW_BYTES_CHANGED")
        chunks = {c.canonical_id: c for c in s.chunks}
        tree = _Tree(s.raw)
        aspects = []
        for proof in s.proofs:
            checked = extract_financial_proof(
                s.store,
                s.registration,
                registered_identity=digest(s.registration),
                fact_id=proof.fact_id,
                expected=proof.context,
            )
            if checked != proof:
                raise ValueError("G92_NATIVE_PROOF_CHANGED")
            ids = s.proof_chunks[digest(proof)]
            if len(ids) != 3:
                raise ValueError("G92_FACT_CONTEXT_UNIT_CLOSURE")
            for key in ids:
                c = chunks[key]
                if (
                    s.raw[c.char_start : c.char_end] != c.chunk_text
                    or blob_hash(c.chunk_text.encode()) != c.chunk_text_sha256
                    or c.raw_document_sha256 != blob_hash(raw)
                    or c.document_owner != s.registration.owner
                    or c.document_id != s.document_id
                ):
                    raise ValueError("G92_NATIVE_SPAN_BINDING")
            c = chunks[ids[0]]
            # Identity from the original parser AND the exact visible native span.
            if not re.search(r'\bid="' + re.escape(proof.fact_id) + r'"', c.chunk_text):
                raise ValueError("G92_NATIVE_FACT_SPAN")
            for key, native_id in zip(
                ids[1:], (proof.context.context_id, proof.context.unit_id), strict=True
            ):
                if not re.search(
                    r'\bid="' + re.escape(native_id) + r'"', chunks[key].chunk_text
                ):
                    raise ValueError("G92_NATIVE_CONTEXT_UNIT_SPAN")
            scale = re.search(r'\bscale="([+-]?\d+)"', c.chunk_text)
            # Missing scale remains unsupported by this new bridge even though
            # the existing parser has its own spec-defined default. Never guess.
            if scale is None or int(scale[1]) != proof.context.scale:
                raise ValueError("G92_EXPLICIT_NATIVE_SCALE_REQUIRED")
            if scaled_decimal(
                proof.context.lexical_value, proof.context.scale, proof.context.sign
            ) != Decimal(proof.context.value):
                raise ValueError("G92_CANONICAL_NATIVE_VALUE")
            node = next(
                n for n in tree.root.iter() if n.attrib.get("id") == proof.fact_id
            )
            fmt = re.search(r'\bformat="([^"]+)"', c.chunk_text)
            aspects.append(
                VerifiedNativeNumericAspect(
                    schema="G92_VERIFIED_NATIVE_NUMERIC_ASPECT_V1",
                    issuer=s.registration.owner,
                    accession=s.registration.accession,
                    evidence_ids=ids,
                    raw_sha256=blob_hash(raw),
                    receipt_identity=s.registration.manifest,
                    registration=digest(s.registration),
                    proof=proof,
                    char_span=(c.char_start, c.char_end),
                    byte_span=(
                        len(s.raw[: c.char_start].encode()),
                        len(s.raw[: c.char_end].encode()),
                    ),
                    raw_node_sha256=c.chunk_text_sha256,
                    format_literal=fmt[1] if fmt else None,
                    format_qname=(
                        tree.qname(fmt[1], tree.namespaces[node]) if fmt else None
                    ),
                    scale_explicit=True,
                    source_clocks=c.temporal_provenance.model_dump(mode="json"),
                )
            )
        return tuple(aspects)

    def ground(
        self, claim_text: str, entries: tuple[NumericEvidenceEntry, ...]
    ) -> tuple[NumericGroundingMatch, ...]:
        """Bind original model semantics and exact cited blocks before numeric use."""
        aspects = self._verify()
        s = self.source
        ids = tuple(e.evidence_id for e in entries)
        chunks = {c.canonical_id: c for c in s.chunks}
        if len(ids) != len(set(ids)) or any(i not in chunks for i in ids):
            raise ValueError("G92_UNKNOWN_EVIDENCE")
        for e in entries:
            c = chunks[e.evidence_id]
            if (
                e.short_description != c.chunk_text
                or e.numeric_tokens != numeric_literals(c.chunk_text)
                or getattr(e, "source", None) != c.exact_citation_reference
            ):
                raise ValueError("G92_EVIDENCE_CONTENT_IDENTITY")
        claim = ClaimEvidenceBinding(
            claim_id="g92-validation-only-not-model-claim",
            claim_path="analysis.facts[0]",
            claim_text=claim_text,
            evidence_ids=ids,
            source_references=tuple(chunks[i].exact_citation_reference for i in ids),
        )
        typed = extract(claim, s, profile="G92")
        aspect = next(
            a for a in aspects if digest(a.proof) == typed.native_proof_identity
        )
        # Typed amount comes from the MODEL text, never filled from the SEC proof.
        with localcontext() as ctx:
            ctx.prec = max(80, len(typed.value.as_tuple().digits) + abs(typed.scale))
            amount = typed.value.scaleb(typed.scale)
        if amount != Decimal(aspect.proof.context.value):
            raise ValueError("G92_MODEL_AMOUNT_MISMATCH")
        money = MONEY.search(claim_text)
        if money is None:
            raise ValueError("G92_MODEL_QUANTITY_MISSING")
        money_tokens = numeric_literals(money[0])
        dates = {str(typed.end)} | ({str(typed.start)} if typed.start else set())
        matches = []
        for literal in numeric_literals(claim_text):
            if literal not in money_tokens and literal not in dates:
                raise ValueError("G92_UNBOUND_ADDITIONAL_NUMERIC")
            matches.append(
                NumericGroundingMatch(
                    literal=literal,
                    kind=NumericSemanticKind.NUMERIC_FACT,
                    evidence_id=aspect.evidence_ids[
                        0 if literal in money_tokens else 1
                    ],
                    source_token=str(amount) if literal in money_tokens else literal,
                )
            )
        return tuple(matches)
