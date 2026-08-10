"""Analytics-owned seam for deterministic factor calculation and market
observations.

This package is the GOV-03 "Analytics-owned seam" referenced in
``docs/ARCHITECTURE-GOVERNANCE.md`` §2 (Analytics) and §6 (current
implementation mapping). The calculator implementation lives in
:mod:`invest_domain.analytics.factor_calculators` (moved from
``invest_domain.research.factor_calculators``) and the Market Observation
domain lives in :mod:`invest_domain.analytics.market_observations` /
:mod:`invest_domain.analytics.market_temperature` so the governance rule
"Analytics owns factor calculation and observations" is satisfied in
code while Research continues to consume the calculated observations as
immutable inputs to an ``EvidencePack``.

The migration is intentionally additive:

* The calculator module keeps the **same** public surface
  (:func:`calculate_market_state_factors` and
  :class:`FactorCalculationResult`).
* ``invest_domain.research.factor_calculators`` is preserved as a thin
  compatibility re-export so existing Research-side imports remain
  valid until the dependent tests / call-sites are migrated.
* The Research ``models`` value objects (``EvidencePack``,
  ``FactorObservation``, ``MarketSnapshot``, ``DataQuality``,
  ``FreshnessStatus``, ``QualityStatus``) remain in
  :mod:`invest_domain.research.models` so this slice does not redesign
  the existing EvidencePack. The Market Observation value objects
  (:class:`MarketObservation`, :class:`MarketObservationSnapshot`) reuse
  :class:`~invest_domain.research.models.QualityStatus` and
  :class:`~invest_domain.research.models.FreshnessStatus` directly; no
  parallel ``ObservationQuality`` enum is introduced.

Re-exports declared by this package:

* :class:`MarketObservation` and :class:`MarketObservationSnapshot` —
  the Analytics-owned, hash-stable observation value objects. These are
  safe to re-export because they only depend on
  :mod:`invest_domain.research.models` (already importable from the
  top-level :mod:`invest_domain` package) and the canonical hash
  primitive. They do NOT pull in
  :mod:`invest_domain.analytics.factor_calculators`, so re-exporting them
  here does not reintroduce the
  ``research.factor_set`` → ``research.__init__`` →
  ``research.factor_calculators`` → ``analytics.factor_calculators``
  cycle that previously prevented the analytics package from being a
  namespace package.

Callers MUST import the calculator directly from
:mod:`invest_domain.analytics.factor_calculators` (the
:data:`__all__` below deliberately does not surface
:func:`calculate_market_state_factors` so that the circular-import risk
remains visible at use-sites).
"""

from .market_observations import MarketObservation, MarketObservationSnapshot

__all__ = ["MarketObservation", "MarketObservationSnapshot"]
