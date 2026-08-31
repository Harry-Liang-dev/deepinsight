"""Idempotency and point-in-time tests for closure-data repositories."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.models.enums import MarketScope
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, MarketDataRepository
from src.schemas.market_data import (
    MacroObservationRecord,
    NewsEvidenceRecord,
    SentimentSnapshotRecord,
)

AS_OF = datetime(2026, 8, 10, 20, tzinfo=UTC)


def test_vintages_are_idempotent_and_future_knowledge_is_excluded(
    tmp_path: Path,
) -> None:
    database = DuckDBDatabase(tmp_path / "pit.duckdb")
    database.bootstrap()
    repository = MarketDataRepository(database)
    early = MacroObservationRecord(
        series_key="GDP",
        region_code=MarketScope.US,
        observation_date=date(2026, 4, 1),
        indicator_name="GDP",
        value=100.0,
        unit="Billions",
        frequency="Quarterly",
        realtime_start=date(2026, 7, 30),
        realtime_end=date(2026, 7, 30),
        source_locator="fred:GDP:vintage:2026-07-30",
        source_id="fred",
        ingestion_ts=AS_OF - timedelta(days=1),
    )
    revised = early.model_copy(
        update={
            "value": 105.0,
            "realtime_start": date(2026, 8, 20),
            "realtime_end": date(2026, 8, 20),
            "source_locator": "fred:GDP:vintage:2026-08-20",
            "ingestion_ts": AS_OF + timedelta(days=10),
        }
    )
    repository.upsert_macro_observation(early)
    repository.upsert_macro_observation(early)
    repository.upsert_macro_observation(revised)

    available = repository.list_macro_observations(
        ["GDP"], end_date=date(2026, 8, 10), as_of=AS_OF
    )

    assert [record.value for record in available] == [100.0]
    with database.connection() as connection:
        count = connection.execute(
            "SELECT count(*) FROM macro_series_vintages"
        ).fetchone()
    assert count == (2,)


def test_macro_history_batch_upsert_preserves_point_in_time_vintages(
    tmp_path: Path,
) -> None:
    """Batch persistence retains the same vintage semantics as single writes."""

    database = DuckDBDatabase(tmp_path / "macro-batch.duckdb")
    database.bootstrap()
    repository = MarketDataRepository(database)
    first = MacroObservationRecord(
        series_key="FEDFUNDS",
        region_code=MarketScope.US,
        observation_date=date(2026, 6, 1),
        indicator_name="Federal Funds Rate",
        value=4.25,
        unit="Percent",
        frequency="Monthly",
        realtime_start=date(2026, 7, 1),
        realtime_end=date(2026, 7, 1),
        source_locator="fred:FEDFUNDS:2026-06-01",
        source_id="fred",
        ingestion_ts=AS_OF - timedelta(days=1),
    )
    second = first.model_copy(
        update={
            "observation_date": date(2026, 7, 1),
            "value": 4.0,
            "realtime_start": date(2026, 8, 1),
            "realtime_end": date(2026, 8, 1),
            "source_locator": "fred:FEDFUNDS:2026-07-01",
        }
    )

    repository.upsert_macro_observations([first, second])
    available = repository.list_macro_observations(
        ["FEDFUNDS"], end_date=date(2026, 8, 10), as_of=AS_OF
    )

    assert [item.observation_date for item in available] == [
        first.observation_date,
        second.observation_date,
    ]
    assert [item.value for item in available] == [first.value, second.value]
    assert [item.source_locator for item in available] == [
        first.source_locator,
        second.source_locator,
    ]
    with database.connection() as connection:
        count = connection.execute(
            "SELECT count(*) FROM macro_series_vintages"
        ).fetchone()
    assert count == (2,)


def test_news_and_sentiment_apply_publication_and_ingestion_cutoffs(
    tmp_path: Path,
) -> None:
    database = DuckDBDatabase(tmp_path / "evidence-pit.duckdb")
    database.bootstrap()
    repository = MarketDataRepository(database)
    asset = AssetId("US:AAPL")
    news = NewsEvidenceRecord(
        news_id="news-1",
        asset_id=asset,
        headline="Known headline",
        created_at=AS_OF - timedelta(hours=2),
        source_url="https://publisher.test/1",
        provider="alpaca_market_data",
        original_source="Benzinga",
        source_locator="alpaca:news:1",
        ingestion_ts=AS_OF - timedelta(hours=1),
    )
    future_news = news.model_copy(
        update={
            "news_id": "news-2",
            "created_at": AS_OF + timedelta(hours=1),
            "source_locator": "alpaca:news:2",
        }
    )
    sentiment = SentimentSnapshotRecord(
        asset_id=asset,
        as_of=AS_OF - timedelta(hours=2),
        provider="stocktwits_mcp",
        score=60,
        source_timestamp=AS_OF - timedelta(hours=2),
        quality="current_community_signal",
        source_locator="stocktwits:symbol:AAPL:current",
        ingestion_ts=AS_OF - timedelta(hours=1),
    )
    repository.upsert_news_evidence(news)
    repository.upsert_news_evidence(news)
    repository.upsert_news_evidence(future_news)
    repository.upsert_sentiment_snapshot(sentiment)
    repository.upsert_sentiment_snapshot(sentiment)

    assert [
        record.news_id
        for record in repository.list_news_evidence(
            asset,
            start_at=AS_OF - timedelta(days=1),
            as_of=AS_OF,
        )
    ] == ["news-1"]
    assert (
        len(
            repository.list_sentiment_snapshots(
                asset,
                start_at=AS_OF - timedelta(days=1),
                as_of=AS_OF,
            )
        )
        == 1
    )
