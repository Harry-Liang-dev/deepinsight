"""Emit a provider-independent ResearchDataBundle capability diagnostic."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path

from src.models.identifiers import AssetId
from src.repositories import (
    DocumentRepository,
    DuckDBDatabase,
    InstrumentRepository,
    MarketDataRepository,
)
from src.schemas.research_data import (
    DataCapability,
    ResearchDataBundleRequest,
    ResearchDataSection,
)
from src.services import ResearchDataBundleService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect canonical data capability coverage."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--asset-id", default="US:AAPL")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build and summarize the canonical Bundle without invoking Agents."""

    args = _parser().parse_args(argv)
    database = DuckDBDatabase(args.database)
    database.bootstrap()
    as_of = datetime.combine(args.as_of, time.max, tzinfo=UTC)
    bundle = ResearchDataBundleService(
        instruments=InstrumentRepository(database),
        market_data=MarketDataRepository(database),
        documents=DocumentRepository(database),
    ).build(
        ResearchDataBundleRequest(
            asset_id=AssetId(args.asset_id),
            as_of=as_of,
            window_start=args.start_date,
            window_end=args.as_of,
            dataset_version="data_layer_diagnostic_v1",
            requested_capabilities=tuple(DataCapability),
        )
    )
    sections = {
        field: getattr(bundle, field)
        for field in (
            "fundamentals",
            "valuation",
            "filings",
            "ohlcv",
            "technical_features",
            "sentiment_evidence",
            "news_evidence",
            "macro_indicators",
            "market_context",
            "industry_sector_context",
        )
    }
    print(
        json.dumps(
            [_summary(name, section) for name, section in sections.items()],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _summary(name: str, section: ResearchDataSection) -> dict[str, object]:
    dates = [item.effective_at.date().isoformat() for item in section.items]
    return {
        "capability": name,
        "status": section.status.value,
        "sources": sorted({item.source.provider_name for item in section.items}),
        "observation_count": section.quality.observation_count,
        "earliest_date": min(dates, default=None),
        "latest_date": max(dates, default=None),
        "freshness": section.freshness.status.value,
        "evidence_count": len(section.items),
        "missing_fields": [item.field_path for item in section.missing_data],
    }


if __name__ == "__main__":
    raise SystemExit(main())
