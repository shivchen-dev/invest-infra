"""Pure domain builder for the Stage 4C **Limit Sentiment** observation.

This module exposes a single pure aggregator,
:func:`build_limit_sentiment`, that produces a
:class:`MarketObservationSnapshot` bound to one input snapshot id,
one ``as_of_date`` and one ``algorithm_version`` (default
``"1.0.0"``).

The Limit Sentiment v1.0.0 contract publishes three ratios:

* ``limit_up_ratio`` — share of *participants* (normal-trading
  instruments with both ``limit_up_price`` and ``limit_down_price``
  supplied) whose close equals ``limit_up_price`` (touched the
  upper limit). Counted via equality, not ``>=``, so a normal row
  whose close is merely above the upper limit is not mistakenly
  classified as a limit-up touch — that scenario is a data quality
  failure the v1 contract surfaces through PARTIAL/FRESH, not
  through silent miscounting.
* ``limit_down_ratio`` — share of participants whose close equals
  ``limit_down_price`` (touched the lower limit).
* ``limit_touch_unknown_ratio`` — share of *tradable* rows
  (normal-trading instruments, regardless of whether both limit
  prices are supplied) whose touch classification could not be
  determined: either the trading status is ``unknown`` or the
  row is normal-trading but is missing one or both limit prices.
  The ratio is the union of the two "we cannot tell" buckets and
  exists so the operator can see the share of the universe that
  is currently excluded from the up/down counts.

The denominator for ``limit_up_ratio`` and ``limit_down_ratio``
is the **participants** set: normal-trading rows with both
``limit_up_price`` and ``limit_down_price`` supplied. The
denominator for ``limit_touch_unknown_ratio`` is the **tradable**
set: every normal-trading row (with or without both limit
prices). Suspended rows are excluded from both denominators
because they did not trade and therefore cannot have a meaningful
touch classification.

Validation is fail-closed at three levels:

* An empty input sequence produces an ``INVALID / FAILED`` snapshot
  with all three observation values ``None``.
* Inputs whose ``observed_date`` does not match the as-of date are
  rejected and surface as ``INVALID / STALE`` (preserves the
  :mod:`invest_domain.analytics.market_temperature` /
  :mod:`invest_domain.analytics.market_breadth` contract that
  :attr:`FreshnessStatus.STALE` is the only condition that means
  "we know the data is just too old", not "we don't know what's
  wrong").
* Inputs that fail the trading-status / finite-positive-price /
  non-empty-id guards surface as ``INVALID / FAILED``.
* Inputs that contain at least one ``unknown`` trading status or
  at least one normal-trading row that is missing a limit price
  surface as ``PARTIAL / FRESH``: ``limit_up_ratio`` /
  ``limit_down_ratio`` keep their existing v1 semantics (the
  counts are computed only over the participants subset and the
  ratios stay finite), but ``limit_touch_unknown_ratio`` is
  published as ``None`` so the operator can see that the
  classification is partially blind — we never silently fold
  those rows into ``limit_up_ratio`` or ``limit_down_ratio`` and
  we never silently fold them into ``limit_touch_unknown_ratio``
  without a clear upstream gap.

The builder never reads the database, never calls a Provider,
never imports FastAPI / SQLAlchemy / Dagster, and never produces
a buy / sell / stance / thesis opinion. The output is a
deterministic fact snapshot bound to one input snapshot id, one
algorithm version, and one ``scope_key``
(``"ashare_active_universe_v1"`` — mirroring the
:mod:`invest_domain.analytics.market_breadth` and
:mod:`invest_domain.analytics.market_temperature` patterns so a
future Limit Sentiment aggregation can sit alongside its peers in
the same :class:`MarketObservationSnapshot` family without any
collision).

The persistence + API + Bundle-registration slices are **not**
part of this module; they follow the same pattern that
``market_breadth`` and ``market_temperature`` follow. This module
only freezes the contract and the deterministic algorithm.

Backwards compatibility: the Limit Sentiment v1 contract is the
first and only Limit Sentiment algorithm version, so there is no
v0 surface to preserve. The ``LimitSentimentInput`` dataclass
exposes the v1 fields (``instrument_id`` / ``close`` /
``limit_up_price`` / ``limit_down_price`` / ``observed_date`` /
``trading_status`` / ``source_kind`` / ``source_ref``); future
v2 fields would default to ``None`` so existing v1 call-sites
keep working unchanged.
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

LIMIT_UP_RATIO: Final[str] = "limit_up_ratio"
LIMIT_DOWN_RATIO: Final[str] = "limit_down_ratio"
LIMIT_TOUCH_UNKNOWN_RATIO: Final[str] = "limit_touch_unknown_ratio"

_OUTPUT_KEYS: Final[tuple[str, ...]] = (
    LIMIT_DOWN_RATIO,
    LIMIT_TOUCH_UNKNOWN_RATIO,
    LIMIT_UP_RATIO,
)

DEFAULT_SOURCE_KIND: Final[str] = "stock_daily_limit"
DEFAULT_SOURCE_REF: Final[str] = "stage4c_limit_sentiment:1.0.0"


TRADING_STATUS_NORMAL: Final[str] = "normal"
TRADING_STATUS_SUSPENDED: Final[str] = "suspended"
TRADING_STATUS_UNKNOWN: Final[str] = "unknown"
_ALLOWED_TRADING_STATUSES: Final[frozenset[str]] = frozenset(
    {TRADING_STATUS_NORMAL, TRADING_STATUS_SUSPENDED, TRADING_STATUS_UNKNOWN}
)


@dataclass(frozen=True, slots=True)
class LimitSentimentInput:
    """One per-instrument limit-sentiment input handed to the builder.

    The builder is a pure aggregator; the caller is responsible for
    closing the price + ``limit_up_price`` + ``limit_down_price``
    values from the authoritative source (today: a stubbed
    per-stock view; tomorrow: the Stage 4C Price Limit pipeline).
    The builder only cares about three predicates:

    * ``close`` vs ``limit_up_price`` (touched the upper limit);
    * ``close`` vs ``limit_down_price`` (touched the lower limit);
    * the trading status (suspended rows are excluded; ``unknown``
      rows and normal rows that are missing a limit price are
      tracked in ``limit_touch_unknown_ratio``).

    The dataclass is frozen and slots-based so the builder's input
    cannot be mutated mid-flight, and the canonical content hash of
    the parent snapshot stays stable across re-runs.
    """

    instrument_id: UUID | str
    close: Decimal
    observed_date: date
    trading_status: str = TRADING_STATUS_NORMAL
    limit_up_price: Decimal | None = None
    limit_down_price: Decimal | None = None
    source_kind: str = DEFAULT_SOURCE_KIND
    source_ref: str = DEFAULT_SOURCE_REF

    def __post_init__(self) -> None:
        if not str(self.instrument_id).strip():
            raise ValueError("LimitSentimentInput.instrument_id must not be empty")
        if not isinstance(self.observed_date, date):
            raise TypeError(
                "LimitSentimentInput.observed_date must be a date, "
                f"got {type(self.observed_date).__name__}"
            )
        if not self.close.is_finite() or self.close <= 0:
            raise ValueError(
                "LimitSentimentInput.close must be a positive finite Decimal"
            )
        if self.limit_up_price is not None:
            if not isinstance(self.limit_up_price, Decimal):
                raise TypeError(
                    "LimitSentimentInput.limit_up_price must be a Decimal when "
                    f"provided, got {type(self.limit_up_price).__name__}"
                )
            if not self.limit_up_price.is_finite() or self.limit_up_price <= 0:
                raise ValueError(
                    "LimitSentimentInput.limit_up_price must be a positive "
                    "finite Decimal"
                )
        if self.limit_down_price is not None:
            if not isinstance(self.limit_down_price, Decimal):
                raise TypeError(
                    "LimitSentimentInput.limit_down_price must be a Decimal "
                    f"when provided, got {type(self.limit_down_price).__name__}"
                )
            if not self.limit_down_price.is_finite() or self.limit_down_price <= 0:
                raise ValueError(
                    "LimitSentimentInput.limit_down_price must be a positive "
                    "finite Decimal"
                )
        if self.trading_status not in _ALLOWED_TRADING_STATUSES:
            raise ValueError(
                "LimitSentimentInput.trading_status must be one of "
                f"{sorted(_ALLOWED_TRADING_STATUSES)}, got {self.trading_status!r}"
            )


def build_limit_sentiment(
    *,
    input_snapshot_id: UUID | str,
    instruments: Iterable[LimitSentimentInput],
    as_of_date: date,
    algorithm_version: str = _ALGORITHM_VERSION,
) -> MarketObservationSnapshot:
    """Return the Limit Sentiment :class:`MarketObservationSnapshot` for ``as_of_date``.

    The v1.0.0 contract publishes three ratios
    (``limit_up_ratio`` / ``limit_down_ratio`` /
    ``limit_touch_unknown_ratio``). A fully normal-trading
    universe where every row supplies both limit prices produces
    a ``COMPLETE / FRESH`` snapshot; an ``unknown`` trading
    status or a normal row missing a limit price downgrades the
    snapshot to ``PARTIAL / FRESH`` and publishes
    ``limit_touch_unknown_ratio`` as ``None`` (the up / down
    ratios keep their existing semantics over the participants
    subset); an empty input is ``INVALID / FAILED``; a stale
    input is ``INVALID / STALE``. The default
    ``algorithm_version`` is ``"1.0.0"`` so the v1 call-site can
    opt in with no extra kwargs.

    The snapshot is keyed on ``input_snapshot_id`` (the Stage 4A
    Input Snapshot that bound the universe the inputs were
    derived from) plus ``as_of_date`` plus ``algorithm_version``.
    The same inputs always produce the same ``content_hash`` /
    ``snapshot_id`` pair because observations are sorted by
    ``observation_key`` and the parent snapshot sorts /
    canonicalises its children.
    """

    return _build_snapshot(
        input_snapshot_id=input_snapshot_id,
        instruments=instruments,
        as_of_date=as_of_date,
        algorithm_version=algorithm_version,
    )


def _build_snapshot(
    *,
    input_snapshot_id: UUID | str,
    instruments: Iterable[LimitSentimentInput],
    as_of_date: date,
    algorithm_version: str,
) -> MarketObservationSnapshot:
    if not str(input_snapshot_id).strip():
        raise ValueError("input_snapshot_id must not be empty")
    if not isinstance(as_of_date, date):
        raise TypeError(f"as_of_date must be a date, got {type(as_of_date).__name__}")
    if not algorithm_version.strip():
        raise ValueError("algorithm_version must not be empty")

    inputs: tuple[LimitSentimentInput, ...] = tuple(instruments)
    invalid, quality, freshness, has_gap = _validate(inputs, as_of_date)
    if invalid:
        values: dict[str, Decimal | None] = {key: None for key in _OUTPUT_KEYS}
    else:
        (
            limit_up_count,
            limit_down_count,
            participants,
            tradable,
            blind,
        ) = _tally(inputs)
        values = {}
        if participants == 0:
            values[LIMIT_UP_RATIO] = Decimal(0)
            values[LIMIT_DOWN_RATIO] = Decimal(0)
        else:
            values[LIMIT_UP_RATIO] = _clip(limit_up_count / participants)
            values[LIMIT_DOWN_RATIO] = _clip(limit_down_count / participants)
        if tradable == 0:
            values[LIMIT_TOUCH_UNKNOWN_RATIO] = Decimal(0)
        else:
            # Fail-closed: when ANY normal row is missing a limit
            # price OR ANY row has an unknown trading status, the
            # blind-ratio denominator is itself partially blind, so
            # we publish the ratio as None instead of silently
            # counting partial gaps. The participants ratios stay
            # finite because they are conditioned on completeness.
            values[LIMIT_TOUCH_UNKNOWN_RATIO] = (
                _clip(blind / tradable) if not has_gap else None
            )
    observations = tuple(
        MarketObservation(
            observation_key=key,
            value=values[key],
            unit="ratio",
            observed_date=as_of_date,
            source_kind="analytics",
            source_ref=f"limit_sentiment:{algorithm_version}",
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
    inputs: tuple[LimitSentimentInput, ...],
    as_of_date: date,
) -> tuple[bool, QualityStatus, FreshnessStatus, bool]:
    if not inputs:
        return True, QualityStatus.INVALID, FreshnessStatus.FAILED, False
    if any(item.observed_date != as_of_date for item in inputs):
        return True, QualityStatus.INVALID, FreshnessStatus.STALE, False
    has_unknown = any(item.trading_status == TRADING_STATUS_UNKNOWN for item in inputs)
    has_missing_limit = any(
        item.trading_status == TRADING_STATUS_NORMAL
        and (item.limit_up_price is None or item.limit_down_price is None)
        for item in inputs
    )
    has_gap = has_unknown or has_missing_limit
    if has_gap:
        return False, QualityStatus.PARTIAL, FreshnessStatus.FRESH, True
    return False, QualityStatus.COMPLETE, FreshnessStatus.FRESH, False


def _tally(
    inputs: tuple[LimitSentimentInput, ...],
) -> tuple[Decimal, Decimal, int, int, int]:
    """Return counts that drive the three Limit Sentiment ratios.

    The function mirrors :func:`_validate` so the caller can rely
    on the same gap definition: ``blind`` is incremented for
    every row that cannot be classified (``unknown`` trading
    status, or normal-trading row missing a limit price). The
    blind-ratio denominator (tradable) therefore intentionally
    counts normal-trading rows even when they are missing a
    limit price — the operator gets to see the share of the
    universe that is currently excluded from the up/down counts.
    Suspended rows are excluded from both denominators.
    """

    limit_up_count = Decimal(0)
    limit_down_count = Decimal(0)
    participants = 0
    tradable = 0
    blind = 0
    for item in inputs:
        if item.trading_status == TRADING_STATUS_SUSPENDED:
            continue
        if item.trading_status == TRADING_STATUS_UNKNOWN:
            tradable += 1
            blind += 1
            continue
        tradable += 1
        if item.limit_up_price is None or item.limit_down_price is None:
            blind += 1
            continue
        participants += 1
        if item.close == item.limit_up_price:
            limit_up_count += Decimal(1)
        elif item.close == item.limit_down_price:
            limit_down_count += Decimal(1)
    return limit_up_count, limit_down_count, participants, tradable, blind


def _clip(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value)).quantize(
        _QUANTUM, rounding=ROUND_HALF_EVEN
    )


__all__ = [
    "DEFAULT_SOURCE_KIND",
    "DEFAULT_SOURCE_REF",
    "LIMIT_DOWN_RATIO",
    "LIMIT_TOUCH_UNKNOWN_RATIO",
    "LIMIT_UP_RATIO",
    "LimitSentimentInput",
    "TRADING_STATUS_NORMAL",
    "TRADING_STATUS_SUSPENDED",
    "TRADING_STATUS_UNKNOWN",
    "build_limit_sentiment",
]
