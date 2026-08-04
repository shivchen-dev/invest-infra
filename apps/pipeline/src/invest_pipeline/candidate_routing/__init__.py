"""Public re-exports for the ``candidate_routing`` bounded context.

The ``candidate_routing`` package composes the dynamic ETF universe
classifier with the existing minimum candidate-pool calculator. The
shadow MVP shipped here is a pure, deterministic application-layer
function that must never write to PostgreSQL, invoke Dagster, call a
provider, or replace the personal candidate pool.
"""

from invest_pipeline.candidate_routing.shadow import (
    DEFAULT_MAX_STALE_DAYS,
    DEFAULT_MINIMUM_FULL_HISTORY_DAYS,
    DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS,
    CandidatePoolShadowError,
    CandidatePoolShadowResult,
    InvalidUniverseThresholdsError,
    route_candidate_pool_shadow,
)

__all__ = [
    "CandidatePoolShadowError",
    "CandidatePoolShadowResult",
    "DEFAULT_MAX_STALE_DAYS",
    "DEFAULT_MINIMUM_FULL_HISTORY_DAYS",
    "DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS",
    "InvalidUniverseThresholdsError",
    "route_candidate_pool_shadow",
]
