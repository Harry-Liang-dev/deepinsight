"""Central Phase One domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    """Supported equity markets."""

    CN = "CN"
    HK = "HK"
    US = "US"


class MarketScope(StrEnum):
    """Supported data and report market scopes."""

    CN = "CN"
    HK = "HK"
    US = "US"
    GLOBAL = "GLOBAL"
    MIXED = "MIXED"


class ReportMarketScope(StrEnum):
    """Market scopes accepted by the report API."""

    CN = "CN"
    HK = "HK"
    US = "US"
    MIXED = "MIXED"


class MemoryLevel(StrEnum):
    """Five-level global memory hierarchy."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class ReportType(StrEnum):
    """Phase One report types declared by the report API."""

    SINGLE_ASSET = "single_asset"
    MARKET_DAILY = "market_daily"
    WATCHLIST = "watchlist"
    MACRO_WEEKLY = "macro_weekly"


class DocumentType(StrEnum):
    """Text document categories stored by the data layer."""

    FILING = "filing"
    NEWS = "news"
    RESEARCH = "research"
    MACRO = "macro"
    SOCIAL = "social"
    POLICY = "policy"


class AgentName(StrEnum):
    """Phase One analyst and manager agent names."""

    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    TECHNICAL_TEXT_ANALYST = "technical_text_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    NEWS_EVENT_ANALYST = "news_event_analyst"
    RESEARCH_MANAGER = "research_manager"
    BULL_MANAGER = "bull_manager"
    BEAR_MANAGER = "bear_manager"
    RISK_MANAGER = "risk_manager"


class AgentStatus(StrEnum):
    """Agent or operation result status."""

    OK = "ok"
    ERROR = "error"


class ClaimIntent(StrEnum):
    """Compliance intent carried by one accepted research claim."""

    FACT = "fact"
    THIRD_PARTY_OPINION = "third_party_opinion"
    ANALYTICAL_INFERENCE = "analytical_inference"
    SYSTEM_RECOMMENDATION = "system_recommendation"
    EXECUTION_INSTRUCTION = "execution_instruction"


class TaskStatus(StrEnum):
    """Background job and report lifecycle status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJobType(StrEnum):
    """Supported data ingestion modes."""

    FULL = "full"
    INCREMENTAL = "incremental"
    REPAIR = "repair"


class EventSeverity(StrEnum):
    """Corporate event severity values."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvaluationDimension(StrEnum):
    """Versioned research-report quality dimensions."""

    STRUCTURE_COMPLETENESS = "structure_completeness"
    FACTUAL_CORRECTNESS = "factual_correctness"
    CITATION_COVERAGE = "citation_coverage"
    CITATION_TRACEABILITY = "citation_traceability"
    CONCLUSION_EVIDENCE_CONSISTENCY = "conclusion_evidence_consistency"
    BULL_BEAR_BALANCE = "bull_bear_balance"
    RISK_IDENTIFICATION_QUALITY = "risk_identification_quality"
    UNCERTAINTY_EXPRESSION = "uncertainty_expression"
    TEMPORAL_VALIDITY = "temporal_validity"
    TRADING_INSTRUCTION_COMPLIANCE = "trading_instruction_compliance"
    MISSING_DATA_DISCLOSURE = "missing_data_disclosure"
    READABILITY = "readability"


class EvaluatorKind(StrEnum):
    """Origin of one report-quality check."""

    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"


class EvaluationEvidenceKind(StrEnum):
    """Auditable locator categories used to explain evaluation scores."""

    REPORT_PATH = "report_path"
    SOURCE = "source"
    DIAGNOSTIC = "diagnostic"


class BenchmarkFixtureKind(StrEnum):
    """Redistribution status of one fixed Benchmark source."""

    SYNTHETIC = "synthetic"
    PUBLIC_EXCERPT = "public_excerpt"
    DEIDENTIFIED = "deidentified"


class BenchmarkExpectedOutcome(StrEnum):
    """Expected lifecycle outcome for one Benchmark case."""

    REPORT = "report"
    EXPECTED_FAILURE = "expected_failure"


class BenchmarkRunMode(StrEnum):
    """Network boundary selected for a Benchmark execution."""

    DEFAULT = "default"
    LIVE = "live"
