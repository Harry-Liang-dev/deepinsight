"""Live Stocktwits MCP smoke through canonical storage and Bundle."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from src.adapters import (
    ProviderRecord,
    StocktwitsSentimentProvider,
    build_stocktwits_provider,
    stocktwits_authorization_configured,
)
from src.core import load_settings
from src.models.enums import Market
from src.models.identifiers import AssetId
from src.repositories import DuckDBDatabase, InstrumentRepository, MarketDataRepository
from src.schemas.market_data import InstrumentRecord
from src.schemas.research_data import (
    DataCapability,
    ResearchDataBundleRequest,
)
from src.services import DataNormalizer, ResearchDataBundleService
from src.services.data_normalization import NormalizationError

_ASSET_ID = AssetId("US:AAPL")


def main(
    argv: Sequence[str] | None = None,
    *,
    provider: StocktwitsSentimentProvider | None = None,
) -> int:
    """Fetch AAPL signals and verify canonical persistence and projection."""

    del argv
    settings = load_settings()
    if provider is None:
        if not settings.providers.stocktwits_mcp_enabled:
            return _not_configured("STOCKTWITS_MCP_ENABLED is false")
        if not stocktwits_authorization_configured(settings.providers):
            return _not_configured("authorization required")
        provider = build_stocktwits_provider(settings.providers)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=30)
    try:
        records = list(provider.fetch_sentiment_range((str(_ASSET_ID),), start, end))
        with TemporaryDirectory(prefix="deepinsight-stocktwits-") as directory:
            result = _persist_and_project(
                provider,
                records,
                Path(directory),
                start=start,
                end=end,
            )
    except (NormalizationError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "PROVIDER_ERROR",
                    "symbol": "AAPL",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def _persist_and_project(
    provider: StocktwitsSentimentProvider,
    records: list[ProviderRecord],
    root: Path,
    *,
    start: date,
    end: date,
) -> dict[str, object]:
    database = DuckDBDatabase(root / "stocktwits.duckdb")
    database.bootstrap()
    instruments = InstrumentRepository(database)
    market_data = MarketDataRepository(database)
    instruments.upsert(
        InstrumentRecord(
            asset_id=_ASSET_ID,
            market=Market.US,
            ticker="AAPL",
            exchange_code="NASDAQ",
            company_name="Apple Inc.",
            currency="USD",
            source_primary="instrument_registry",
        )
    )
    normalizer = DataNormalizer()
    received_at = datetime.now(UTC)
    for record in records:
        if record.get("record_type") == "sentiment_snapshot":
            market_data.upsert_sentiment_snapshot(
                normalizer.normalize_sentiment_snapshot(
                    provider.provider_name,
                    record,
                    received_at=received_at,
                )
            )
        elif record.get("record_type") == "sentiment_evidence":
            market_data.upsert_sentiment_evidence(
                normalizer.normalize_sentiment_evidence(
                    provider.provider_name,
                    record,
                    received_at=received_at,
                )
            )
        else:
            raise NormalizationError("unknown Stocktwits canonical record type")
    as_of = datetime.now(UTC) + timedelta(seconds=1)
    snapshots = market_data.list_sentiment_snapshots(
        _ASSET_ID,
        start_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        as_of=as_of,
    )
    messages = market_data.list_sentiment_evidence(
        _ASSET_ID,
        start_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        as_of=as_of,
    )
    bundle = ResearchDataBundleService(
        instruments=instruments,
        market_data=market_data,
    ).build(
        ResearchDataBundleRequest(
            asset_id=_ASSET_ID,
            as_of=as_of,
            window_start=start,
            window_end=end,
            dataset_version="stocktwits_live_smoke_v1",
            requested_capabilities=(
                DataCapability.ASSET_IDENTITY,
                DataCapability.SENTIMENT_EVIDENCE,
            ),
        )
    )
    if not snapshots or not bundle.sentiment_evidence.items:
        raise RuntimeError("canonical Stocktwits sentiment projection is empty")
    if not all(
        item.source.provider_locator for item in bundle.sentiment_evidence.items
    ):
        raise RuntimeError("Stocktwits Bundle source lineage is incomplete")
    current = snapshots[-1]
    message_dates = [record.created_at for record in messages]
    historical = [
        record
        for record in snapshots
        if record.quality == "historical_normalized_signal"
    ]
    return {
        "status": "PASS",
        "sentiment_status": (
            "AVAILABLE"
            if bundle.sentiment_evidence.status.value == "present"
            else bundle.sentiment_evidence.status.value.upper()
        ),
        "symbol": "AAPL",
        "provider": provider.provider_name,
        "available_tool_names": list(provider.available_tools),
        "sentiment_score": current.score,
        "sentiment_label": current.label,
        "current_sentiment_available": current.score is not None,
        "bullish_pct": current.bullish_pct,
        "bearish_pct": current.bearish_pct,
        "message_volume_score": current.message_volume_score,
        "message_count": len(messages),
        "earliest_message_timestamp": (
            min(message_dates).isoformat() if message_dates else None
        ),
        "latest_message_timestamp": (
            max(message_dates).isoformat() if message_dates else None
        ),
        "snapshot_count": len(snapshots),
        "sentiment_history_count": sum(
            record.score is not None for record in historical
        ),
        "message_volume_history_count": sum(
            record.message_volume_score is not None for record in historical
        ),
        "bundle_sentiment_status": bundle.sentiment_evidence.status.value,
        "bundle_evidence_count": len(bundle.sentiment_evidence.items),
        "source_lineage_complete": True,
    }


def _not_configured(reason: str) -> int:
    print(
        json.dumps(
            {
                "status": "NOT_CONFIGURED",
                "provider_status": "NOT_CONFIGURED",
                "message": reason,
            },
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
