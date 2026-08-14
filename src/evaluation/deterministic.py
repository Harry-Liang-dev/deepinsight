"""Deterministic report-quality checks over structured reports and evidence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from src.models.compliance import claim_intent_is_allowed
from src.models.enums import (
    ClaimIntent,
    EvaluationDimension,
    EvaluationEvidenceKind,
    EvaluatorKind,
)
from src.reports.contracts import STANDARD_SECTION_NAMES, StandardReportSection
from src.schemas.common import SourceReference
from src.schemas.evaluation import (
    EvaluationCheck,
    EvaluationEvidenceItem,
    EvaluationEvidenceRef,
    EvaluationInput,
    EvaluationRuleSet,
)


@dataclass(frozen=True, slots=True)
class _Statement:
    """Tolerant internal view of one report statement."""

    path: str
    text: str
    citations: tuple[SourceReference, ...]
    claim_intent: ClaimIntent
    numeric_literals: tuple[str, ...]
    claim_status: str


class DeterministicReportEvaluator:
    """Compute all objectively reproducible first-version checks."""

    def evaluate(
        self,
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> list[EvaluationCheck]:
        """Return deterministic checks in stable order."""

        statements = _statements(payload)
        return [
            self._structure(payload, rules),
            self._numeric_grounding(payload, rules, statements),
            self._citation_coverage(rules, statements),
            self._citation_traceability(payload, rules, statements),
            self._uncertainty_presence(payload, rules),
            self._temporal_validity(payload, rules, statements),
            self._trading_compliance(payload, rules),
            self._missing_data_disclosure(payload, rules),
        ]

    @staticmethod
    def _structure(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> EvaluationCheck:
        raw = payload.report.report_json
        exact_section_set = set(raw) == set(STANDARD_SECTION_NAMES)
        present = sum(name in raw for name in STANDARD_SECTION_NAMES)
        valid = 0
        ordered = 0
        for expected_order, name in enumerate(STANDARD_SECTION_NAMES):
            value = raw.get(name)
            try:
                section = StandardReportSection.model_validate(value)
            except ValidationError:
                continue
            valid += 1
            if section.section_name == name and section.section_order == expected_order:
                ordered += 1
        denominator = 3 * len(STANDARD_SECTION_NAMES) + 1
        score = (present + valid + ordered + int(exact_section_set)) / denominator
        return _check(
            check_id="structure_completeness",
            dimension=EvaluationDimension.STRUCTURE_COMPLETENESS,
            score=score,
            rules=rules,
            reason=(
                f"{present}/{len(STANDARD_SECTION_NAMES)} required sections "
                f"were present, {valid} were schema-valid, and {ordered} "
                "had the expected identity and order. "
                f"Exact section set: {exact_section_set}."
            ),
            evidence=[
                _report_ref(
                    "report.report_json",
                    excerpt="standard section presence, schema, and order",
                )
            ],
        )

    @staticmethod
    def _numeric_grounding(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
        statements: Sequence[_Statement],
    ) -> EvaluationCheck:
        numeric = [statement for statement in statements if statement.numeric_literals]
        if not numeric:
            return _check(
                check_id="numeric_grounding",
                dimension=EvaluationDimension.FACTUAL_CORRECTNESS,
                score=1.0,
                rules=rules,
                reason="The report contained no numeric textual claims to verify.",
                evidence=[_diagnostic_ref("numeric_claims:none")],
            )
        supported = sum(statement.claim_status == "accepted" for statement in numeric)
        score = supported / len(numeric)
        detail = (
            f"{supported}/{len(numeric)} numeric report Claims retained an "
            "accepted upstream validation status."
        )
        return _check(
            check_id="numeric_grounding",
            dimension=EvaluationDimension.FACTUAL_CORRECTNESS,
            score=score,
            rules=rules,
            reason=detail,
            evidence=[
                _report_ref(statement.path, excerpt=statement.text[:240])
                for statement in numeric[:5]
            ],
        )

    @staticmethod
    def _citation_coverage(
        rules: EvaluationRuleSet,
        statements: Sequence[_Statement],
    ) -> EvaluationCheck:
        if not statements:
            return _check(
                check_id="citation_coverage",
                dimension=EvaluationDimension.CITATION_COVERAGE,
                score=0.0,
                rules=rules,
                reason="No attributable report statements were found.",
                evidence=[_diagnostic_ref("report_statements:none")],
            )
        cited = sum(bool(statement.citations) for statement in statements)
        return _check(
            check_id="citation_coverage",
            dimension=EvaluationDimension.CITATION_COVERAGE,
            score=cited / len(statements),
            rules=rules,
            reason=f"{cited}/{len(statements)} report statements contained citations.",
            evidence=[
                _report_ref(
                    "report.report_json",
                    excerpt="facts, inferences, and risk_warnings",
                )
            ],
        )

    @staticmethod
    def _citation_traceability(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
        statements: Sequence[_Statement],
    ) -> EvaluationCheck:
        citations = _unique_citations(
            citation for statement in statements for citation in statement.citations
        )
        if not citations:
            return _check(
                check_id="citation_traceability",
                dimension=EvaluationDimension.CITATION_TRACEABILITY,
                score=0.0,
                rules=rules,
                reason="No citations were available for source tracing.",
                evidence=[_diagnostic_ref("citations:none")],
            )
        traced = [
            citation
            for citation in citations
            if _matching_evidence(citation, payload.evidence_items)
        ]
        return _check(
            check_id="citation_traceability",
            dimension=EvaluationDimension.CITATION_TRACEABILITY,
            score=len(traced) / len(citations),
            rules=rules,
            reason=(
                f"{len(traced)}/{len(citations)} unique citations resolved to "
                "supplied evidence."
            ),
            evidence=[_source_ref(citation) for citation in citations[:5]],
        )

    @staticmethod
    def _uncertainty_presence(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> EvaluationCheck:
        count = 0
        paths: list[str] = []
        for name in STANDARD_SECTION_NAMES:
            value = payload.report.report_json.get(name)
            if not isinstance(value, dict):
                continue
            uncertainties = value.get("uncertainties")
            if isinstance(uncertainties, list):
                usable = [
                    item
                    for item in uncertainties
                    if isinstance(item, str) and item.strip()
                ]
                if usable:
                    count += len(usable)
                    paths.append(f"report.report_json.{name}.uncertainties")
        score = 1.0 if count else 0.0
        return _check(
            check_id="uncertainty_presence",
            dimension=EvaluationDimension.UNCERTAINTY_EXPRESSION,
            score=score,
            rules=rules,
            reason=f"The report contained {count} explicit uncertainty statements.",
            evidence=(
                [_report_ref(path) for path in paths[:5]]
                if paths
                else [_diagnostic_ref("uncertainties:none")]
            ),
        )

    @staticmethod
    def _temporal_validity(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
        statements: Sequence[_Statement],
    ) -> EvaluationCheck:
        citations = _unique_citations(
            citation for statement in statements for citation in statement.citations
        )
        if not citations:
            return _check(
                check_id="temporal_validity",
                dimension=EvaluationDimension.TEMPORAL_VALIDITY,
                score=0.0,
                rules=rules,
                reason="No cited evidence was available for temporal validation.",
                evidence=[_diagnostic_ref("temporal_evidence:none")],
            )
        valid = 0
        diagnostics: list[str] = []
        for citation in citations:
            matches = _matching_evidence(citation, payload.evidence_items)
            dated = [item for item in matches if item.published_at is not None]
            citation_valid = bool(dated) and any(
                _date_is_valid(
                    item.published_at.date(),
                    payload.report.report_date,
                    rules.max_evidence_age_days,
                )
                for item in dated
                if item.published_at is not None
            )
            if citation_valid:
                valid += 1
            else:
                diagnostics.append(_citation_locator(citation))
        reason = (
            f"{valid}/{len(citations)} unique citations had dated evidence "
            f"between the report date and {rules.max_evidence_age_days} days old."
        )
        if diagnostics:
            reason = f"{reason} Invalid or undated: {', '.join(diagnostics[:5])}."
        return _check(
            check_id="temporal_validity",
            dimension=EvaluationDimension.TEMPORAL_VALIDITY,
            score=valid / len(citations),
            rules=rules,
            reason=reason,
            evidence=[_source_ref(citation) for citation in citations[:5]],
        )

    @staticmethod
    def _trading_compliance(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> EvaluationCheck:
        statements = _statements(payload)
        matches = [
            statement.path
            for statement in statements
            if not claim_intent_is_allowed(statement.claim_intent)
        ]
        return _check(
            check_id="trading_instruction_compliance",
            dimension=EvaluationDimension.TRADING_INSTRUCTION_COMPLIANCE,
            score=0.0 if matches else 1.0,
            rules=rules,
            reason=(
                f"Detected prohibited trading language: {', '.join(matches)}."
                if matches
                else ("No system recommendation or execution instruction was detected.")
            ),
            evidence=[_report_ref("report.report_markdown")],
        )

    @staticmethod
    def _missing_data_disclosure(
        payload: EvaluationInput,
        rules: EvaluationRuleSet,
    ) -> EvaluationCheck:
        known = [item.strip() for item in payload.known_missing_data if item.strip()]
        if not known:
            return _check(
                check_id="missing_data_disclosure",
                dimension=EvaluationDimension.MISSING_DATA_DISCLOSURE,
                score=1.0,
                rules=rules,
                reason="No upstream missing-data items were supplied for disclosure.",
                evidence=[_diagnostic_ref("known_missing_data:none")],
            )
        normalized = payload.report.report_markdown.casefold()
        disclosed = [item for item in known if item.casefold() in normalized]
        missing = [item for item in known if item not in disclosed]
        reason = (
            f"{len(disclosed)}/{len(known)} known missing-data items were disclosed."
        )
        if missing:
            reason = f"{reason} Undisclosed: {', '.join(missing[:5])}."
        return _check(
            check_id="missing_data_disclosure",
            dimension=EvaluationDimension.MISSING_DATA_DISCLOSURE,
            score=len(disclosed) / len(known),
            rules=rules,
            reason=reason,
            evidence=[
                _diagnostic_ref(
                    "known_missing_data",
                    excerpt=", ".join(known[:10]),
                ),
                _report_ref("report.report_markdown"),
            ],
        )


def _check(
    *,
    check_id: str,
    dimension: EvaluationDimension,
    score: float,
    rules: EvaluationRuleSet,
    reason: str,
    evidence: list[EvaluationEvidenceRef],
) -> EvaluationCheck:
    bounded = min(1.0, max(0.0, score))
    return EvaluationCheck(
        check_id=check_id,
        dimension=dimension,
        evaluator=EvaluatorKind.DETERMINISTIC,
        score=bounded,
        passed=bounded >= rules.pass_threshold,
        reason=reason,
        evidence=evidence,
    )


def _statements(payload: EvaluationInput) -> list[_Statement]:
    statements: list[_Statement] = []
    for section_name, raw_section in payload.report.report_json.items():
        if not isinstance(raw_section, dict):
            continue
        for category in ("facts", "inferences", "risk_warnings"):
            raw_statements = raw_section.get(category)
            if not isinstance(raw_statements, list):
                continue
            for index, raw_statement in enumerate(raw_statements):
                if not isinstance(raw_statement, dict):
                    continue
                text = raw_statement.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                raw_citations = raw_statement.get("citations")
                citations: list[SourceReference] = []
                if isinstance(raw_citations, list):
                    for raw_citation in raw_citations:
                        try:
                            citations.append(
                                SourceReference.model_validate(raw_citation)
                            )
                        except ValidationError:
                            continue
                raw_intent = raw_statement.get("claim_intent")
                claim_intent = (
                    ClaimIntent(raw_intent)
                    if isinstance(raw_intent, str)
                    and raw_intent in {item.value for item in ClaimIntent}
                    else ClaimIntent.FACT
                )
                raw_literals = raw_statement.get("numeric_literals")
                numeric = (
                    tuple(item for item in raw_literals if isinstance(item, str))
                    if isinstance(raw_literals, list)
                    else ()
                )
                raw_status = raw_statement.get("claim_status")
                statements.append(
                    _Statement(
                        path=(
                            f"report.report_json.{section_name}." f"{category}[{index}]"
                        ),
                        text=text,
                        citations=tuple(citations),
                        claim_intent=claim_intent,
                        numeric_literals=numeric,
                        claim_status=(
                            raw_status if isinstance(raw_status, str) else "accepted"
                        ),
                    )
                )
    return statements


def _matching_evidence(
    citation: SourceReference,
    evidence_items: Sequence[EvaluationEvidenceItem],
) -> list[EvaluationEvidenceItem]:
    return [
        item for item in evidence_items if _citation_matches(citation, item.source_ref)
    ]


def _citation_matches(
    citation: SourceReference,
    source: SourceReference,
) -> bool:
    values = (
        (citation.document_id, source.document_id),
        (citation.excerpt_ref, source.excerpt_ref),
        (citation.provider, source.provider),
        (citation.source_url, source.source_url),
    )
    return all(expected is None or expected == actual for expected, actual in values)


def _citation_key(citation: SourceReference) -> tuple[str, str, str, str]:
    return (
        citation.document_id or "",
        citation.excerpt_ref or "",
        citation.provider or "",
        citation.source_url or "",
    )


def _unique_citations(
    citations: Iterable[SourceReference],
) -> list[SourceReference]:
    unique: dict[tuple[str, str, str, str], SourceReference] = {}
    for citation in citations:
        unique.setdefault(_citation_key(citation), citation)
    return list(unique.values())


def _date_is_valid(
    published: date,
    report_date: date,
    max_age_days: int,
) -> bool:
    age = (report_date - published).days
    return 0 <= age <= max_age_days


def _report_ref(locator: str, excerpt: str | None = None) -> EvaluationEvidenceRef:
    return EvaluationEvidenceRef(
        kind=EvaluationEvidenceKind.REPORT_PATH,
        locator=locator,
        excerpt=excerpt,
    )


def _diagnostic_ref(
    locator: str,
    excerpt: str | None = None,
) -> EvaluationEvidenceRef:
    return EvaluationEvidenceRef(
        kind=EvaluationEvidenceKind.DIAGNOSTIC,
        locator=locator,
        excerpt=excerpt,
    )


def _source_ref(citation: SourceReference) -> EvaluationEvidenceRef:
    return EvaluationEvidenceRef(
        kind=EvaluationEvidenceKind.SOURCE,
        locator=_citation_locator(citation),
    )


def _citation_locator(citation: SourceReference) -> str:
    values = [
        citation.document_id,
        citation.excerpt_ref,
        citation.provider,
        citation.source_url,
    ]
    return "|".join(value for value in values if value) or "unresolved-source"
