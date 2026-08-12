"""Pure domain builder for the Stage 4B **Market Breadth** observation.

This module exposes two algorithm versions of the same pure
aggregator, both of which produce a
:class:`MarketObservationSnapshot` bound to one input snapshot id,
one ``as_of_date`` and one ``algorithm_version``:

* :func:`build_market_breadth` — **v1** contract: three frozen
  ratios
  (``advancing_ratio`` / ``declining_ratio`` / ``above_ma20_ratio``),
  default algorithm version ``"1.0.0"``. The v1 builder ignores the
  v2 input fields entirely, so a v1 caller (the Stage 4B Market
  Breadth pipeline) that only supplies v1 fields still gets
  ``COMPLETE / FRESH`` for a fully normal-trading universe.
* :func:`build_market_breadth_v2` — **v2** contract: six frozen
  ratios (the v1 trio plus ``above_ma60_ratio`` /
  ``new_high_ratio`` / ``new_low_ratio``), default algorithm
  version ``"2.0.0"``. The v2 builder publishes the affected v2
  ratio as ``None`` and downgrades the snapshot to
  ``PARTIAL / FRESH`` whenever a normal-trading instrument is
  missing any v2 field; the v1 ratios keep their existing
  semantics and any complete v2 ratio is still computed normally.

The shared :class:`MarketBreadthInput` dataclass carries the v1
required fields (``instrument_id`` / ``close`` / ``prev_close`` /
``ma20`` / ``observed_date`` / ``trading_status``) plus three v2
optional fields (``ma60`` / ``is_new_high`` / ``is_new_low``). The
v2 fields default to ``None`` so existing v1 callers stay
unchanged; v2 callers either supply them on every normal-trading
instrument (the v2 ``COMPLETE`` shape) or accept that the
corresponding v2 ratio is published as ``None`` and the snapshot is
downgraded to ``PARTIAL / FRESH``. The dataclass still validates
the v2 fields' types and finite / positive constraints so a
caller cannot smuggle in a non-Decimal / negative / ``NaN`` v2
field by accident.

Validation is fail-closed for both versions:

* An empty input sequence produces an ``INVALID / FAILED`` snapshot
  with all observation values ``None``.
* Inputs whose ``observed_date`` does not match the as-of date are
  rejected and surface as ``INVALID / STALE`` (preserves the
  :mod:`invest_domain.analytics.market_temperature` contract that
  :attr:`FreshnessStatus.STALE` is the only condition that means
  "we know the data is just too old", not "we don't know what's
  wrong").
* Inputs that fail the trading-status / finite-price / non-empty-id
  guards surface as ``INVALID / FAILED``.
* v1: an ``unknown`` trading status downgrades the snapshot to
  ``PARTIAL / FRESH`` (the v1 ratios are still computed from the
  tradable universe).
* v2: an ``unknown`` trading status **or** a v2-missing
  normal-trading instrument downgrades the snapshot to
  ``PARTIAL / FRESH``; only the affected v2 ratio is published as
  ``None`` (the v1 ratios and any complete v2 ratio are still
  computed).

The builder never reads the database, never calls a Provider, never
imports FastAPI / SQLAlchemy / Dagster, and never produces a buy /
sell / stance / thesis opinion. The output is a deterministic fact
snapshot bound to one input snapshot id, one algorithm version, and
one ``scope_key`` (``"ashare_active_universe_v1"`` — frozen by this
module, mirroring the per-universe scope key pattern used by
:mod:`invest_domain.analytics.market_temperature`).

The persistence + API + Bundle-registration slices are **not** part
of this module. They follow the same pattern
``market_temperature`` followed (see migration
``20260810_0015_market_observation_snapshots`` + repository
``SqlAlchemyMarketObservationSnapshotRepository``); this module only
freezes the contract and the deterministic algorithm.

Backwards compatibility: the existing Stage 4B Market Breadth
Evidence / Bundle semantics are intentionally **not** changed. The
v1 ``MarketBreadthInput`` surface (``close`` / ``prev_close`` /
``ma20`` / ``observed_date`` / ``trading_status``) is preserved
verbatim; v2 fields (``ma60`` / ``is_new_high`` / ``is_new_low``)
are additive ``None``-defaulted kwargs so existing v1 call-sites
keep working unchanged. The new ``scope_key`` is the only constant
this module owns — it does not reuse
:data:`market_temperature.SCOPE_KEY` so a future
``MarketBreadth`` aggregation can sit alongside
``MarketTemperature`` in the same
:class:`MarketObservationSnapshot` family without any collision.
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

_V1_ALGORITHM_VERSION: Final[str] = "1.0.0"
_V2_ALGORITHM_VERSION: Final[str] = "2.0.0"
_SCOPE_TYPE: Final[str] = "ashare_universe"
_SCOPE_KEY: Final[str] = "ashare_active_universe_v1"
_QUANTUM: Final[Decimal] = Decimal("0.00000001")

ADVANCING_RATIO: Final[str] = "advancing_ratio"
DECLINING_RATIO: Final[str] = "declining_ratio"
ABOVE_MA20_RATIO: Final[str] = "above_ma20_ratio"
ABOVE_MA60_RATIO: Final[str] = "above_ma60_ratio"
NEW_HIGH_RATIO: Final[str] = "new_high_ratio"
NEW_LOW_RATIO: Final[str] = "new_low_ratio"

_V1_OUTPUT_KEYS: Final[tuple[str, ...]] = (
    ADVANCING_RATIO,
    DECLINING_RATIO,
    ABOVE_MA20_RATIO,
)
_V2_OUTPUT_KEYS: Final[tuple[str, ...]] = (
    ABOVE_MA60_RATIO,
    NEW_HIGH_RATIO,
    NEW_LOW_RATIO,
)
_OUTPUT_KEYS: Final[tuple[str, ...]] = _V1_OUTPUT_KEYS + _V2_OUTPUT_KEYS


TRADING_STATUS_NORMAL: Final[str] = "normal"
TRADING_STATUS_SUSPENDED: Final[str] = "suspended"
TRADING_STATUS_UNKNOWN: Final[str] = "unknown"
_ALLOWED_TRADING_STATUSES: Final[frozenset[str]] = frozenset(
    {TRADING_STATUS_NORMAL, TRADING_STATUS_SUSPENDED, TRADING_STATUS_UNKNOWN}
)


@dataclass(frozen=True, slots=True)
class MarketBreadthInput:
    """One per-instrument breadth input handed to the breadth builders.

    The builder is a pure aggregator; the caller is responsible for
    closing the price + ``ma20`` values from the authoritative source
    (today: a stubbed per-stock view; tomorrow: the Stock Daily Bars
    pipeline that Stage 4B Phase 4B-1 explicitly postpones). The
    v1 builder only cares about three predicates:

    * ``close`` vs ``prev_close`` (advancing / declining);
    * ``close`` vs ``ma20`` (above the 20-day moving average);
    * the trading status (suspended instruments are excluded from
      the denominator; ``unknown`` is treated as missing and reduces
      quality_status to ``PARTIAL``).

    The v2 builder additionally tracks three v2 predicates:

    * ``close`` vs ``ma60`` (above the 60-day moving average);
    * ``is_new_high`` / ``is_new_low`` (52-week new-high / new-low
      flags).

    The v2 fields default to ``None`` so existing v1 callers stay
    compatible. When any normal-trading instrument omits a v2 field
    the corresponding v2 ratio is published as ``None`` and the
    snapshot is downgraded to ``PARTIAL / FRESH``.

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
    ma60: Decimal | None = None
    is_new_high: bool | None = None
    is_new_low: bool | None = None

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
        if self.ma60 is not None:
            if not isinstance(self.ma60, Decimal):
                raise TypeError(
                    "MarketBreadthInput.ma60 must be a Decimal when provided, "
                    f"got {type(self.ma60).__name__}"
                )
            if not self.ma60.is_finite() or self.ma60 <= 0:
                raise ValueError(
                    "MarketBreadthInput.ma60 must be a positive finite Decimal"
                )
        if self.is_new_high is not None and not isinstance(self.is_new_high, bool):
            raise TypeError(
                "MarketBreadthInput.is_new_high must be a bool when provided, "
                f"got {type(self.is_new_high).__name__}"
            )
        if self.is_new_low is not None and not isinstance(self.is_new_low, bool):
            raise TypeError(
                "MarketBreadthInput.is_new_low must be a bool when provided, "
                f"got {type(self.is_new_low).__name__}"
            )
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
    algorithm_version: str = _V1_ALGORITHM_VERSION,
) -> MarketObservationSnapshot:
    """Return the v1 breadth :class:`MarketObservationSnapshot` for ``as_of_date``.

    The v1 contract publishes three ratios
    (``advancing_ratio`` / ``declining_ratio`` / ``above_ma20_ratio``)
    and ignores the v2 input fields entirely. A fully normal-trading
    v1 universe therefore produces a ``COMPLETE / FRESH`` snapshot;
    an ``unknown`` instrument downgrades it to ``PARTIAL / FRESH``;
    an empty input is ``INVALID / FAILED``; a stale input is
    ``INVALID / STALE``. The default ``algorithm_version`` is
    ``"1.0.0"`` so existing v1 call-sites can drop in unchanged.

    The snapshot is keyed on ``input_snapshot_id`` (the Stage 4A
    Input Snapshot that bound the universe the inputs were derived
    from) plus ``as_of_date`` plus ``algorithm_version``. The same
    inputs always produce the same ``content_hash`` /
    ``snapshot_id`` pair because observations are sorted by
    ``observation_key`` and the parent snapshot sorts /
    canonicalises its children.
    """

    return _build_snapshot(
        input_snapshot_id=input_snapshot_id,
        instruments=instruments,
        as_of_date=as_of_date,
        algorithm_version=algorithm_version,
        output_keys=_V1_OUTPUT_KEYS,
        enforce_v2_completeness=False,
    )


def build_market_breadth_v2(
    *,
    input_snapshot_id: UUID | str,
    instruments: Iterable[MarketBreadthInput],
    as_of_date: date,
    algorithm_version: str = _V2_ALGORITHM_VERSION,
) -> MarketObservationSnapshot:
    """Return the v2 breadth :class:`MarketObservationSnapshot` for ``as_of_date``.

    The v2 contract publishes six ratios
    (``advancing_ratio`` / ``declining_ratio`` / ``above_ma20_ratio``
    / ``above_ma60_ratio`` / ``new_high_ratio`` /
    ``new_low_ratio``) and tracks the per-metric v2 completeness
    across the normal-trading universe:

    * When every normal-trading instrument supplies a finite
      positive ``ma60`` / a boolean ``is_new_high`` / a boolean
      ``is_new_low``, the corresponding v2 ratio is computed
      normally and the snapshot is ``COMPLETE / FRESH``.
    * When a normal-trading instrument is missing one of the v2
      fields, the affected v2 ratio is published as ``None`` and
      the snapshot is downgraded to ``PARTIAL / FRESH``. The v1
      ratios and any complete v2 ratio keep their existing
      semantics.
    * ``STALE`` / ``INVALID`` snapshots publish all six ratios as
      ``None`` — the v2 fail-closed contract is identical to the
      v1 fail-closed contract at the matrix level, only the
      number of ratios differs.
    * An all-suspended universe publishes the six ratios as
      ``Decimal("0.00000000")`` — the v2 builder mirrors the v1
      defensive denominator-zero branch (every instrument was
      filtered out) so the snapshot stays auditable in storage.

    The default ``algorithm_version`` is ``"2.0.0"`` so the v2
    call-site can opt in with no extra kwargs.
    """

    return _build_snapshot(
        input_snapshot_id=input_snapshot_id,
        instruments=instruments,
        as_of_date=as_of_date,
        algorithm_version=algorithm_version,
        output_keys=_OUTPUT_KEYS,
        enforce_v2_completeness=True,
    )


def _build_snapshot(
    *,
    input_snapshot_id: UUID | str,
    instruments: Iterable[MarketBreadthInput],
    as_of_date: date,
    algorithm_version: str,
    output_keys: tuple[str, ...],
    enforce_v2_completeness: bool,
) -> MarketObservationSnapshot:
    if not str(input_snapshot_id).strip():
        raise ValueError("input_snapshot_id must not be empty")
    if not isinstance(as_of_date, date):
        raise TypeError(f"as_of_date must be a date, got {type(as_of_date).__name__}")
    if not algorithm_version.strip():
        raise ValueError("algorithm_version must not be empty")

    inputs: tuple[MarketBreadthInput, ...] = tuple(instruments)
    invalid, quality, freshness = _validate(
        inputs,
        as_of_date,
        enforce_v2_completeness=enforce_v2_completeness,
    )
    if invalid:
        values: dict[str, Decimal | None] = {key: None for key in output_keys}
    else:
        (
            advancing,
            declining,
            above_ma20,
            above_ma60,
            new_high,
            new_low,
            denominator,
            v2_complete,
        ) = _tally(inputs)
        if denominator == 0:
            # Defensive: an all-suspended / all-unknown universe is
            # technically valid input (every instrument was filtered
            # out), so we publish 0.0 ratios for both v1 and v2
            # rather than fail-closed.
            values = {key: Decimal(0) for key in output_keys}
        else:
            values = {
                ADVANCING_RATIO: _clip(advancing / denominator),
                DECLINING_RATIO: _clip(declining / denominator),
                ABOVE_MA20_RATIO: _clip(above_ma20 / denominator),
            }
            if enforce_v2_completeness:
                values[ABOVE_MA60_RATIO] = (
                    _clip(above_ma60 / denominator)
                    if v2_complete["ma60"]
                    else None
                )
                values[NEW_HIGH_RATIO] = (
                    _clip(new_high / denominator)
                    if v2_complete["new_high"]
                    else None
                )
                values[NEW_LOW_RATIO] = (
                    _clip(new_low / denominator)
                    if v2_complete["new_low"]
                    else None
                )
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
        for key in output_keys
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
    *,
    enforce_v2_completeness: bool,
) -> tuple[bool, QualityStatus, FreshnessStatus]:
    if not inputs:
        return True, QualityStatus.INVALID, FreshnessStatus.FAILED
    if any(item.observed_date != as_of_date for item in inputs):
        return True, QualityStatus.INVALID, FreshnessStatus.STALE
    has_unknown = any(item.trading_status == TRADING_STATUS_UNKNOWN for item in inputs)
    if has_unknown:
        return False, QualityStatus.PARTIAL, FreshnessStatus.FRESH
    if enforce_v2_completeness:
        has_v2_missing = any(
            item.trading_status == TRADING_STATUS_NORMAL
            and (
                item.ma60 is None
                or item.is_new_high is None
                or item.is_new_low is None
            )
            for item in inputs
        )
        if has_v2_missing:
            return False, QualityStatus.PARTIAL, FreshnessStatus.FRESH
    return False, QualityStatus.COMPLETE, FreshnessStatus.FRESH


def _tally(
    inputs: tuple[MarketBreadthInput, ...],
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    int,
    dict[str, bool],
]:
    """Return v1 counts, v2 counts, denominator, and v2 completeness map.

    Suspended instruments are filtered out of the denominator;
    ``unknown`` instruments are also filtered out of the denominator.
    The :func:`_validate` helper promotes the snapshot to
    ``PARTIAL / FRESH`` whenever the input set contains an
    ``unknown`` instrument (v1 + v2) or a v2-incomplete
    normal-trading instrument (v2 only), so the caller does not
    need to know about those buckets here.

    v2 counts are only accumulated when the corresponding field is
    present on the input. The completeness map reports ``True``
    for a field iff every normal-trading instrument supplied it;
    a ``False`` flag tells the v2 caller to publish ``None``
    instead of the ratio so the v2 gap is visible in the snapshot.
    The v1 caller ignores the v2 counts and the completeness map.
    """

    advancing = Decimal(0)
    declining = Decimal(0)
    above_ma20 = Decimal(0)
    above_ma60 = Decimal(0)
    new_high = Decimal(0)
    new_low = Decimal(0)
    denominator = 0
    ma60_complete = True
    new_high_complete = True
    new_low_complete = True
    for item in inputs:
        if item.trading_status != TRADING_STATUS_NORMAL:
            continue
        if item.close > item.prev_close:
            advancing += Decimal(1)
        elif item.close < item.prev_close:
            declining += Decimal(1)
        if item.close >= item.ma20:
            above_ma20 += Decimal(1)
        if item.ma60 is not None:
            if item.close >= item.ma60:
                above_ma60 += Decimal(1)
        else:
            ma60_complete = False
        if item.is_new_high is not None:
            if item.is_new_high:
                new_high += Decimal(1)
        else:
            new_high_complete = False
        if item.is_new_low is not None:
            if item.is_new_low:
                new_low += Decimal(1)
        else:
            new_low_complete = False
        denominator += 1
    return (
        advancing,
        declining,
        above_ma20,
        above_ma60,
        new_high,
        new_low,
        denominator,
        {
            "ma60": ma60_complete,
            "new_high": new_high_complete,
            "new_low": new_low_complete,
        },
    )


def _clip(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


__all__ = [
    "ABOVE_MA20_RATIO",
    "ABOVE_MA60_RATIO",
    "ADVANCING_RATIO",
    "DECLINING_RATIO",
    "MarketBreadthInput",
    "NEW_HIGH_RATIO",
    "NEW_LOW_RATIO",
    "TRADING_STATUS_NORMAL",
    "TRADING_STATUS_SUSPENDED",
    "TRADING_STATUS_UNKNOWN",
    "build_market_breadth",
    "build_market_breadth_v2",
]
