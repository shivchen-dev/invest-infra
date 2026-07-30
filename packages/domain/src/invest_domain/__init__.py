"""Public surface of the ``invest_domain`` package.

Re-exports the public domain types grouped by bounded context. Importing
from this module never triggers any infrastructure dependency: the
package is guaranteed to be SQLAlchemy-, Alembic-, FastAPI-, Dagster-
and Provider-SDK-free (see M0-CODING-BRIEF Phase 1-B / scripts/check_architecture.py).
"""

from invest_domain.candidate_pool import (
    CalculationContext,
    CandidatePoolCalculator,
    CandidatePoolItem,
    CandidatePoolPolicy,
    CandidatePoolResult,
    CandidatePoolRun,
    CandidatePoolStatus,
    CandidatePoolSummary,
    EligibilityCriteria,
    ExclusionReason,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    RuleOutcome,
    RuleSeverity,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.instruments import (
    Instrument,
    InstrumentId,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.market_data import (
    Adjust,
    BarSource,
    Currency,
    DailyBar,
    EtfMarketDataProvider,
    Exchange,
    InstrumentProvider,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataContractError,
    TradingStatus,
    bar_source_metadata_hash,
)
from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_domain.shared.canonical import (
    CANONICAL_HASH_SCHEMA_VERSION,
    CanonicalizationError,
    canonical_json,
    canonical_sha256,
    content_hash,
)

__all__ = [
    "Adjust",
    "BarSource",
    "CANONICAL_HASH_SCHEMA_VERSION",
    "CalculationContext",
    "CandidatePoolCalculator",
    "CandidatePoolItem",
    "CandidatePoolPolicy",
    "CandidatePoolResult",
    "CandidatePoolRun",
    "CandidatePoolStatus",
    "CandidatePoolSummary",
    "CanonicalizationError",
    "Currency",
    "DailyBar",
    "EligibilityCriteria",
    "EtfMarketDataProvider",
    "Exchange",
    "ExclusionReason",
    "Instrument",
    "InstrumentId",
    "InstrumentProvider",
    "InstrumentStatus",
    "InstrumentType",
    "LiquidityCriteria",
    "PipelineRun",
    "PipelineRunStatus",
    "PriceQualityCriteria",
    "ProviderBatch",
    "ProviderBatchStatus",
    "ProviderDataContractError",
    "RiskCriteria",
    "RuleOutcome",
    "RuleSeverity",
    "ScoreWeights",
    "SelectionCriteria",
    "TradingStatus",
    "bar_source_metadata_hash",
    "canonical_json",
    "canonical_sha256",
    "content_hash",
]
