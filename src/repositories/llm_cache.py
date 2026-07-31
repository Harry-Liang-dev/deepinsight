"""DuckDB Repository for provider-independent LLM cache records."""

from __future__ import annotations

from src.repositories.base import (
    BaseRepository,
    decode_json_object,
    encode_json,
)
from src.repositories.records import LLMCacheRecord

_CACHE_COLUMNS = (
    "cache_key",
    "provider",
    "model_name",
    "prompt_hash",
    "response_json",
    "created_at",
    "expires_at",
)


class LLMCacheRepository(BaseRepository):
    """Persist structured LLM responses without invoking an LLM provider."""

    def put(self, record: LLMCacheRecord) -> None:
        """Insert or replace one cache entry.

        Args:
            record: Validated cache persistence record.
        """

        columns = _CACHE_COLUMNS[:5] + ("expires_at",)
        self._execute(
            f"""
            INSERT INTO llm_cache ({", ".join(columns)})
            VALUES ({_placeholders(len(columns))})
            ON CONFLICT (cache_key) DO UPDATE SET
                provider = excluded.provider,
                model_name = excluded.model_name,
                prompt_hash = excluded.prompt_hash,
                response_json = excluded.response_json,
                created_at = now(),
                expires_at = excluded.expires_at
            """,
            (
                record.cache_key,
                record.provider,
                record.model_name,
                record.prompt_hash,
                encode_json(record.response),
                record.expires_at,
            ),
        )

    def get(self, cache_key: str) -> LLMCacheRecord | None:
        """Return one cache record without applying expiry policy.

        Args:
            cache_key: Deterministic cache identifier.

        Returns:
            The matching record, or ``None``.
        """

        row = self._fetch_one(
            f"""
            SELECT {", ".join(_CACHE_COLUMNS)}
            FROM llm_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        )
        if row is None:
            return None
        values = dict(zip(_CACHE_COLUMNS, row, strict=True))
        raw_response = values.pop("response_json")
        values["response"] = decode_json_object(raw_response)
        return LLMCacheRecord.model_validate(values)


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))
