"""DuckDB persistence for complete report-evaluation audit results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import duckdb
from pydantic import ValidationError

from src.models.types import JsonValue
from src.repositories.base import (
    BaseRepository,
    RepositoryError,
    decode_json_object,
    encode_json,
)
from src.repositories.records import EvaluationRecord
from src.schemas.evaluation import EvaluationResult

_COLUMNS = (
    "evaluation_id",
    "report_id",
    "ruleset_version",
    "judge_model",
    "input_fingerprint",
    "overall_score",
    "deterministic_score",
    "judge_score",
    "result_json",
    "created_at",
)


class EvaluationRepository(BaseRepository):
    """Store immutable versioned evaluation results."""

    def save(self, result: EvaluationResult) -> None:
        """Insert one result without silently replacing an existing audit."""

        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"""
                    INSERT INTO report_evaluations ({", ".join(_COLUMNS)})
                    VALUES ({", ".join("?" for _ in _COLUMNS)})
                    """,
                    (
                        result.evaluation_id,
                        result.report_id,
                        result.ruleset_version,
                        result.judge_model,
                        result.input_fingerprint,
                        result.overall_score,
                        result.deterministic_score,
                        result.judge_score,
                        encode_json(
                            cast(
                                JsonValue,
                                result.model_dump(mode="json"),
                            )
                        ),
                        _utc_naive(result.evaluated_at),
                    ),
                )
        except duckdb.Error as exc:
            raise RepositoryError("failed to save report evaluation") from exc

    def get(self, evaluation_id: str) -> EvaluationResult | None:
        """Return one evaluation and validate duplicated audit columns."""

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_COLUMNS)}
            FROM report_evaluations
            WHERE evaluation_id = ?
            """,
            (evaluation_id,),
        )
        if row is None:
            return None
        values = dict(zip(_COLUMNS, row, strict=True))
        try:
            result = EvaluationResult.model_validate(
                decode_json_object(values.pop("result_json"))
            )
            record = EvaluationRecord.model_validate(
                {
                    **values,
                    "result": result,
                }
            )
        except ValidationError as exc:
            raise RepositoryError("stored evaluation is invalid") from exc
        if (
            record.evaluation_id != result.evaluation_id
            or record.report_id != result.report_id
            or record.ruleset_version != result.ruleset_version
            or record.judge_model != result.judge_model
            or record.input_fingerprint != result.input_fingerprint
            or record.overall_score != result.overall_score
            or record.deterministic_score != result.deterministic_score
            or record.judge_score != result.judge_score
            or _utc_naive(record.created_at) != _utc_naive(result.evaluated_at)
        ):
            raise RepositoryError("stored evaluation audit columns are inconsistent")
        return result


def _utc_naive(value: datetime) -> datetime:
    """Normalize DuckDB ``TIMESTAMP`` and timezone-aware UTC for comparison."""

    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
