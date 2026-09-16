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
        "macro_series_vintages",
        "memory_items",
        "news_evidence",
        "phase2_registry",
        "report_evaluations",
        "report_jobs",
        "report_sections",
        "reports",
        "research_dataset_samples",
        "research_scopes",
        "sector_edges",
        "sector_benchmark_mappings",
        "sector_memberships",
        "sector_nodes",
        "sector_universe_snapshots",
        "sector_research_snapshots",
        "sector_macro_snapshots",
        "sector_anomaly_events",
        "sector_anomaly_scopes",
        "source_registry",
        "sentiment_evidence",
        "sentiment_snapshots",
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
        "idx_macro_vintages_key_date",
        "idx_memory_items_faiss_mapping",
        "idx_memory_items_level_namespace_ts",
        "idx_reports_date_market",
        "idx_report_evaluations_report_created",
        "idx_report_jobs_status_created",
        "idx_research_dataset_asset_as_of",
        "idx_research_scopes_parent",
        "idx_sector_edges_source_target",
        "idx_sector_benchmarks_time",
        "idx_sector_memberships_asset_time",
        "idx_sector_nodes_type_time",
        "idx_sector_universe_as_of",
        "idx_sector_research_as_of",
        "idx_sector_macro_as_of",
        "idx_sector_anomalies_sector_time",
        "idx_sector_anomaly_scopes_scope",
        "idx_text_documents_asset_publish",
        "idx_news_evidence_asset_created",
        "idx_sentiment_snapshots_asset_time",
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
        feed_identity        VARCHAR,
        coverage_scope       VARCHAR,
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
        current_assets         DOUBLE,
        total_liabilities      DOUBLE,
        current_liabilities    DOUBLE,
        total_debt             DOUBLE,
        shareholders_equity    DOUBLE,
        operating_cash_flow    DOUBLE,
        shares_outstanding     DOUBLE,
        free_cash_flow         DOUBLE,
        revenue_yoy            DOUBLE,
        net_income_yoy         DOUBLE,
        gross_margin           DOUBLE,
        operating_margin       DOUBLE,
        net_margin             DOUBLE,
        roe                    DOUBLE,
        roa                    DOUBLE,
        debt_to_equity         DOUBLE,
        current_ratio          DOUBLE,
        eps_ttm                DOUBLE,
        book_value_per_share   DOUBLE,
        market_cap             DOUBLE,
        pe_ttm                 DOUBLE,
        pb                     DOUBLE,
        earnings_yield         DOUBLE,
        source_locator         VARCHAR,
        quality                VARCHAR,
        filing_url             VARCHAR,
        filing_date            DATE,
        accepted_at            TIMESTAMP,
        source_id              VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        p2_factor_blob_json    VARCHAR,
        PRIMARY KEY (asset_id, fiscal_period_end, report_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS macro_series_vintages (
        series_key             VARCHAR NOT NULL,
        region_code            VARCHAR NOT NULL,
        observation_date       DATE NOT NULL,
        indicator_name         VARCHAR NOT NULL,
        value                  DOUBLE,
        unit                   VARCHAR,
        frequency              VARCHAR,
        realtime_start         DATE NOT NULL,
        realtime_end           DATE NOT NULL,
        source_locator         VARCHAR,
        source_id              VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (
            series_key,
            observation_date,
            realtime_start,
            realtime_end
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_snapshots (
        asset_id               VARCHAR NOT NULL,
        as_of                  TIMESTAMP NOT NULL,
        provider               VARCHAR NOT NULL,
        score                  DOUBLE,
        label                  VARCHAR,
        bullish_pct            DOUBLE,
        bearish_pct            DOUBLE,
        message_volume_score   DOUBLE,
        message_volume_label   VARCHAR,
        source_timestamp       TIMESTAMP NOT NULL,
        quality                VARCHAR NOT NULL,
        source_locator         VARCHAR NOT NULL,
        evidence_class         VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP NOT NULL,
        PRIMARY KEY (asset_id, source_timestamp, provider)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_evidence (
        source                  VARCHAR NOT NULL,
        message_id             VARCHAR NOT NULL,
        asset_id               VARCHAR NOT NULL,
        created_at             TIMESTAMP NOT NULL,
        text                   VARCHAR NOT NULL,
        declared_sentiment     VARCHAR,
        source_locator         VARCHAR NOT NULL,
        evidence_class         VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP NOT NULL,
        PRIMARY KEY (source, message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_evidence (
        news_id                VARCHAR PRIMARY KEY,
        asset_id               VARCHAR NOT NULL,
        headline               VARCHAR NOT NULL,
        summary                VARCHAR,
        content                VARCHAR,
        author                 VARCHAR,
        created_at             TIMESTAMP NOT NULL,
        updated_at             TIMESTAMP,
        source_url             VARCHAR NOT NULL,
        provider               VARCHAR NOT NULL,
        original_source        VARCHAR NOT NULL,
        source_locator         VARCHAR NOT NULL,
        ingestion_ts           TIMESTAMP NOT NULL
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
        source_locator         VARCHAR,
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
        metadata_json          VARCHAR,
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
    CREATE TABLE IF NOT EXISTS report_evaluations (
        evaluation_id          VARCHAR PRIMARY KEY,
        report_id              VARCHAR NOT NULL,
        ruleset_version        VARCHAR NOT NULL,
        judge_model            VARCHAR NOT NULL,
        input_fingerprint      VARCHAR NOT NULL,
        overall_score          DOUBLE NOT NULL,
        deterministic_score    DOUBLE NOT NULL,
        judge_score            DOUBLE NOT NULL,
        result_json            VARCHAR NOT NULL,
        created_at             TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_jobs (
        job_id                 VARCHAR PRIMARY KEY,
        request_json           VARCHAR NOT NULL,
        status                 VARCHAR NOT NULL,
        report_id              VARCHAR,
        error_json             VARCHAR,
        attempt_count          INTEGER DEFAULT 0,
        created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at             TIMESTAMP,
        finished_at            TIMESTAMP
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
    CREATE TABLE IF NOT EXISTS research_dataset_samples (
        sample_id               VARCHAR PRIMARY KEY,
        asset_id               VARCHAR NOT NULL,
        market                 VARCHAR NOT NULL,
        research_as_of         TIMESTAMP NOT NULL,
        research_state_id      VARCHAR NOT NULL,
        research_episode_id    VARCHAR NOT NULL,
        data_snapshot_id       VARCHAR NOT NULL,
        sector_context_id      VARCHAR,
        attribution_bundle_id  VARCHAR,
        quality_status         VARCHAR NOT NULL,
        label_status           VARCHAR NOT NULL,
        dataset_schema_version VARCHAR NOT NULL,
        dataset_build_version  VARCHAR NOT NULL,
        input_fingerprint      VARCHAR NOT NULL,
        sample_json            VARCHAR NOT NULL,
        created_at             TIMESTAMP NOT NULL,
        UNIQUE (research_episode_id, dataset_build_version)
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
    CREATE TABLE IF NOT EXISTS sector_nodes (
        node_id                 VARCHAR NOT NULL,
        node_type               VARCHAR NOT NULL,
        name                    VARCHAR NOT NULL,
        sector_id               VARCHAR,
        chain_id                VARCHAR,
        asset_id                VARCHAR,
        description             VARCHAR,
        status                  VARCHAR NOT NULL,
        valid_from              DATE NOT NULL,
        valid_to                DATE,
        source                  VARCHAR NOT NULL,
        version                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (node_id, version, valid_from),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_edges (
        edge_id                 VARCHAR NOT NULL,
        source_node_id          VARCHAR NOT NULL,
        target_node_id          VARCHAR NOT NULL,
        edge_type               VARCHAR NOT NULL,
        confidence              DOUBLE NOT NULL,
        source                  VARCHAR NOT NULL,
        valid_from              DATE NOT NULL,
        valid_to                DATE,
        version                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (edge_id, version, valid_from),
        CHECK (source_node_id <> target_node_id),
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_memberships (
        asset_id                VARCHAR NOT NULL,
        sector_id               VARCHAR NOT NULL,
        chain_ids_json          VARCHAR NOT NULL,
        role                    VARCHAR NOT NULL,
        valid_from              DATE NOT NULL,
        valid_to                DATE,
        weight                  DOUBLE NOT NULL,
        confidence              DOUBLE NOT NULL,
        source                  VARCHAR NOT NULL,
        version                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (asset_id, sector_id, role, valid_from, version),
        CHECK (weight >= 0 AND weight <= 1),
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS research_scopes (
        scope_id                VARCHAR NOT NULL,
        scope_type              VARCHAR NOT NULL,
        parent_scope_id         VARCHAR,
        name                    VARCHAR NOT NULL,
        valid_from              DATE NOT NULL,
        valid_to                DATE,
        version                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (scope_id, version, valid_from),
        CHECK (scope_id <> parent_scope_id),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_benchmark_mappings (
        sector_id               VARCHAR NOT NULL,
        benchmark_ids_json      VARCHAR NOT NULL,
        status                  VARCHAR NOT NULL,
        source                  VARCHAR NOT NULL,
        valid_from              DATE NOT NULL,
        valid_to                DATE,
        version                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (sector_id, version, valid_from),
        CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_universe_snapshots (
        snapshot_id             VARCHAR PRIMARY KEY,
        sector_id               VARCHAR NOT NULL,
        as_of                   DATE NOT NULL,
        asset_ids_json          VARCHAR NOT NULL,
        benchmark_ids_json      VARCHAR NOT NULL,
        membership_version      VARCHAR NOT NULL,
        source                  VARCHAR NOT NULL,
        coverage_json           VARCHAR NOT NULL,
        quality                 VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (sector_id, as_of, membership_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_research_snapshots (
        snapshot_id             VARCHAR PRIMARY KEY,
        sector_id               VARCHAR NOT NULL,
        as_of                   DATE NOT NULL,
        market_state_json       VARCHAR NOT NULL,
        breadth_state_json      VARCHAR NOT NULL,
        fundamental_state_json  VARCHAR NOT NULL,
        valuation_state_json    VARCHAR NOT NULL,
        coverage_json           VARCHAR NOT NULL,
        source_ids_json         VARCHAR NOT NULL,
        feature_version         VARCHAR NOT NULL,
        status                  VARCHAR NOT NULL,
        created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (sector_id, as_of, feature_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_macro_snapshots (
        snapshot_id                 VARCHAR PRIMARY KEY,
        sector_id                   VARCHAR NOT NULL,
        as_of                       DATE NOT NULL,
        cycle_state_json            VARCHAR NOT NULL,
        macro_sensitivity_json      VARCHAR NOT NULL,
        source_sector_snapshot_id   VARCHAR NOT NULL,
        feature_version             VARCHAR NOT NULL,
        status                      VARCHAR NOT NULL,
        created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (sector_id, as_of, feature_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_anomaly_events (
        event_id                    VARCHAR PRIMARY KEY,
        event_type                  VARCHAR NOT NULL,
        sector_id                  VARCHAR NOT NULL,
        chain_ids_json              VARCHAR NOT NULL,
        source_asset_ids_json       VARCHAR NOT NULL,
        affected_asset_ids_json     VARCHAR NOT NULL,
        direction                   VARCHAR NOT NULL,
        severity                    VARCHAR NOT NULL,
        confidence                  DOUBLE NOT NULL,
        event_time                  TIMESTAMP NOT NULL,
        published_at                TIMESTAMP NOT NULL,
        available_at                TIMESTAMP NOT NULL,
        ingested_at                 TIMESTAMP NOT NULL,
        as_of                       TIMESTAMP NOT NULL,
        source_evidence_ids_json    VARCHAR NOT NULL,
        summary                     VARCHAR NOT NULL,
        propagation_hypothesis      VARCHAR,
        status                      VARCHAR NOT NULL,
        version                     VARCHAR NOT NULL,
        created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CHECK (confidence >= 0 AND confidence <= 1),
        CHECK (available_at <= as_of),
        CHECK (ingested_at <= as_of)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_anomaly_scopes (
        event_id                    VARCHAR NOT NULL,
        scope_id                    VARCHAR NOT NULL,
        PRIMARY KEY (event_id, scope_id)
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
    "ALTER TABLE eod_bars ADD COLUMN IF NOT EXISTS feed_identity VARCHAR",
    "ALTER TABLE eod_bars ADD COLUMN IF NOT EXISTS coverage_scope VARCHAR",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS shares_outstanding DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS filing_date DATE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS current_assets DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS current_liabilities DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS total_debt DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS revenue_yoy DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS net_income_yoy DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS eps_ttm DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS book_value_per_share DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS market_cap DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS earnings_yield DOUBLE",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS source_locator VARCHAR",
    "ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS quality VARCHAR",
    "ALTER TABLE macro_series ADD COLUMN IF NOT EXISTS source_locator VARCHAR",
    "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS metadata_json VARCHAR",
    """
    ALTER TABLE macro_series_vintages
    ADD COLUMN IF NOT EXISTS source_locator VARCHAR
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
    CREATE INDEX IF NOT EXISTS idx_macro_vintages_key_date
    ON macro_series_vintages (series_key, observation_date, realtime_start)
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
    CREATE INDEX IF NOT EXISTS idx_news_evidence_asset_created
    ON news_evidence (asset_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sentiment_snapshots_asset_time
    ON sentiment_snapshots (asset_id, source_timestamp)
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
    """
    CREATE INDEX IF NOT EXISTS idx_report_evaluations_report_created
    ON report_evaluations (report_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_report_jobs_status_created
    ON report_jobs (status, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_research_dataset_asset_as_of
    ON research_dataset_samples (asset_id, research_as_of)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_nodes_type_time
    ON sector_nodes (node_type, valid_from, valid_to)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_edges_source_target
    ON sector_edges (source_node_id, target_node_id, valid_from, valid_to)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_memberships_asset_time
    ON sector_memberships (asset_id, valid_from, valid_to)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_research_scopes_parent
    ON research_scopes (parent_scope_id, valid_from, valid_to)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_benchmarks_time
    ON sector_benchmark_mappings (sector_id, valid_from, valid_to)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_universe_as_of
    ON sector_universe_snapshots (sector_id, as_of)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_research_as_of
    ON sector_research_snapshots (sector_id, as_of)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_macro_as_of
    ON sector_macro_snapshots (sector_id, as_of)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_anomalies_sector_time
    ON sector_anomaly_events (sector_id, available_at, as_of)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sector_anomaly_scopes_scope
    ON sector_anomaly_scopes (scope_id, event_id)
    """,
)
