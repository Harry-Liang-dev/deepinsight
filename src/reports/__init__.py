"""Public deterministic report assembly boundary."""

from src.reports.assembler import (
    EmptyAgentOutputError,
    MissingReportSectionError,
    ReportAssembler,
    ReportAssemblyError,
    ReportCitationError,
)
from src.reports.contracts import (
    STANDARD_SECTION_NAMES,
    ReportAssemblyInput,
    ReportStatement,
    StandardReportSection,
)

__all__ = [
    "STANDARD_SECTION_NAMES",
    "EmptyAgentOutputError",
    "MissingReportSectionError",
    "ReportAssembler",
    "ReportAssemblyError",
    "ReportAssemblyInput",
    "ReportCitationError",
    "ReportStatement",
    "StandardReportSection",
]
