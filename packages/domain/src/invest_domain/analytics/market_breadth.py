"""Pure domain builder for the Stage 4B **Market Breadth** observation.

This module is the second Analytics-owned deep module after
:mod:`invest_domain.analytics.market_temperature`. It is intentionally
narrow: a single public entry point — :func:`build_market_breadth` —
that takes one as-of date and a sequence of per-instrument breadth
inputs, and returns a :class:`MarketObservationSnapshot` carrying the
three frozen first-slice breadth observations:

``advancing_ratio``   — fraction of the universe whose ``close >
prev_close`` on the as-of date.

``declining_ratio``   — fraction of the universe whose ``close <
prev_close`` on the as-of date.

``above_ma20_ratio``  — fraction of the universe whose ``close >=
ma20`` on the as-of date (the 20-day simple moving average, supplied
by the caller — the builder is a pure aggregator and never reads raw
bars or env vars).

The builder never reads the database, never calls a Provider, never
imports FastAPI / SQLAlchemy / Dagster, and never produces a buy /
sell / stance / thesis opinion. The output is a deterministic fact
snapshot bound to one input snapshot id, one algorithm version, and
one ``scope_key`` (``"ashare_active_universe_v1"`` — frozen by this
module, mirroring the per-universe scope key pattern used by
:mod:`invest_domain.analytics.market_temperature`).

Validation is fail-closed:

- An empty input sequence produces an ``INVALID / FAILED`` snapshot
  with all observation values ``None`` and a deterministic reason
  string in the content hash.
- Inputs whose ``observed_date`` does not match the as-of date are
  rejected and surface as ``INVALID / STALE`` (preserves the
  ``market_temperature`` contract that ``FreshnessStatus.STALE`` is
  the only condition that means "we know the data is just too old",
  not "we don't know what's wrong").
- Inputs that fail the trading-status / finite-price / non-empty-id
  guards surface as ``INVALID / FAILED``.

The persistence + API + Bundle-registration slices are **not** part
of this module. They will follow the same pattern
``market_temperature`` followed (see migration
``20260810_0015_market_observation_snapshots`` + repository
``SqlAlchemyMarketObservationSnapshotRepository``); this module only
freezes the contract and the deterministic algorithm.

Backwards compatibility: the existing ETF Market Temperature
Evidence / Bundle semantics are intentionally **not** changed. The
new ``scope_key`` is the only constant this module owns — it does
not reuse :data:`market_temperature.SCOPE_KEY` so a future
``MarketBreadth`` aggregation can sit alongside ``MarketTemperature``
in the same :class:`MarketObservationSnapshot` family without any
collision.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final
from uuid import UUID

from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.research.models import FreshnessStatus, QualityStatus

_ALGORITHM_VERSION: Final[str] = "1.0.0"
_SCOPE_TYPE: Final[str] = "ashare_universe"
_SCOPE_KEY: Final[str] = "ashare_active_universe_v1"
_QUANTUM: Final[Decimal] = Decimal("0.00000001")

ADVANCING_RATIO: Final[str] = "advancing_ratio"
DECLINING_RATIO: Final[str] = "declining_ratio"
ABOVE_MA20_RATIO: Final[str] = "above_ma20_ratio"

_OUTPUT_KEYS: Final[tuple[str, ...]] = (
    ADVANCING_RATIO,
    DECLINING_RATIO,
    ABOVE_MA20_RATIO,
)


TRADING_STATUS_NORMAL: Final[str] = "normal"
TRADING_STATUS_SUSPENDED: Final[str] = "suspended"
TRADING_STATUS_UNKNOWN: Final[str] = "unknown"
_ALLOWED_TRADING_STATUSES: Final[frozenset[str]] = frozenset(
    {TRADING_STATUS_NORMAL, TRADING_STATUS_SUSPENDED, TRADING_STATUS_UNKNOWN}
)


@dataclass(frozen=True, slots=True)
class MarketBreadthInput:
    """One per-instrument breadth input handed to :func:`build_market_breadth`.

    The builder is a pure aggregator; the caller is responsible for
    closing the price + ``ma20`` values from the authoritative source
    (today: a stubbed per-stock view; tomorrow: the Stock Daily Bars
    pipeline that Stage 4B Phase 4B-1 explicitly postpones). The
    builder only cares about three predicates:

    - ``close`` vs ``prev_close`` (advancing / declining);
    - ``close`` vs ``ma20`` (above the 20-day moving average);
    - the trading status (suspended instruments are excluded from
      the denominator; ``unknown`` is treated as missing and reduces
      quality_status to ``PARTIAL``).

    The dataclass is frozen and slots-based so the builder's input
    cannot be mutated mid-flight, and the canonical content hash of
    the parent snapshot stays stable across re-runs.
    """

    instrument_id: UUID | str
    close: Decimal
    prev_close: Decimal
    ma20: Decimal
    observed_date: date
    trading_status: str = TRADING_STATUS_NORMAL
    source_kind: str = "stock_daily_bar"
    source_ref: str = "stage4b_breadth:1.0.0"

    def __post_init__(self) -> None:
        if not str(self.instrument_id).strip():
            raise ValueError("MarketBreadthInput.instrument_id must not be empty")
        if not isinstance(self.observed_date, date):
            raise TypeError(
                "MarketBreadthInput.observed_date must be a date, "
                f"got {type(self.observed_date).__name__}"
            )
        if not self.close.is_finite() or self.close <= 0:
            raise ValueError("MarketBreadthInput.close must be a positive finite Decimal")
        if not self.prev_close.is_finite() or self.prev_close <= 0:
            raise ValueError("MarketBreadthInput.prev_close must be a positive finite Decimal")
        if not self.ma20.is_finite() or self.ma20 <= 0:
            raise ValueError("MarketBreadthInput.ma20 must be a positive finite Decimal")
        if self.trading_status not in _ALLOWED_TRADING_STATUSES:
            raise ValueError(
                "MarketBreadthInput.trading_status must be one of "
                f"{sorted(_ALLOWED_TRADING_STATUSES)}, got {self.trading_status!r}"
            )


def build_market_breadth(
    *,
    input_snapshot_id: UUID | str,
    instruments: Iterable[MarketBreadthInput],
    as_of_date: date,
    algorithm_version: str = _ALGORITHM_VERSION,
) -> MarketObservationSnapshot:
    """Return the breadth :class:`MarketObservationSnapshot` for ``as_of_date``.

    The snapshot is keyed on ``input_snapshot_id`` (the Stage 4A
    Input Snapshot that bound the universe the inputs were derived
    from) plus ``as_of_date`` plus ``algorithm_version``. The same
    inputs always produce the same ``content_hash`` /
    ``snapshot_id`` pair because observations are sorted by
    ``observation_key`` and the parent snapshot sorts / canonicalises
    its children.

    Empty input fails closed: the snapshot is published with all
    observation values ``None``, ``quality_status = INVALID`` and
    ``freshness_status = FAILED``. This keeps the read API contract
    — "a snapshot exists iff there is a published row" — while
    surfacing the empty-input case through the quality vocabulary
    instead of swallowing it silently.
    """

    if not str(input_snapshot_id).strip():
        raise ValueError("input_snapshot_id must not be empty")
    if not isinstance(as_of_date, date):
        raise TypeError(f"as_of_date must be a date, got {type(as_of_date).__name__}")
    if not algorithm_version.strip():
        raise ValueError("algorithm_version must not be empty")

    inputs: tuple[MarketBreadthInput, ...] = tuple(instruments)
    invalid, quality, freshness = _validate(inputs, as_of_date)
    if invalid:
        values: dict[str, Decimal | None] = {key: None for key in _OUTPUT_KEYS}
    else:
        advancing, declining, above_ma20, denominator = _tally(inputs)
        if denominator == 0:
            # Defensive: an all-suspended universe is technically
            # valid input (every instrument was filtered out), so
            # we publish three 0.0 ratios rather than fail-closed.
            advancing = Decimal(0)
            declining = Decimal(0)
            above_ma20 = Decimal(0)
        else:
            advancing = _clip(advancing / denominator)
            declining = _clip(declining / denominator)
            above_ma20 = _clip(above_ma20 / denominator)
        values = {
            ADVANCING_RATIO: advancing,
            DECLINING_RATIO: declining,
            ABOVE_MA20_RATIO: above_ma20,
        }
    observations = tuple(
        MarketObservation(
            observation_key=key,
            value=values[key],
            unit="ratio",
            observed_date=as_of_date,
            source_kind="analytics",
            source_ref=f"market_breadth:{algorithm_version}",
            quality_status=quality,
        )
        for key in _OUTPUT_KEYS
    )
    return MarketObservationSnapshot(
        input_snapshot_id=input_snapshot_id,
        as_of_date=as_of_date,
        observations=observations,
        algorithm_version=algorithm_version,
        scope_type=_SCOPE_TYPE,
        scope_key=_SCOPE_KEY,
        quality_status=quality,
        freshness_status=freshness,
    )


def _validate(
    inputs: tuple[MarketBreadthInput, ...],
    as_of_date: date,
) -> tuple[bool, QualityStatus, FreshnessStatus]:
    if not inputs:
        return True, QualityStatus.INVALID, FreshnessStatus.FAILED
    if any(item.observed_date != as_of_date for item in inputs):
        return True, QualityStatus.INVALID, FreshnessStatus.STALE
    if any(item.trading_status == TRADING_STATUS_UNKNOWN for item in inputs):
        return False, QualityStatus.PARTIAL, FreshnessStatus.FRESH
    return False, QualityStatus.COMPLETE, FreshnessStatus.FRESH


def _tally(
    inputs: tuple[MarketBreadthInput, ...],
) -> tuple[Decimal, Decimal, Decimal, int]:
    """Return ``(advancing, declining, above_ma20, denominator)``.

    Suspended instruments are filtered out of the denominator;
    ``unknown`` instruments are also filtered out of the denominator.
    The :func:`_validate` helper promotes the snapshot to
    ``PARTIAL / FRESH`` whenever the input set contains an
    ``unknown`` instrument, so the caller does not need to know
    about the unknown bucket here.
    """

    advancing = Decimal(0)
    declining = Decimal(0)
    above_ma20 = Decimal(0)
    denominator = 0
    for item in inputs:
        if item.trading_status != TRADING_STATUS_NORMAL:
            continue
        if item.close > item.prev_close:
            advancing += Decimal(1)
        elif item.close < item.prev_close:
            declining += Decimal(1)
        if item.close >= item.ma20:
            above_ma20 += Decimal(1)
        denominator += 1
    return advancing, declining, above_ma20, denominator


def _clip(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


__all__ = [
    "ABOVE_MA20_RATIO",
    "ADVANCING_RATIO",
    "DECLINING_RATIO",
    "MarketBreadthInput",
    "TRADING_STATUS_NORMAL",
    "TRADING_STATUS_SUSPENDED",
    "TRADING_STATUS_UNKNOWN",
    "build_market_breadth",
]
