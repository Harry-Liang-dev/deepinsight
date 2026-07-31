"""Common source, error, and task schemas."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from src.models.enums import TaskStatus
from src.models.types import DomainModel, JsonObject


class SourceReference(DomainModel):
    """Traceable reference to a source document, chunk, or provider."""

    document_id: str | None = None
    excerpt_ref: str | None = None
    provider: str | None = None
    source_url: str | None = None

    @model_validator(mode="after")
    def require_reference_value(self) -> Self:
        """Require at least one usable source locator."""

        if not any(
            (
                self.document_id,
                self.excerpt_ref,
                self.provider,
                self.source_url,
            )
        ):
            raise ValueError("at least one source reference value is required")
        return self


class ErrorInfo(DomainModel):
    """Serializable error information shared across module boundaries."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    details: JsonObject | None = None


class TaskStatusResponse(DomainModel):
    """Minimal background task status returned by service boundaries."""

    job_id: str = Field(min_length=1)
    status: TaskStatus
    report_id: str | None = None
    error: ErrorInfo | None = None
