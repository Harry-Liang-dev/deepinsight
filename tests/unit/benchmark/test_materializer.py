"""Tests for fixed report materialization without production orchestration."""

from __future__ import annotations

import pytest

from src.benchmark import BenchmarkReportMaterializer
from src.models.enums import BenchmarkExpectedOutcome, TaskStatus
from src.reports import STANDARD_SECTION_NAMES
from src.schemas.benchmark import ResearchBenchmarkCase


def test_materializer_builds_current_ten_section_report_with_known_sources(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """Fixed semantic input becomes one valid, attributable report contract."""

    case = next(
        item
        for item in benchmark_cases
        if item.expected_outcome is BenchmarkExpectedOutcome.REPORT
    )
    report = BenchmarkReportMaterializer().build(case)

    assert report.status is TaskStatus.COMPLETED
    assert list(report.report_json) == list(STANDARD_SECTION_NAMES)
    assert [section.section_name for section in report.sections] == list(
        STANDARD_SECTION_NAMES
    )
    assert report.source_trace
    assert {citation.document_id for citation in report.source_trace} <= {
        source.document_id for source in case.sources
    }


def test_materializer_refuses_expected_failure_case(
    benchmark_cases: list[ResearchBenchmarkCase],
) -> None:
    """No report is invented after a declared Analyst failure."""

    failure = next(case for case in benchmark_cases if case.report is None)

    with pytest.raises(ValueError, match="only report"):
        BenchmarkReportMaterializer().build(failure)
