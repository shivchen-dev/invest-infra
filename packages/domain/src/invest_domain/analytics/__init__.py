"""Analytics-owned seam for deterministic factor calculation.

This package is the GOV-03 "Analytics-owned seam" referenced in
``docs/ARCHITECTURE-GOVERNANCE.md`` §2 (Analytics) and §6 (current
implementation mapping). The calculator implementation moves here from
``invest_domain.research.factor_calculators`` so the governance rule
"Analytics owns factor calculation and observations" is satisfied in
code while Research continues to consume the calculated observations
as immutable inputs to an ``EvidencePack``.

The migration is intentionally additive:

* The moved module keeps the **same** public surface
  (:func:`calculate_market_state_factors` and
  :class:`FactorCalculationResult`).
* ``invest_domain.research.factor_calculators`` is preserved as a thin
  compatibility re-export so existing Research-side imports remain
  valid until the dependent tests / call-sites are migrated.
* The Research ``models`` value objects (``FactorObservation``,
  ``MarketSnapshot``, ``DataQuality``, ``FreshnessStatus``,
  ``QualityStatus``) are still consumed by the calculator; they remain
  in :mod:`invest_domain.research.models` so this slice does not
  redesign the EvidencePack.

Callers MUST import from :mod:`invest_domain.analytics.factor_calculators`
directly (this package deliberately exposes no re-exports to avoid the
circular-import cycle the calculator would otherwise create through
``research.factor_set`` -> ``research.__init__`` -> ``research.factor_calculators``
-> ``analytics.factor_calculators``).
"""