"""Tests for DuckDB schema bootstrap and transaction boundaries."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.repositories import (
    CORE_INDEXES,
    CORE_TABLES,
    DatabaseInitializationError,
    DuckDBDatabase,
)

EXPECTED_SCHEMA = {
    "instruments": (
        "asset_id",
        "market",
        "ticker",
        "exchange_code",
        "company_name",
        "company_name_en",
        "sector_l1",
        "sector_l2",
        "industry_code",
        "currency",
        "is_active",
        "source_primary",
        "source_secondary",
        "listed_date",
        "delisted_date",
        "created_at",
        "updated_at",
        "p2_factor_universe",
        "p2_strategy_bucket",
        "p2_router_group",
    ),
    "source_registry": (
        "source_id",
        "source_name",
        "market_scope",
        "source_type",
        "auth_mode",
        "base_url",
        "enabled",
        "notes",
        "created_at",
        "updated_at",
    ),
    "eod_bars": (
        "asset_id",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "turnover",
        "vwap",
        "source_id",
        "ingestion_ts",
        "p2_feature_blob_json",
    ),
    "fundamentals": (
        "asset_id",
        "fiscal_period_end",
        "report_type",
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps_basic",
        "total_assets",
        "total_liabilities",
        "shareholders_equity",
        "operating_cash_flow",
        "free_cash_flow",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "debt_to_equity",
        "current_ratio",
        "pe_ttm",
        "pb",
        "filing_url",
        "source_id",
        "ingestion_ts",
        "p2_factor_blob_json",
    ),
    "macro_series": (
        "series_key",
        "region_code",
        "observation_date",
        "indicator_name",
        "value",
        "unit",
        "frequency",
        "realtime_start",
        "realtime_end",
        "source_id",
        "ingestion_ts",
        "p2_regime_feature_json",
    ),
    "corporate_events": (
        "event_id",
        "asset_id",
        "market",
        "event_date",
        "event_type",
        "severity",
        "title",
        "summary",
        "source_document_id",
        "source_id",
        "tags_json",
        "impact_window_days",
        "has_document",
        "created_at",
        "p2_label_json",
    ),
    "text_documents": (
        "document_id",
        "asset_id",
        "market",
        "doc_type",
        "title",
        "language",
        "publisher",
        "publish_ts",
        "source_id",
        "source_url",
        "raw_text_path",
        "checksum_sha256",
        "metadata_json",
        "created_at",
        "p2_label_json",
        "p2_training_split",
    ),
    "document_chunks": (
        "chunk_id",
        "document_id",
        "asset_id",
        "market",
        "chunk_index",
        "chunk_text",
        "token_count",
        "embedding_model",
        "embedding_dim",
        "faiss_namespace",
        "faiss_vector_id",
        "metadata_json",
        "created_at",
        "p2_ranker_features",
    ),
    "memory_items": (
        "memory_id",
        "memory_level",
        "namespace_key",
        "asset_id",
        "effective_ts",
        "memory_type",
        "importance_score",
        "summary_text",
        "source_ref_json",
        "embedding_model",
        "embedding_dim",
        "faiss_namespace",
        "faiss_vector_id",
        "created_by",
        "created_at",
        "expires_at",
        "p2_reward_hint_json",
        "p2_router_hint_json",
    ),
    "agent_runs": (
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
        "p2_preference_label",
        "p2_reward_score",
    ),
    "reports": (
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
        "p2_strategy_hint_json",
        "p2_signal_stub_json",
    ),
    "report_sections": (
        "report_id",
        "section_name",
        "section_order",
        "section_markdown",
        "citations_json",
    ),
    "llm_cache": (
        "cache_key",
        "provider",
        "model_name",
        "prompt_hash",
        "response_json",
        "created_at",
        "expires_at",
    ),
    "ingestion_jobs": (
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
    ),
    "report_jobs": (
        "job_id",
        "request_json",
        "status",
        "report_id",
        "error_json",
        "attempt_count",
        "created_at",
        "started_at",
        "finished_at",
    ),
    "phase2_registry": (
        "module_name",
        "api_path",
        "class_path",
        "enabled",
        "notes",
        "created_at",
    ),
}

EXPECTED_PRIMARY_KEYS = {
    "instruments": ("asset_id",),
    "source_registry": ("source_id",),
    "eod_bars": ("asset_id", "trade_date"),
    "fundamentals": ("asset_id", "fiscal_period_end", "report_type"),
    "macro_series": ("series_key", "observation_date"),
    "corporate_events": ("event_id",),
    "text_documents": ("document_id",),
    "document_chunks": ("chunk_id",),
    "memory_items": ("memory_id",),
    "agent_runs": ("run_id",),
    "reports": ("report_id",),
    "report_sections": ("report_id", "section_name"),
    "llm_cache": ("cache_key",),
    "ingestion_jobs": ("job_id",),
    "report_jobs": ("job_id",),
    "phase2_registry": ("module_name",),
}


@pytest.fixture
def database(tmp_path: Path) -> DuckDBDatabase:
    """Return an initialized isolated DuckDB database."""

    instance = DuckDBDatabase(tmp_path / "database" / "test.duckdb")
    instance.bootstrap()
    return instance


def test_bootstrap_creates_all_tables_and_indexes(
    database: DuckDBDatabase,
) -> None:
    """Bootstrap creates every table and index declared by MASTER_SPEC."""

    with database.connection() as connection:
        tables = {row[0] for row in connection.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """).fetchall()}
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT index_name FROM duckdb_indexes()"
            ).fetchall()
        }

    assert CORE_TABLES <= tables
    assert CORE_INDEXES <= indexes


def test_all_table_columns_and_primary_keys_match_master_spec(
    database: DuckDBDatabase,
) -> None:
    """Every table exposes the exact MASTER_SPEC column and key layout."""

    with database.connection() as connection:
        for table_name, expected_columns in EXPECTED_SCHEMA.items():
            table_info = connection.execute(
                f"PRAGMA table_info('{table_name}')"
            ).fetchall()
            actual_columns = tuple(row[1] for row in table_info)
            primary_keys = tuple(
                row[1]
                for row in sorted(table_info, key=lambda item: item[5])
                if row[5] > 0
            )

            assert actual_columns == expected_columns
            assert primary_keys == EXPECTED_PRIMARY_KEYS[table_name]


def test_bootstrap_is_idempotent_and_preserves_data(
    database: DuckDBDatabase,
) -> None:
    """A repeated bootstrap preserves previously written records."""

    with database.transaction() as connection:
        connection.execute("""
            INSERT INTO source_registry (
                source_id,
                source_name,
                market_scope,
                source_type,
                auth_mode
            )
            VALUES ('source-1', 'Source One', 'US', 'market', 'api_key')
            """)

    database.bootstrap()

    with database.connection() as connection:
        count = connection.execute(
            "SELECT count(*) FROM source_registry WHERE source_id = 'source-1'"
        ).fetchone()

    assert count == (1,)


def test_schema_constraints_defaults_and_reserved_columns(
    database: DuckDBDatabase,
) -> None:
    """Key constraints, defaults, and nullable Phase Two columns are present."""

    with database.connection() as connection:
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info('instruments')").fetchall()
        }
        connection.execute("""
            INSERT INTO source_registry (
                source_id,
                source_name,
                market_scope,
                source_type,
                auth_mode
            )
            VALUES ('source-defaults', 'Defaults', 'GLOBAL', 'macro', 'api_key')
            """)
        defaults = connection.execute("""
            SELECT enabled, created_at, updated_at
            FROM source_registry
            WHERE source_id = 'source-defaults'
            """).fetchone()

    assert columns["asset_id"][5] is True
    assert columns["market"][3] is True
    assert columns["p2_factor_universe"][3] is False
    assert defaults is not None
    assert defaults[0] is True
    assert defaults[1] is not None
    assert defaults[2] is not None


def test_transaction_rolls_back_all_writes_on_constraint_error(
    database: DuckDBDatabase,
) -> None:
    """A failed statement rolls back earlier writes in the transaction."""

    with pytest.raises(duckdb.ConstraintException):
        with database.transaction() as connection:
            connection.execute("""
                INSERT INTO source_registry (
                    source_id,
                    source_name,
                    market_scope,
                    source_type,
                    auth_mode
                )
                VALUES ('rolled-back', 'Valid First Row', 'US', 'market', 'api_key')
                """)
            connection.execute("""
                INSERT INTO source_registry (
                    source_id,
                    source_name,
                    market_scope,
                    source_type,
                    auth_mode
                )
                VALUES ('invalid', NULL, 'US', 'market', 'api_key')
                """)

    with database.connection() as connection:
        count = connection.execute(
            "SELECT count(*) FROM source_registry WHERE source_id = 'rolled-back'"
        ).fetchone()

    assert count == (0,)


def test_bootstrap_reports_invalid_database_target(tmp_path: Path) -> None:
    """Bootstrap translates an invalid file target into a stable error."""

    directory_target = tmp_path / "not-a-database-file"
    directory_target.mkdir()
    database = DuckDBDatabase(directory_target)

    with pytest.raises(DatabaseInitializationError):
        database.bootstrap()
