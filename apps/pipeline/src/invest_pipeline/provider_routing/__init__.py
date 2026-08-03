"""Provider routing and coverage matrix (PR-05).

PR-05 (see
``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md`` Task 5
/ PR-05) introduces a pure, deterministic provider-routing layer and a
read-only coverage-report model. The increment is intentionally narrow:

* The :mod:`invest_pipeline.provider_routing.datasets` module freezes
  the dataset keys the V2 pipeline cares about and the
  :class:`invest_pipeline.provider_catalog.ProviderCapability` each
  dataset requires.
* The :mod:`invest_pipeline.provider_routing.selection` module exposes
  :func:`select_providers`, a pure function that returns the sorted,
  deterministic subset of provider declarations that satisfy a
  dataset + capability contract, while honouring
  ``enabled_by_default`` and the matrix §5.4 / plan PR-05 "no
  research-only providers for ETF daily bars" rule.
* The :mod:`invest_pipeline.provider_routing.coverage` module exposes
  the :class:`CoverageReport` model and :func:`calculate_coverage`
  calculator. The calculator only normalises in-memory samples; it
  never touches the network, the filesystem or the database, so the
  coverage report is reproducible bit-for-bit from its inputs.
* The :mod:`invest_pipeline.provider_routing.probe` module exposes
  the :func:`build_coverage_samples` pure input builder that
  converts successful provider probe results into the
  :func:`calculate_coverage`-compatible input mapping. The builder
  adds the typed seam an offline probe runner uses to hand
  successful adapter batches back to the read-only coverage
  matrix; it never touches the network, the filesystem or the
  database either.

The package has no Dagster / FastAPI / SQLAlchemy / external SDK
dependency, mirroring the
:mod:`invest_pipeline.provider_catalog` contract. The runtime factory
(:mod:`invest_pipeline.provider_factory`) is intentionally **not**
extended in this increment; PR-05 only adds the routing decision and
the coverage calculator, and leaves the real backfill (plan §3 Task 5
last bullet) for the next PR.
"""

from __future__ import annotations

from invest_pipeline.provider_routing.coverage import (
    CoverageReport,
    DateRangeSample,
    InvalidCoverageSampleError,
    ProviderCoverage,
    SymbolCoverage,
    calculate_coverage,
)
from invest_pipeline.provider_routing.datasets import (
    DATASET_CAPABILITIES,
    Dataset,
    dataset_requires_capability,
    required_capability_for,
)
from invest_pipeline.provider_routing.probe import (
    CALENDAR_FIELDS,
    DAILY_BARS_FIELDS,
    INSTRUMENT_FIELDS,
    NAV_FIELDS,
    CoverageProbeInput,
    CoverageProbeSample,
    build_coverage_samples,
)
from invest_pipeline.provider_routing.selection import (
    NoEligibleProviderError,
    RoutingRequest,
    select_providers,
)

__all__ = [
    "CALENDAR_FIELDS",
    "CoverageProbeInput",
    "CoverageProbeSample",
    "CoverageReport",
    "DATASET_CAPABILITIES",
    "DAILY_BARS_FIELDS",
    "Dataset",
    "DateRangeSample",
    "INSTRUMENT_FIELDS",
    "InvalidCoverageSampleError",
    "NAV_FIELDS",
    "NoEligibleProviderError",
    "ProviderCoverage",
    "RoutingRequest",
    "SymbolCoverage",
    "build_coverage_samples",
    "calculate_coverage",
    "dataset_requires_capability",
    "required_capability_for",
    "select_providers",
]
