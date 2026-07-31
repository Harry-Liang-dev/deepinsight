"""Repositories for Agent execution and ingestion job audit records."""

from __future__ import annotations

from src.repositories.base import (
    BaseRepository,
    decode_json_object,
    encode_json,
    map_row,
)
from src.repositories.records import AgentRunRecord, IngestionJobRecord

_AGENT_RUN_COLUMNS = (
    "run_id",
    "report_id",
    "agent_name",
    "agent_role",
    "model_name",
    "prompt_template_ver",
    "input_payload_json",
    "retrieved_context_json",
    "output_payload_json",
    "status",
    "started_at",
    "finished_at",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "cache_hit",
    "error_message",
    "created_at",
)

_INGESTION_JOB_COLUMNS = (
    "job_id",
    "source_id",
    "job_type",
    "market_scope",
    "target_date",
    "status",
    "started_at",
    "finished_at",
    "rows_written",
    "error_message",
    "created_at",
)


class AgentRunRepository(BaseRepository):
    """Persist auditable Agent invocation state without running an Agent."""

    def save(self, record: AgentRunRecord) -> None:
        """Insert or update one Agent run record.

        Args:
            record: Validated Agent run persistence record.
        """

        columns = _AGENT_RUN_COLUMNS[:-1]
        self._execute(
            f"""
            INSERT INTO agent_runs ({", ".join(columns)})
            VALUES ({_placeholders(len(columns))})
            ON CONFLICT (run_id) DO UPDATE SET
                report_id = excluded.report_id,
                agent_name = excluded.agent_name,
                agent_role = excluded.agent_role,
                model_name = excluded.model_name,
                prompt_template_ver = excluded.prompt_template_ver,
                input_payload_json = excluded.input_payload_json,
                retrieved_context_json = excluded.retrieved_context_json,
                output_payload_json = excluded.output_payload_json,
                status = excluded.status,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                latency_ms = excluded.latency_ms,
                prompt_tokens = excluded.prompt_tokens,
                completion_tokens = excluded.completion_tokens,
                cache_hit = excluded.cache_hit,
                error_message = excluded.error_message
            """,
            (
                record.run_id,
                record.report_id,
                record.agent_name.value,
                record.agent_role,
                record.model_name,
                record.prompt_template_ver,
                encode_json(record.input_payload),
                (
                    None
                    if record.retrieved_context is None
                    else encode_json(record.retrieved_context)
                ),
                (
                    None
                    if record.output_payload is None
                    else encode_json(record.output_payload)
                ),
                record.status,
                record.started_at,
                record.finished_at,
                record.latency_ms,
                record.prompt_tokens,
                record.completion_tokens,
                record.cache_hit,
                record.error_message,
            ),
        )

    def get(self, run_id: str) -> AgentRunRecord | None:
        """Return one Agent run record.

        Args:
            run_id: Stable run identifier.

        Returns:
            The matching record, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_AGENT_RUN_COLUMNS)}
            FROM agent_runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        if row is None:
            return None
        values = dict(zip(_AGENT_RUN_COLUMNS, row, strict=True))
        for persisted, field in (
            ("input_payload_json", "input_payload"),
            ("retrieved_context_json", "retrieved_context"),
            ("output_payload_json", "output_payload"),
        ):
            raw_value = values.pop(persisted)
            values[field] = None if raw_value is None else decode_json_object(raw_value)
        return AgentRunRecord.model_validate(values)


class IngestionJobRepository(BaseRepository):
    """Persist ingestion job lifecycle state without executing ingestion."""

    def save(self, record: IngestionJobRecord) -> None:
        """Insert or update one ingestion job.

        Args:
            record: Validated ingestion job persistence record.
        """

        columns = _INGESTION_JOB_COLUMNS[:-1]
        self._execute(
            f"""
            INSERT INTO ingestion_jobs ({", ".join(columns)})
            VALUES ({_placeholders(len(columns))})
            ON CONFLICT (job_id) DO UPDATE SET
                source_id = excluded.source_id,
                job_type = excluded.job_type,
                market_scope = excluded.market_scope,
                target_date = excluded.target_date,
                status = excluded.status,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                rows_written = excluded.rows_written,
                error_message = excluded.error_message
            """,
            (
                record.job_id,
                record.source_id,
                record.job_type.value,
                record.market_scope.value,
                record.target_date,
                record.status,
                record.started_at,
                record.finished_at,
                record.rows_written,
                record.error_message,
            ),
        )

    def get(self, job_id: str) -> IngestionJobRecord | None:
        """Return one ingestion job record.

        Args:
            job_id: Stable job identifier.

        Returns:
            The matching record, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_INGESTION_JOB_COLUMNS)}
            FROM ingestion_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        )
        return (
            None
            if row is None
            else map_row(IngestionJobRecord, _INGESTION_JOB_COLUMNS, row)
        )


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))
