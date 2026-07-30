"""Shared pytest fixtures / helpers for the domain unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import BarSource


@pytest.fixture
def instrument_id() -> InstrumentId:
    return InstrumentId.generate()


@pytest.fixture
def bar_source() -> BarSource:
    return BarSource(
        provider_key="fixture_dev",
        source_batch_id=uuid4(),
        observed_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
    )


def make_bar_source(
    *,
    provider_key: str = "fixture_dev",
    observed_at: datetime | None = None,
    source_batch_id: UUID | None = None,
) -> BarSource:
    """Build a deterministic :class:`BarSource` for tests where a fixture is overkill."""
    return BarSource(
        provider_key=provider_key,
        source_batch_id=source_batch_id or uuid4(),
        observed_at=observed_at
        or datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
    )
