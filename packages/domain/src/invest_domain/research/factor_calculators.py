"""Compatibility shim for the GOV-03 Analytics-owned seam (DEPRECATED import).

The implementation moved to :mod:`invest_domain.analytics.factor_calculators`
as part of the architecture-governance convergence (GOV-03, see
``docs/ARCHITECTURE-GOVERNANCE.md`` §2 and §6). This module is preserved
as a thin re-export so existing Research-side callers continue to work
without modification. New code MUST import from
``invest_domain.analytics.factor_calculators`` directly.

Only :func:`calculate_market_state_factors` and
:class:`FactorCalculationResult` are re-exported; the helpers and
private data classes stay private to the analytics module.
"""

from __future__ import annotations

from invest_domain.analytics.factor_calculators import (
    FactorCalculationResult,
    calculate_market_state_factors,
)

__all__ = ["FactorCalculationResult", "calculate_market_state_factors"]