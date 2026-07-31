"""HTTP-specific response contracts for the Phase One API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, field_validator

from src.core.settings import AppEnvironment
from src.models.types import DomainModel
from src.schemas.common import ErrorInfo


class HealthResponse(DomainModel):
    """Safe application health metadata."""

    status: Literal["ok"] = "ok"
    service: Literal["deepinsight-api"] = "deepinsight-api"
    environment: AppEnvironment


class ApiErrorResponse(DomainModel):
    """Unified HTTP error response."""

    error: ErrorInfo


class MemorySnapshotResponse(DomainModel):
    """Safe logical references to one existing local Memory snapshot."""

    snapshot_date: date
    duckdb_artifact: str | None = None
    faiss_artifacts: list[str] = Field(default_factory=list)
    status: Literal["ok"] = "ok"

    @field_validator("duckdb_artifact")
    @classmethod
    def reject_internal_duckdb_path(cls, value: str | None) -> str | None:
        """Reject absolute or nested paths from HTTP output."""

        if value is not None:
            _validate_artifact_name(value)
        return value

    @field_validator("faiss_artifacts")
    @classmethod
    def reject_internal_faiss_paths(cls, values: list[str]) -> list[str]:
        """Reject absolute or nested paths from HTTP output."""

        for value in values:
            _validate_artifact_name(value)
        return values


def _validate_artifact_name(value: str) -> None:
    if not value.strip() or "/" in value or "\\" in value:
        raise ValueError("snapshot artifacts must be safe logical names")
