"""DuckDB schema definition for the Phase One structured store."""

from __future__ import annotations

CORE_TABLES = frozenset(
    {
        "agent_runs",
        "corporate_events",
        "document_chunks",
        "eod_bars",
        "fundamentals",
        "ingestion_jobs",
        "instruments",
        "llm_cache",
        "macro_series",
        "memory_items",
        "phase2_registry",
        "report_sections",
        "reports",
        "source_registry",
        "text_documents",
    }
)

CORE_INDEXES = frozenset(
    {
        "idx_agent_runs_report_agent",
        "idx_corporate_events_asset_date",
        "idx_eod_bars_asset_date",
        "idx_fundamentals_asset_period",
        "idx_macro_series_key_date",
        "idx_memory_items_faiss_mapping",
        "idx_memory_items_level_namespace_ts",
        "idx_reports_date_market",
        "idx_text_documents_asset_publish",
    }
)

TABLE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS instruments (
        asset_id             VARCHAR PRIMARY KEY,
        market               VARCHAR NOT NULL,
        ticker               VARCHAR NOT NULL,
        exchange_code        VARCHAR NOT NULL,
        company_name         VARCHAR,
        company_name_en      VARCHAR,
        sector_l1            VARCHAR,
        sector_l2            VARCHAR,
        industry_code        VARCHAR,
        currency             VARCHAR,
        is_active            BOOLEAN DEFAULT TRUE,
        source_primary       VARCHAR NOT NULL,
        source_secondary     VARCHAR,
        listed_date          DATE,
        delisted_date        DATE,
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_factor_universe   VARCHAR,
        p2_strategy_bucket   VARCHAR,
        p2_router_group      VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_registry (
        source_id            VARCHAR PRIMARY KEY,
        source_name          VARCHAR NOT NULL,
        market_scope         VARCHAR NOT NULL,
        source_type          VARCHAR NOT NULL,
        auth_mode            VARCHAR NOT NULL,
        base_url             VARCHAR,
        enabled              BOOLEAN DEFAULT TRUE,
        notes                VARCHAR,
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eod_bars (
        asset_id             VARCHAR NOT NULL,
        trade_date           DATE NOT NULL,
        open                 DOUBLE,
        high                 DOUBLE,
        low                  DOUBLE,
        close                DOUBLE,
        adj_close            DOUBLE,
        volume               DOUBLE,
        turnover             DOUBLE,
        vwap                 DOUBLE,
        source_id            VARCHAR NOT NULL,
        ingestion_ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_feature_blob_json VARCHAR,
        PRIMARY KEY (asset_id, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamentals (
        asset_id               VARCHAR NOT NULL,
        fiscal_period_end      DATE NOT NULL,
        report_type            VARCHAR NOT NULL,
        revenue                DOUBLE,
        gross_profit           DOUBLE,
        operating_income       DOUBLE,
        net_income             DOUBLE,
        eps_basic              DOUBLE,
        total_assets           DOUBLE,
        total_liabilities      DOUBLE,
        shareholders_equity    DOUBLE,
        operating_cash_flow    DOUBLE,
        free_cash_flow         DOUBLE,
        gross_margin           DOUBLE,
        operating_margin       DOUBLE,
        net_margin             DOUBLE,
        roe                    DOUBLE,
        roa                    DOUBLE,
        debt_to_equity         DOUBLE,
        current_ratio          DOUBLE,
        pe_ttm                 DOUBLE,
        pb                     DOUBLE,
        filing_url             VARCHAR,
        source_id              VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_factor_blob_json    VARCHAR,
        PRIMARY KEY (asset_id, fiscal_period_end, report_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS macro_series (
        series_key             VARCHAR NOT NULL,
        region_code            VARCHAR NOT NULL,
        observation_date       DATE NOT NULL,
        indicator_name         VARCHAR NOT NULL,
        value                  DOUBLE,
        unit                   VARCHAR,
        frequency              VARCHAR,
        realtime_start         DATE,
        realtime_end           DATE,
        source_id              VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_regime_feature_json VARCHAR,
        PRIMARY KEY (series_key, observation_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_events (
        event_id               VARCHAR PRIMARY KEY,
        asset_id               VARCHAR,
        market                 VARCHAR NOT NULL,
        event_date             TIMESTAMP NOT NULL,
        event_type             VARCHAR NOT NULL,
        severity               VARCHAR NOT NULL,
        title                  VARCHAR NOT NULL,
        summary                VARCHAR,
        source_document_id     VARCHAR,
        source_id              VARCHAR NOT NULL,
        tags_json              VARCHAR,
        impact_window_days     INTEGER,
        has_document           BOOLEAN DEFAULT FALSE,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_label_json          VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS text_documents (
        document_id            VARCHAR PRIMARY KEY,
        asset_id               VARCHAR,
        market                 VARCHAR NOT NULL,
        doc_type               VARCHAR NOT NULL,
        title                  VARCHAR NOT NULL,
        language               VARCHAR DEFAULT 'en',
        publisher              VARCHAR,
        publish_ts             TIMESTAMP,
        source_id              VARCHAR NOT NULL,
        source_url             VARCHAR,
        raw_text_path          VARCHAR,
        checksum_sha256        VARCHAR,
        metadata_json          VARCHAR,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_label_json          VARCHAR,
        p2_training_split      VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        chunk_id               VARCHAR PRIMARY KEY,
        document_id            VARCHAR NOT NULL,
        asset_id               VARCHAR,
        market                 VARCHAR NOT NULL,
        chunk_index            INTEGER NOT NULL,
        chunk_text             VARCHAR NOT NULL,
        token_count            INTEGER,
        embedding_model        VARCHAR NOT NULL,
        embedding_dim          INTEGER NOT NULL,
        faiss_namespace        VARCHAR NOT NULL,
        faiss_vector_id        BIGINT NOT NULL,
        metadata_json          VARCHAR,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_ranker_features     VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_items (
        memory_id              VARCHAR PRIMARY KEY,
        memory_level           VARCHAR NOT NULL,
        namespace_key          VARCHAR NOT NULL,
        asset_id               VARCHAR,
        effective_ts           TIMESTAMP NOT NULL,
        memory_type            VARCHAR NOT NULL,
        importance_score       DOUBLE DEFAULT 0.5,
        summary_text           VARCHAR NOT NULL,
        source_ref_json        VARCHAR,
        embedding_model        VARCHAR NOT NULL,
        embedding_dim          INTEGER NOT NULL,
        faiss_namespace        VARCHAR NOT NULL,
        faiss_vector_id        BIGINT NOT NULL,
        created_by             VARCHAR NOT NULL,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at             TIMESTAMP,
        p2_reward_hint_json    VARCHAR,
        p2_router_hint_json    VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        run_id                 VARCHAR PRIMARY KEY,
        report_id              VARCHAR,
        agent_name             VARCHAR NOT NULL,
        agent_role             VARCHAR NOT NULL,
        model_name             VARCHAR NOT NULL,
        prompt_template_ver    VARCHAR NOT NULL,
        input_payload_json     VARCHAR NOT NULL,
        retrieved_context_json VARCHAR,
        output_payload_json    VARCHAR,
        status                 VARCHAR NOT NULL,
        started_at             TIMESTAMP NOT NULL,
        finished_at            TIMESTAMP,
        latency_ms             BIGINT,
        prompt_tokens          BIGINT,
        completion_tokens      BIGINT,
        cache_hit              BOOLEAN DEFAULT FALSE,
        error_message          VARCHAR,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_preference_label    VARCHAR,
        p2_reward_score        DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
        report_id              VARCHAR PRIMARY KEY,
        report_date            DATE NOT NULL,
        market_scope           VARCHAR NOT NULL,
        report_type            VARCHAR NOT NULL,
        asset_id               VARCHAR,
        title                  VARCHAR NOT NULL,
        thesis_bull_summary    VARCHAR,
        thesis_bear_summary    VARCHAR,
        risk_summary           VARCHAR,
        final_recommendation   VARCHAR NOT NULL,
        confidence_band        VARCHAR,
        report_markdown        VARCHAR NOT NULL,
        report_json            VARCHAR NOT NULL,
        source_trace_json      VARCHAR,
        status                 VARCHAR NOT NULL,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_strategy_hint_json  VARCHAR,
        p2_signal_stub_json    VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_sections (
        report_id              VARCHAR NOT NULL,
        section_name           VARCHAR NOT NULL,
        section_order          INTEGER NOT NULL,
        section_markdown       VARCHAR NOT NULL,
        citations_json         VARCHAR,
        PRIMARY KEY (report_id, section_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_cache (
        cache_key              VARCHAR PRIMARY KEY,
        provider               VARCHAR NOT NULL,
        model_name             VARCHAR NOT NULL,
        prompt_hash            VARCHAR NOT NULL,
        response_json          VARCHAR NOT NULL,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at             TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
        job_id                 VARCHAR PRIMARY KEY,
        source_id              VARCHAR NOT NULL,
        job_type               VARCHAR NOT NULL,
        market_scope           VARCHAR NOT NULL,
        target_date            DATE,
        status                 VARCHAR NOT NULL,
        started_at             TIMESTAMP,
        finished_at            TIMESTAMP,
        rows_written           BIGINT DEFAULT 0,
        error_message          VARCHAR,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS phase2_registry (
        module_name            VARCHAR PRIMARY KEY,
        api_path               VARCHAR NOT NULL,
        class_path             VARCHAR NOT NULL,
        enabled                BOOLEAN DEFAULT FALSE,
        notes                  VARCHAR,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
)

INDEX_DDL = (
    """
    CREATE INDEX IF NOT EXISTS idx_eod_bars_asset_date
    ON eod_bars (asset_id, trade_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fundamentals_asset_period
    ON fundamentals (asset_id, fiscal_period_end)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_macro_series_key_date
    ON macro_series (series_key, observation_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_corporate_events_asset_date
    ON corporate_events (asset_id, event_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_text_documents_asset_publish
    ON text_documents (asset_id, publish_ts)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_items_level_namespace_ts
    ON memory_items (memory_level, namespace_key, effective_ts)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_faiss_mapping
    ON memory_items (faiss_namespace, faiss_vector_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_runs_report_agent
    ON agent_runs (report_id, agent_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reports_date_market
    ON reports (report_date, market_scope)
    """,
)
