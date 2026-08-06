"""Tests for report lifecycle and replaceable persistence boundaries."""

from __future__ import annotations

import pytest

from src.models.enums import MemoryLevel, TaskStatus
from src.orchestration import ResearchReportPipeline
from src.reports import ReportAssembler
from src.schemas.memory import (
    MemoryWriteRequest,
    MemoryWriteResult,
)
from src.schemas.reports import ResearchReport
from tests.fixtures.report_data import make_report_input


class CapturingReportStore:
    """Capture saved report states and optionally fail at one call."""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.reports: list[ResearchReport] = []
        self._calls = 0
        self._fail_on_call = fail_on_call

    def save(self, report: ResearchReport) -> None:
        self._calls += 1
        if self._calls == self._fail_on_call:
            raise RuntimeError("simulated report persistence failure")
        self.reports.append(report.model_copy(deep=True))


class CapturingMemoryWriter:
    """Capture the L3 write and optionally fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[MemoryWriteRequest] = []
        self.deleted: list[str] = []
        self._fail = fail

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        self.requests.append(request)
        if self._fail:
            raise RuntimeError("simulated Memory failure")
        return MemoryWriteResult(
            memory_id="memory-report-1",
            faiss_namespace="memory_L3_v1",
            faiss_vector_id=1,
        )

    def delete(self, memory_id: str) -> None:
        self.deleted.append(memory_id)


def test_pipeline_marks_report_completed_only_after_memory_write() -> None:
    """A successful pipeline persists running then completed states."""

    store = CapturingReportStore()
    memory = CapturingMemoryWriter()
    pipeline = ResearchReportPipeline(ReportAssembler(), store, memory)

    report = pipeline.execute(make_report_input())

    assert [item.status for item in store.reports] == [
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
    ]
    assert report.status is TaskStatus.COMPLETED
    assert len(memory.requests) == 1
    assert memory.requests[0].memory_level is MemoryLevel.L3
    assert memory.requests[0].namespace_key == "REPORT:report-1"
    assert memory.requests[0].source_ref_json == report.source_trace[0]


def test_memory_failure_persists_explicit_failed_report() -> None:
    """A failed L3 write must not leave a stale running report."""

    store = CapturingReportStore()
    pipeline = ResearchReportPipeline(
        ReportAssembler(),
        store,
        CapturingMemoryWriter(fail=True),
    )

    with pytest.raises(RuntimeError, match="Memory"):
        pipeline.execute(make_report_input())

    assert [item.status for item in store.reports] == [
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ]


def test_final_persistence_failure_compensates_memory_and_marks_failed() -> None:
    """A failed completion write must compensate Memory and terminalize state."""

    store = CapturingReportStore(fail_on_call=2)
    memory = CapturingMemoryWriter()
    pipeline = ResearchReportPipeline(
        ReportAssembler(),
        store,
        memory,
    )

    with pytest.raises(RuntimeError, match="persistence"):
        pipeline.execute(make_report_input())

    assert [item.status for item in store.reports] == [
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
    ]
    assert memory.deleted == ["memory-report-1"]
