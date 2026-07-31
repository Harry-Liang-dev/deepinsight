"""Shared JSON and Pydantic domain types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class DomainModel(BaseModel):
    """Strict base class for cross-module domain contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
