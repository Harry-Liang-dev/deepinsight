"""Canonical cross-market security identifiers."""

from __future__ import annotations

import re

from pydantic import RootModel, field_validator

from src.models.enums import Market

_ASSET_ID_PATTERNS = (
    re.compile(r"^CN:\d{6}\.(?:SH|SZ)$"),
    re.compile(r"^HK:\d{4,5}\.HK$"),
    re.compile(r"^US:[A-Z][A-Z0-9.-]*$"),
)


class AssetId(RootModel[str]):
    """Validated canonical security identifier."""

    @field_validator("root")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        """Validate a canonical CN, HK, or US security identifier.

        Args:
            value: Candidate canonical security identifier.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the identifier does not match a supported format.
        """

        if not any(pattern.fullmatch(value) for pattern in _ASSET_ID_PATTERNS):
            raise ValueError("invalid canonical asset_id")
        return value

    @property
    def market(self) -> Market:
        """Return the market encoded by the identifier."""

        return Market(self.root.split(":", maxsplit=1)[0])

    def __str__(self) -> str:
        """Return the canonical string form."""

        return self.root
