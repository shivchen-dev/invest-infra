from __future__ import annotations

from dataclasses import dataclass

from invest_domain.research.models import FACTOR_SET_KEY, FACTOR_SET_VERSION


@dataclass(frozen=True, slots=True)
class FactorDefinition:
    key: str
    window: int
    required_closes: int
    required_amounts: int
    unit: str


FACTOR_DEFINITIONS: tuple[FactorDefinition, ...] = (
    FactorDefinition("return_20d", 20, 21, 0, "ratio"),
    FactorDefinition("return_60d", 60, 61, 0, "ratio"),
    FactorDefinition("distance_ma20", 20, 20, 0, "ratio"),
    FactorDefinition("distance_ma60", 60, 60, 0, "ratio"),
    FactorDefinition("realized_volatility_20d", 20, 21, 0, "annualized_ratio"),
    FactorDefinition("max_drawdown_60d", 60, 60, 0, "ratio"),
    FactorDefinition("avg_turnover_amount_20d", 20, 0, 20, "CNY"),
    FactorDefinition("data_completeness_60d", 60, 0, 0, "ratio"),
)
FACTOR_KEYS: tuple[str, ...] = tuple(item.key for item in FACTOR_DEFINITIONS)


def factor_definition(key: str) -> FactorDefinition:
    for definition in FACTOR_DEFINITIONS:
        if definition.key == key:
            return definition
    raise KeyError(key)


__all__ = [
    "FACTOR_DEFINITIONS",
    "FACTOR_KEYS",
    "FACTOR_SET_KEY",
    "FACTOR_SET_VERSION",
    "FactorDefinition",
    "factor_definition",
]
