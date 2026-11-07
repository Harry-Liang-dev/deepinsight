"""Restricted offline iXBRL proof extraction; not Report or PIT admission.

Only registered source bytes and exact native contexts establish a fact. Unsupported
HTML, transformations, dimensions and ambiguous selections fail closed.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, localcontext
from html.parser import HTMLParser
from typing import Literal, Self, cast
from xml.etree.ElementTree import Element

from pydantic import model_validator

from src.schemas.research_v2_shared import Digest, Frozen, Text, digest
from src.services.native_preservation import NativePreserver, blob_hash
from src.services.phase5d_temporal import receipt_bytes
from src.services.sec_source_scope import TARGETS, SECSourceTarget

IX = "http://www.xbrl.org/2013/inlineXBRL"
X = "http://www.xbrl.org/2003/instance"
D = "http://xbrl.org/2006/xbrldi"
ISO = "http://www.xbrl.org/2003/iso4217"
VERSION: Literal["sec_native_financial_proof/0.1.0-experimental"] = (
    "sec_native_financial_proof/0.1.0-experimental"
)
TR5_PROFILE = "G53_XBRL_TR5_TRANSFORM_PROFILE/1"
TR5_QNAME = "{http://www.xbrl.org/inlineXBRL/transformation/2022-02-16}num-dot-decimal"
TR5_VERSION: Literal["sec_native_financial_proof/0.2.0-tr5-experimental"] = (
    "sec_native_financial_proof/0.2.0-tr5-experimental"
)


class SECRegistration(Frozen):
    """Externally pinned NEW source registration, never model-supplied authority."""

    owner: Text = "US:AAPL"
    cik: Text = "0000320193"
    accession: Text = "0000320193-26-000020"
    form: Literal["10-Q", "10-K"] = "10-Q"
    primary_document: Text = "aapl-20260627.htm"
    source_run: Text
    manifest: Digest
    submissions_manifest: Digest
    raw_sha256: Digest
    document_revision: Text
    classification: Literal["SYNTHETIC_NATIVE_FIXTURE", "ACTUAL_NEW_NATIVE_SOURCE"]
    allowed_dimensions: tuple[tuple[str, str], ...] = ()
    publication_assertion: None = None

    @property
    def target(self) -> SECSourceTarget:
        """Resolve an exact closed tuple; no wildcard issuer/file registration."""
        for target in TARGETS:
            if (self.owner, self.cik, self.accession, self.primary_document) == (
                target.owner,
                target.cik,
                target.accession,
                target.primary_document,
            ):
                return target
        raise ValueError("SEC_UNREGISTERED_FILING_SCOPE")

    @model_validator(mode="after")
    def closed_scope(self) -> Self:
        """Preserve legacy bytes and require a new G50 run for either new filing."""
        if self.form != self.target.form:
            raise ValueError("SEC_REGISTRATION_FORM_MISMATCH")
        if self.target.key.startswith("G55_"):
            from src.services.sec_source_scope import target_plan

            target_plan(self.target.key, self.source_run)
        elif self.target.key != "G43_AAPL" and not self.source_run.startswith("g50-"):
            raise ValueError("SEC_G50_NEW_SOURCE_RUN_REQUIRED")
        return self

    @property
    def document_url(self) -> str:
        """Exact filing path; no discovery fallback or approximate matching."""
        return self.target.urls[1]


class FactContext(Frozen):
    """Exact expected native semantic context, including QName namespaces."""

    concept: Text
    context_id: Text
    unit_id: Text
    cik: Text
    period_kind: Literal["duration", "instant"]
    start: date | None
    end: date
    dimensions: tuple[tuple[str, str], ...]
    currency: Text
    scale: int
    sign: Literal["", "-"]
    decimals: Text
    lexical_value: Text
    value: Text


class CellSelector(Frozen):
    """Logical DOM table location, not rendered-layout or TSV equivalence."""

    table_id: Text
    row: int
    column: int
    row_label: Text
    column_label: Text


class NativeFinancialProof(Frozen):
    """Recomputable source-native proof; downstream qualifications stay separate."""

    version: Literal[
        "sec_native_financial_proof/0.1.0-experimental",
        "sec_native_financial_proof/0.2.0-tr5-experimental",
    ] = VERSION
    classification: Literal["SYNTHETIC_NATIVE_FIXTURE", "ACTUAL_NEW_NATIVE_SOURCE"]
    registration: Digest
    manifest: Digest
    raw_sha256: Digest
    source_run: Text
    revision: Text
    fact_id: Text
    element_ordinal: int
    context: FactContext
    cell: CellSelector | None
    raw_source_durable: Literal[True] = True
    native_fact_proven: Literal[True] = True
    report_admissible: Literal["UNRESOLVED_NATIVE_FORMAT_NOT_REGISTERED"] = (
        "UNRESOLVED_NATIVE_FORMAT_NOT_REGISTERED"
    )
    prospective_pit_eligible: Literal[False] = False
    formal_historical_pit_eligible: Literal[False] = False
    publication_at: None = None


class _Tree(HTMLParser):
    """Strict balanced HTML/XHTML subset with native namespace resolution."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack: list[tuple[str, Element, dict[str, str]]] = [
            ("root", self.root, {})
        ]
        self.namespaces: dict[Element, dict[str, str]] = {}
        self.feed(text)
        self.close()
        if len(self.stack) != 1:
            raise ValueError("SEC_UNBALANCED_HTML")

    def handle_decl(self, decl: str) -> None:
        if decl.lower() != "doctype html":
            raise ValueError("SEC_UNSUPPORTED_DECLARATION")

    def unknown_decl(self, data: str) -> None:
        raise ValueError("SEC_UNSUPPORTED_DECLARATION")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(dict(attrs)) != len(attrs):
            raise ValueError("SEC_DUPLICATE_ATTRIBUTE")
        values = {k: v or "" for k, v in attrs}
        ns = dict(self.stack[-1][2])
        ns.update(
            {
                k.removeprefix("xmlns:"): v
                for k, v in values.items()
                if k.startswith("xmlns:")
            }
        )
        if "xmlns" in values:
            ns[""] = values["xmlns"]
        # HTML names are case-insensitive, namespace URI identity is not.
        namespace, local = self.qname(tag, ns).rsplit("}", 1)
        expanded = namespace + "}" + local.lower()
        element = Element(expanded, values)
        self.stack[-1][1].append(element)
        self.namespaces[element] = ns
        if tag not in {"br", "hr", "img", "meta", "link", "input"}:
            self.stack.append((tag, element, ns))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        depth = len(self.stack)
        self.handle_starttag(tag, attrs)
        if len(self.stack) > depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if len(self.stack) == 1 or self.stack[-1][0] != tag:
            raise ValueError("SEC_UNBALANCED_HTML")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        element = self.stack[-1][1]
        if len(element):
            element[-1].tail = (element[-1].tail or "") + data
        else:
            element.text = (element.text or "") + data

    @staticmethod
    def qname(value: str, ns: dict[str, str]) -> str:
        prefix, name = value.split(":", 1) if ":" in value else ("", value)
        if prefix and prefix not in ns:
            raise ValueError("SEC_UNBOUND_QNAME")
        return "{" + ns.get(prefix, "") + "}" + name


def _one(items: list[Element]) -> Element:
    if len(items) != 1:
        raise ValueError("SEC_MISSING_OR_AMBIGUOUS_NATIVE_NODE")
    return items[0]


def _text(element: Element) -> str:
    return "".join(element.itertext()).strip()


def extract_financial_proof(
    store: NativePreserver,
    registration: SECRegistration,
    *,
    registered_identity: str,
    fact_id: str,
    expected: FactContext,
    cell: CellSelector | None = None,
) -> NativeFinancialProof:
    """Reopen durable bytes and prove an exact fact; never infer missing context."""
    return _extract_financial_proof(
        store,
        registration,
        registered_identity=registered_identity,
        fact_id=fact_id,
        expected=expected,
        cell=cell,
    )


def _extract_financial_proof(
    store: NativePreserver,
    registration: SECRegistration,
    *,
    registered_identity: str,
    fact_id: str,
    expected: FactContext,
    cell: CellSelector | None = None,
    duplicate_member: bool = False,
) -> NativeFinancialProof:
    """Shared node checks; duplicate members are not independently admissible.

    Only the separate complete-group extractor uses duplicate_member. Existing
    public single-node extraction and Report re-extraction always reject peers.
    """
    r = SECRegistration.model_validate_json(registration.model_dump_json())
    if digest(r) != registered_identity:
        raise ValueError("SEC_EXTERNAL_REGISTRATION_PIN")
    if (store.provider, store.owner, store.run_id) != (
        "sec_edgar",
        r.owner,
        r.source_run,
    ):
        raise ValueError("SEC_SOURCE_RUN_OWNER")
    m, submissions = store.verify(r.manifest), store.verify(r.submissions_manifest)
    raw = receipt_bytes(m.acquisition)
    if (
        m.acquisition.endpoint != r.document_url
        or m.acquisition.revision_id != r.document_revision
        or blob_hash(raw) != r.raw_sha256
        or m.status_code != 200
        or submissions.status_code != 200
        or submissions.acquisition.endpoint != r.target.urls[0]
    ):
        raise ValueError("SEC_NATIVE_DOCUMENT_BINDING")
    metadata = json.loads(receipt_bytes(submissions.acquisition))
    recent = metadata["filings"]["recent"]
    indexes = [i for i, a in enumerate(recent["accessionNumber"]) if a == r.accession]
    if (
        str(metadata["cik"]).zfill(10) != r.cik
        or len(indexes) != 1
        or recent["form"][indexes[0]] != r.form
        or recent["primaryDocument"][indexes[0]] != r.primary_document
        or (
            r.target.key != "G43_AAPL"
            and recent.get("reportDate", [])[indexes[0]] != r.target.period_end
        )
    ):
        raise ValueError("SEC_SUBMISSIONS_TARGET_MISMATCH")
    if len(raw) > 20_000_000:
        raise ValueError("SEC_DOCUMENT_SIZE")
    tree = _Tree(raw.decode("utf-8", errors="strict"))
    nodes = list(tree.root.iter())
    ids = [n.attrib["id"] for n in nodes if "id" in n.attrib]
    if len(set(ids)) != len(ids):
        raise ValueError("SEC_DUPLICATE_NATIVE_ID")
    fact = _one(
        [
            n
            for n in nodes
            if n.attrib.get("id") == fact_id and n.tag == "{" + IX + "}nonfraction"
        ]
    )
    ns = tree.namespaces[fact]

    def qname(value: str) -> str:
        return tree.qname(value, ns)

    context_id, unit_id = fact.attrib["contextref"], fact.attrib["unitref"]
    concept = qname(fact.attrib["name"])
    peers = [
        n
        for n in nodes
        if n.tag == fact.tag
        and n.attrib.get("contextref") == context_id
        and tree.qname(n.attrib.get("name", ""), tree.namespaces[n]) == concept
    ]
    if len(peers) != 1 and not duplicate_member:
        raise ValueError("SEC_AMBIGUOUS_FACT")
    context = _one(
        [
            n
            for n in nodes
            if n.tag == "{" + X + "}context" and n.attrib.get("id") == context_id
        ]
    )
    if sorted(n.tag for n in context) != sorted(
        ["{" + X + "}entity", "{" + X + "}period"]
    ):
        raise ValueError("SEC_CONTEXT_STRUCTURE")
    entity = _one([n for n in context if n.tag == "{" + X + "}entity"])
    if any(
        n.tag not in {"{" + X + "}identifier", "{" + X + "}segment"} for n in entity
    ):
        raise ValueError("SEC_ENTITY_STRUCTURE")
    allowed = {
        "context",
        "entity",
        "identifier",
        "segment",
        "period",
        "startdate",
        "enddate",
        "instant",
    }
    if any(
        n.tag
        not in {"{" + X + "}" + k for k in allowed} | {"{" + D + "}explicitmember"}
        for n in context.iter()
    ):
        raise ValueError("SEC_UNSUPPORTED_CONTEXT_DIMENSION")
    identifier = _one([n for n in context.iter() if n.tag == "{" + X + "}identifier"])
    if (
        identifier.attrib.get("scheme") != "http://www.sec.gov/CIK"
        or _text(identifier).zfill(10) != r.cik
    ):
        raise ValueError("SEC_ENTITY_CIK")
    period = _one([n for n in context if n.tag == "{" + X + "}period"])
    kind: Literal["duration", "instant"]
    if [n.tag for n in period] == ["{" + X + "}instant"]:
        kind, start, end = "instant", None, date.fromisoformat(_text(period[0]))
    elif [n.tag for n in period] == ["{" + X + "}startdate", "{" + X + "}enddate"]:
        kind, start, end = (
            "duration",
            date.fromisoformat(_text(period[0])),
            date.fromisoformat(_text(period[1])),
        )
        if start > end:
            raise ValueError("SEC_PERIOD_ORDER")
    else:
        raise ValueError("SEC_PERIOD_SHAPE")
    dimensions = tuple(
        sorted(
            (
                tree.qname(n.attrib["dimension"], tree.namespaces[n]),
                tree.qname(_text(n), tree.namespaces[n]),
            )
            for n in context.iter()
            if n.tag == "{" + D + "}explicitmember"
        )
    )
    if len({a for a, _ in dimensions}) != len(dimensions) or any(
        d not in r.allowed_dimensions for d in dimensions
    ):
        raise ValueError("SEC_UNREGISTERED_DIMENSION")
    unit = _one(
        [
            n
            for n in nodes
            if n.tag == "{" + X + "}unit" and n.attrib.get("id") == unit_id
        ]
    )
    measure = _one(list(unit))
    currency = tree.qname(_text(measure), tree.namespaces[measure])
    if measure.tag != "{" + X + "}measure" or currency != "{" + ISO + "}USD":
        raise ValueError("SEC_UNSUPPORTED_CURRENCY_UNIT")
    allowed_attributes = {
        "id",
        "name",
        "contextref",
        "unitref",
        "scale",
        "sign",
        "decimals",
        "format",
        "style",
        "class",
        "title",
    }
    if any(
        k not in allowed_attributes and not k.startswith("xmlns") for k in fact.attrib
    ) or len(fact):
        raise ValueError("SEC_UNSUPPORTED_FACT_CONTENT")
    if "format" in fact.attrib and qname(fact.attrib["format"]) not in {
        "{http://www.xbrl.org/inlineXBRL/transformation/2020-02-12}num-dot-decimal",
        TR5_QNAME,
    }:
        raise ValueError("SEC_UNSUPPORTED_TRANSFORM")
    lexical = _text(fact)
    if "," in lexical and "format" not in fact.attrib:
        raise ValueError("SEC_UNREGISTERED_GROUPING_TRANSFORM")
    if (
        not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", lexical)
        or len(lexical) > 48
    ):
        raise ValueError("SEC_FINANCIAL_LEXEME")
    scale, sign, decimals = (
        int(fact.attrib.get("scale", "0")),
        fact.attrib.get("sign", ""),
        fact.attrib["decimals"],
    )
    if (
        abs(scale) > 18
        or sign not in ("", "-")
        or (decimals != "INF" and not re.fullmatch(r"-?(?:[0-9]|1[0-8])", decimals))
    ):
        raise ValueError("SEC_NUMERIC_ATTRIBUTES")
    with localcontext() as ctx:
        ctx.prec = 80
        value = Decimal(lexical.replace(",", "")).scaleb(scale)
        value = -value if sign else value
    actual = FactContext(
        concept=concept,
        context_id=context_id,
        unit_id=unit_id,
        cik=r.cik,
        period_kind=kind,
        start=start,
        end=end,
        dimensions=dimensions,
        currency="USD",
        scale=scale,
        sign=cast(Literal["", "-"], sign),
        decimals=decimals,
        lexical_value=lexical,
        value=format(value, "f"),
    )
    if actual != expected:
        raise ValueError("SEC_EXACT_FACT_CONTEXT_MISMATCH")
    if cell is not None:
        table = _one(
            [
                n
                for n in nodes
                if n.tag.rsplit("}", 1)[-1] == "table"
                and n.attrib.get("id") == cell.table_id
            ]
        )
        if sum(n.tag.rsplit("}", 1)[-1] == "table" for n in table.iter()) != 1:
            raise ValueError("SEC_NESTED_TABLE_UNSUPPORTED")
        rows = [n for n in table.iter() if n.tag.rsplit("}", 1)[-1] == "tr"]
        grid = [
            [n for n in row if n.tag.rsplit("}", 1)[-1] in {"td", "th"}] for row in rows
        ]
        if (
            cell.row < 1
            or cell.column < 1
            or cell.row >= len(grid)
            or any(len(row) != len(grid[0]) for row in grid)
            or cell.column >= len(grid[0])
            or any(
                n.attrib.get(k, "1") != "1"
                for row in grid
                for n in row
                for k in ("rowspan", "colspan")
            )
            or _text(grid[cell.row][0]) != cell.row_label
            or _text(grid[0][cell.column]) != cell.column_label
            or fact not in list(grid[cell.row][cell.column].iter())
        ):
            raise ValueError("SEC_NATIVE_TABLE_CELL_MISMATCH")
    return NativeFinancialProof(
        version=(
            TR5_VERSION
            if "format" in fact.attrib and qname(fact.attrib["format"]) == TR5_QNAME
            else VERSION
        ),
        classification=r.classification,
        registration=registered_identity,
        manifest=r.manifest,
        raw_sha256=r.raw_sha256,
        source_run=r.source_run,
        revision=r.document_revision,
        fact_id=fact_id,
        element_ordinal=nodes.index(fact),
        context=actual,
        cell=cell,
    )
