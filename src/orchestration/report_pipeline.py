"""Research report persistence and L3 Memory orchestration."""

from __future__ import annotations

from typing import Protocol

from src.models.enums import TaskStatus
from src.reports.assembler import ReportAssembler
from src.reports.contracts import ReportAssemblyInput
from src.schemas.memory import MemoryWriteRequest, MemoryWriteResult
from src.schemas.reports import ResearchReport


class ReportStore(Protocol):
    """Narrow persistence boundary used by the report pipeline."""

    def save(self, report: ResearchReport) -> None:
        """Atomically persist a report and its sections."""
        ...


class ReportMemoryWriter(Protocol):
    """Narrow public Memory boundary used by the report pipeline."""

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Write one attributable L3 report trace."""
        ...

    def delete(self, memory_id: str) -> None:
        """Delete one L3 trace during failed completion compensation."""
        ...


class ResearchReportPipeline:
    """Finalize structured Agent output without direct storage dependencies."""

    def __init__(
        self,
        assembler: ReportAssembler,
        report_store: ReportStore,
        memory_writer: ReportMemoryWriter,
    ) -> None:
        """Bind pure assembly and replaceable persistence boundaries.

        Args:
            assembler: Deterministic Markdown and JSON report assembler.
            report_store: Report persistence interface.
            memory_writer: Public Memory write interface.
        """

        self._assembler = assembler
        self._report_store = report_store
        self._memory_writer = memory_writer

    def execute(self, payload: ReportAssemblyInput) -> ResearchReport:
        """Persist a running report, write L3 trace, then mark it completed.

        Args:
            payload: Validated structured Agent result and report request.

        Returns:
            Completed standard research report.

        Raises:
            Exception: Propagates assembly, persistence, or Memory failures.
                A report is never persisted as completed before all preceding
                stages succeed.
        """

        running_report = self._assembler.assemble(
            payload,
            status=TaskStatus.RUNNING,
        )
        self._report_store.save(running_report)
        try:
            memory = self._memory_writer.write(
                self._assembler.to_memory_request(running_report)
            )
        except Exception:
            self._record_failed(running_report)
            raise
        completed_report = running_report.model_copy(
            update={"status": TaskStatus.COMPLETED}
        )
        try:
            self._report_store.save(completed_report)
        except Exception:
            try:
                self._memory_writer.delete(memory.memory_id)
            finally:
                self._record_failed(running_report)
            raise
        return completed_report

    def _record_failed(self, report: ResearchReport) -> None:
        """Best-effort replacement of a stale running report state."""

        try:
            self._report_store.save(
                report.model_copy(update={"status": TaskStatus.FAILED})
            )
        except Exception:
            return
