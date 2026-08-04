"""Provider quality policy registry for DC1-A.

All priorities, reliability scores, and freshness SLAs below are explicit
provisional policy values, not measured provider-quality statistics. The
provisional order is fixture_dev (0), cifangquant (10), akshare (20),
eastmoney (30), sina (40), and tonghuashun (50). Their provisional
reliability scores are 1.00, 0.80, 0.70, 0.60, 0.60, and 0.60; their
freshness SLAs are respectively 0, 1, 1, 1, 1, and 1 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from invest_pipeline.provider_catalog import lookup_provider
from invest_pipeline.provider_routing.datasets import Dataset, required_capability_for
from invest_pipeline.provider_routing.probe import DAILY_BARS_FIELDS


@dataclass(frozen=True, slots=True)
class ProviderDatasetRegistration:
    provider_key: str
    dataset: Dataset
    priority: int
    reliability_score: Decimal
    freshness_sla_days: int
    supported_fields: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str) or not self.provider_key.strip():
            raise ValueError("provider_key must be a non-empty string")
        if not isinstance(self.dataset, Dataset):
            raise ValueError("dataset must be a Dataset instance")
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise ValueError("priority must be a non-negative integer")
        if not isinstance(self.reliability_score, Decimal):
            raise ValueError("reliability_score must be a Decimal")
        if not self.reliability_score.is_finite() or not (
            Decimal("0") <= self.reliability_score <= Decimal("1")
        ):
            raise ValueError("reliability_score must be between 0 and 1")
        if (
            not isinstance(self.freshness_sla_days, int)
            or isinstance(self.freshness_sla_days, bool)
            or self.freshness_sla_days < 0
        ):
            raise ValueError("freshness_sla_days must be a non-negative integer")
        if not isinstance(self.supported_fields, frozenset) or not self.supported_fields:
            raise ValueError("supported_fields must be a non-empty frozenset")
        if any(
            not isinstance(field, str) or not field.strip()
            for field in self.supported_fields
        ):
            raise ValueError("supported_fields must contain non-empty strings")

        declaration = lookup_provider(self.provider_key)
        required_capability = required_capability_for(self.dataset)
        if required_capability not in declaration.capabilities:
            raise ValueError(
                f"provider {self.provider_key!r} does not support dataset "
                f"{self.dataset.value!r}"
            )


def _etf_registration(
    provider_key: str,
    priority: int,
    reliability_score: str,
    freshness_sla_days: int,
) -> ProviderDatasetRegistration:
    return ProviderDatasetRegistration(
        provider_key=provider_key,
        dataset=Dataset.ETF_DAILY_BARS,
        priority=priority,
        reliability_score=Decimal(reliability_score),
        freshness_sla_days=freshness_sla_days,
        supported_fields=DAILY_BARS_FIELDS,
    )


ETF_DAILY_BAR_REGISTRY: tuple[ProviderDatasetRegistration, ...] = (
    _etf_registration("fixture_dev", 0, "1.00", 0),
    _etf_registration("cifangquant", 10, "0.80", 1),
    _etf_registration("akshare", 20, "0.70", 1),
    _etf_registration("eastmoney", 30, "0.60", 1),
    _etf_registration("sina", 40, "0.60", 1),
    _etf_registration("tonghuashun", 50, "0.60", 1),
)


def iter_etf_daily_bar_registrations() -> tuple[ProviderDatasetRegistration, ...]:
    return tuple(
        sorted(
            ETF_DAILY_BAR_REGISTRY,
            key=lambda registration: (registration.priority, registration.provider_key),
        )
    )


__all__ = [
    "ETF_DAILY_BAR_REGISTRY",
    "ProviderDatasetRegistration",
    "iter_etf_daily_bar_registrations",
]
