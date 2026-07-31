"""Atomic DuckDB Repository for reports and ordered report sections."""

from __future__ import annotations

from typing import cast

import duckdb
from pydantic import TypeAdapter

from src.models.types import JsonValue
from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_object,
    decode_json_value,
    encode_json,
)
from src.schemas.common import SourceReference
from src.schemas.reports import ReportSection, ResearchReport

_SOURCE_REFERENCES = TypeAdapter(list[SourceReference])

_REPORT_COLUMNS = (
    "report_id",
    "report_date",
    "market_scope",
    "report_type",
    "asset_id",
    "title",
    "thesis_bull_summary",
    "thesis_bear_summary",
    "risk_summary",
    "final_recommendation",
    "confidence_band",
    "report_markdown",
    "report_json",
    "source_trace_json",
    "status",
    "created_at",
)

_SECTION_COLUMNS = (
    "report_id",
    "section_name",
    "section_order",
    "section_markdown",
    "citations_json",
)


class ReportRepository(BaseRepository):
    """Persist a report and its sections as one consistency boundary."""

    def save(self, report: ResearchReport) -> None:
        """Atomically insert or replace a report and all of its sections.

        Args:
            report: Validated final report domain object.

        Raises:
            ValueError: If a section belongs to another report.
            RepositoryError: If any DuckDB write fails; all changes are rolled
                back.
        """

        if any(section.report_id != report.report_id for section in report.sections):
            raise ValueError("all sections must belong to the saved report")

        source_trace = _SOURCE_REFERENCES.dump_python(
            report.source_trace,
            mode="json",
        )
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"""
                    INSERT INTO reports ({", ".join(_REPORT_COLUMNS)})
                    VALUES ({_placeholders(len(_REPORT_COLUMNS))})
                    ON CONFLICT (report_id) DO UPDATE SET
                        report_date = excluded.report_date,
                        market_scope = excluded.market_scope,
                        report_type = excluded.report_type,
                        asset_id = excluded.asset_id,
                        title = excluded.title,
                        thesis_bull_summary = excluded.thesis_bull_summary,
                        thesis_bear_summary = excluded.thesis_bear_summary,
                        risk_summary = excluded.risk_summary,
                        final_recommendation = excluded.final_recommendation,
                        confidence_band = excluded.confidence_band,
                        report_markdown = excluded.report_markdown,
                        report_json = excluded.report_json,
                        source_trace_json = excluded.source_trace_json,
                        status = excluded.status,
                        created_at = excluded.created_at
                    """,
                    (
                        report.report_id,
                        report.report_date,
                        report.market_scope.value,
                        report.report_type.value,
                        None if report.asset_id is None else str(report.asset_id),
                        report.title,
                        report.thesis_bull_summary,
                        report.thesis_bear_summary,
                        report.risk_summary,
                        report.final_recommendation,
                        report.confidence_band,
                        report.report_markdown,
                        encode_json(report.report_json),
                        encode_json(cast(JsonValue, source_trace)),
                        report.status.value,
                        report.created_at,
                    ),
                )
                connection.execute(
                    "DELETE FROM report_sections WHERE report_id = ?",
                    (report.report_id,),
                )
                for section in report.sections:
                    citations = _SOURCE_REFERENCES.dump_python(
                        section.citations,
                        mode="json",
                    )
                    connection.execute(
                        f"""
                        INSERT INTO report_sections
                            ({", ".join(_SECTION_COLUMNS)})
                        VALUES ({_placeholders(len(_SECTION_COLUMNS))})
                        """,
                        (
                            section.report_id,
                            section.section_name,
                            section.section_order,
                            section.section_markdown,
                            encode_json(cast(JsonValue, citations)),
                        ),
                    )
        except duckdb.Error as exc:
            raise RepositoryError("failed to save report atomically") from exc

    def get(self, report_id: str) -> ResearchReport | None:
        """Return a report and all ordered sections from one snapshot.

        Args:
            report_id: Stable report identifier.

        Returns:
            The matching report, or ``None``.
        """

        try:
            with self._database.transaction() as connection:
                report_row = connection.execute(
                    f"""
                    SELECT {", ".join(_REPORT_COLUMNS)}
                    FROM reports
                    WHERE report_id = ?
                    """,
                    (report_id,),
                ).fetchone()
                if report_row is None:
                    return None
                section_rows = connection.execute(
                    f"""
                    SELECT {", ".join(_SECTION_COLUMNS)}
                    FROM report_sections
                    WHERE report_id = ?
                    ORDER BY section_order, section_name
                    """,
                    (report_id,),
                ).fetchall()
        except duckdb.Error as exc:
            raise RepositoryError("failed to read report") from exc

        report_values = dict(zip(_REPORT_COLUMNS, report_row, strict=True))
        report_values["report_json"] = decode_json_object(report_values["report_json"])
        raw_trace = report_values.pop("source_trace_json")
        report_values["source_trace"] = (
            []
            if raw_trace is None
            else _SOURCE_REFERENCES.validate_python(decode_json_value(raw_trace))
        )

        sections: list[ReportSection] = []
        for row in section_rows:
            section_values = dict(zip(_SECTION_COLUMNS, row, strict=True))
            raw_citations = section_values.pop("citations_json")
            section_values["citations"] = (
                []
                if raw_citations is None
                else _SOURCE_REFERENCES.validate_python(
                    decode_json_value(raw_citations)
                )
            )
            sections.append(ReportSection.model_validate(section_values))
        report_values["sections"] = sections
        return ResearchReport.model_validate(report_values)


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))
