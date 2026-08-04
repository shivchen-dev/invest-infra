from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from invest_pipeline.provider_quality import (
    ETF_DAILY_BAR_REGISTRY,
    ProviderDatasetRegistration,
    iter_etf_daily_bar_registrations,
)
from invest_pipeline.provider_routing.datasets import Dataset
from invest_pipeline.provider_routing.probe import DAILY_BARS_FIELDS


def registration(**overrides: object) -> ProviderDatasetRegistration:
    values = {
        "provider_key": "fixture_dev",
        "dataset": Dataset.ETF_DAILY_BARS,
        "priority": 0,
        "reliability_score": Decimal("1"),
        "freshness_sla_days": 0,
        "supported_fields": DAILY_BARS_FIELDS,
    }
    values.update(overrides)
    return ProviderDatasetRegistration(**values)  # type: ignore[arg-type]


def test_registry_contains_valid_frozen_entries() -> None:
    assert {entry.provider_key for entry in ETF_DAILY_BAR_REGISTRY} == {
        "fixture_dev",
        "cifangquant",
        "akshare",
        "eastmoney",
        "sina",
        "tonghuashun",
    }
    assert all(entry.dataset is Dataset.ETF_DAILY_BARS for entry in ETF_DAILY_BAR_REGISTRY)
    assert all(entry.supported_fields == DAILY_BARS_FIELDS for entry in ETF_DAILY_BAR_REGISTRY)
    with pytest.raises(FrozenInstanceError):
        ETF_DAILY_BAR_REGISTRY[0].priority = 99  # type: ignore[misc]


def test_registry_iteration_has_stable_policy_order() -> None:
    first = iter_etf_daily_bar_registrations()
    second = iter_etf_daily_bar_registrations()
    assert first == second
    assert [(entry.priority, entry.provider_key) for entry in first] == sorted(
        (entry.priority, entry.provider_key) for entry in ETF_DAILY_BAR_REGISTRY
    )


def test_capability_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not support dataset"):
        registration(provider_key="rsscast")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(KeyError) as exc_info:
        registration(provider_key="unknown")
    assert exc_info.value.args == ("unknown",)


@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")])
def test_invalid_reliability_ranges_are_rejected(score: Decimal) -> None:
    with pytest.raises(ValueError, match="reliability_score"):
        registration(reliability_score=score)


@pytest.mark.parametrize(
    "fields",
    [frozenset(), frozenset({""}), frozenset({"open", " "})],
)
def test_empty_or_blank_supported_fields_are_rejected(fields: frozenset[str]) -> None:
    with pytest.raises(ValueError, match="supported_fields"):
        registration(supported_fields=fields)


@pytest.mark.parametrize("priority", [-1, 1.5, True])
def test_invalid_priority_is_rejected(priority: object) -> None:
    with pytest.raises(ValueError, match="priority"):
        registration(priority=priority)


@pytest.mark.parametrize("sla", [-1, 1.5, True])
def test_invalid_sla_is_rejected(sla: object) -> None:
    with pytest.raises(ValueError, match="freshness_sla_days"):
        registration(freshness_sla_days=sla)
