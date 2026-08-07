from invest_domain.research.canonical import (
    canonical_pack_json,
    compute_item_hash,
    compute_pack_hash,
    item_content_projection,
    make_evidence_id,
    pack_content_projection,
    pack_view,
)
from invest_domain.research.context import (
    CONTEXT_SCHEMA_VERSION,
    ContextItem,
    ContextValueType,
    ResearchContextPack,
    canonical_context_pack_json,
    compute_context_item_hash,
    compute_context_pack_hash,
    context_item_projection,
    context_pack_projection,
)
from invest_domain.research.factor_set import (
    FACTOR_DEFINITIONS,
    FACTOR_KEYS,
    FactorDefinition,
    factor_definition,
)
from invest_domain.research.models import (
    FACTOR_SET_KEY,
    FACTOR_SET_VERSION,
    SCHEMA_VERSION,
    CandidateContext,
    CaseContext,
    DataQuality,
    EvidencePack,
    FactorObservation,
    FactorSetMetadata,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    SourceReference,
)
from invest_domain.research.quality_gate import (
    QualityGateResult,
    QualityGateStatus,
    evaluate_quality_gate,
)
from invest_domain.research.research_case import (
    ResearchCase,
    ResearchCaseStatus,
)
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)
from invest_domain.research.runner import (
    ResearchPlaybook,
    ResearchRunner,
    ResearchRunnerDraft,
    ResearchRunnerFailure,
    complete_research_attempt,
    execute_research_attempt,
    fail_research_attempt,
    start_research_attempt,
)


def __getattr__(name: str):
    """Lazily re-export the Analytics-owned factor calculator.

    The implementation moved to :mod:`invest_domain.analytics.factor_calculators`
    (GOV-03). Importing it eagerly here would create a circular import
    because the calculator pulls in :mod:`invest_domain.research.factor_set`,
    which is re-exported by this same ``__init__``. Deferring the
    resolution to attribute access breaks the cycle while still
    preserving ``invest_domain.research.FactorCalculationResult`` /
    ``invest_domain.research.calculate_market_state_factors`` for
    existing callers and tests.
    """

    if name in {"FactorCalculationResult", "calculate_market_state_factors"}:
        from invest_domain.analytics import factor_calculators as _analytics_fc

        value = getattr(_analytics_fc, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'invest_domain.research' has no attribute {name!r}")


__all__ = [
    "FACTOR_DEFINITIONS",
    "FACTOR_KEYS",
    "FACTOR_SET_KEY",
    "FACTOR_SET_VERSION",
    "SCHEMA_VERSION",
    "CONTEXT_SCHEMA_VERSION",
    "CandidateContext",
    "ContextItem",
    "ContextValueType",
    "CaseContext",
    "DataQuality",
    "EvidencePack",
    "FactorCalculationResult",
    "FactorDefinition",
    "FactorObservation",
    "FactorSetMetadata",
    "FreshnessStatus",
    "InstrumentSnapshot",
    "MarketSnapshot",
    "QualityGateResult",
    "QualityGateStatus",
    "QualityStatus",
    "ResearchCase",
    "ResearchCaseStatus",
    "ResearchPlaybook",
    "ResearchResult",
    "ResearchRunner",
    "ResearchRunnerDraft",
    "ResearchRunnerFailure",
    "ResearchRun",
    "ResearchRunStatus",
    "complete_research_attempt",
    "execute_research_attempt",
    "fail_research_attempt",
    "start_research_attempt",
    "ResearchContextPack",
    "SourceReference",
    "calculate_market_state_factors",
    "canonical_pack_json",
    "canonical_context_pack_json",
    "compute_item_hash",
    "compute_pack_hash",
    "compute_context_item_hash",
    "compute_context_pack_hash",
    "evaluate_quality_gate",
    "factor_definition",
    "item_content_projection",
    "context_item_projection",
    "context_pack_projection",
    "make_evidence_id",
    "pack_content_projection",
    "pack_view",
]
