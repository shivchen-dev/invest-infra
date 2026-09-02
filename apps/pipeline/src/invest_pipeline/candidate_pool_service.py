"""Pipeline application service for the personal candidate pool (PR-3 slice 1).

The module implements the smallest complete ``Pipeline`` application-service
slice for the personal Candidate Pool vertical slice:

* Load a versioned personal Candidate Pool policy from YAML.
* Resolve the requested :class:`InputSnapshot` by id (or fail clearly).
* Read only the requested ``trade_date``'s latest daily bars with
  ``Adjust.NONE``.
* Reconstruct persisted bars through the domain :class:`DailyBar` model
  so the domain invariants are re-applied before the calculator runs.
* Compute the deterministic
  :func:`~invest_domain.candidate_pool.fingerprint.compute_market_data_fingerprint`
  over the exact selected bar revisions so the run can be bound to its
  market-data identity. The helper supports an empty bar selection so a
  ``no_data`` trade day still produces a stable, valid fingerprint.
* Run the existing
  :class:`DefaultMinimumCandidatePoolCalculator` (no new business rules).
* Persist one :class:`CandidatePoolRun` and all :class:`CandidatePoolItem`
  rows in one UnitOfWork.
* Verify the inserted item count matches the calculator result count.
* Transition the run ``CALCULATED -> VALIDATED -> PUBLISHED`` through
  the existing repository state machine, using timezone-aware UTC
  timestamps for the terminal transition.

Run identity uses the six-part natural unique key
``(trade_date, algorithm_key, algorithm_version, parameter_hash,
input_snapshot_id, market_data_fingerprint)``. Behaviour is safe by
construction: an idempotent rerun with the exact same selected bar
revisions reuses the existing ``PUBLISHED`` row (the database unique
constraint never fires); a re-run that observes a changed selected bar
revision, or any bar that was previously missing for the same snapshot
and policy, gets a fresh fingerprint and therefore a new immutable
``CandidatePoolRun`` row instead of overwriting the audit history.

The slice is intentionally Dagster-free: no asset wiring, no
publication infrastructure, no superseded state. The Dagster asset and
publication pipeline land in later increments.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from invest_domain.candidate_pool.calculator import DefaultMinimumCandidatePoolCalculator
from invest_domain.candidate_pool.fingerprint import compute_market_data_fingerprint
from invest_domain.candidate_pool.models import (
    CandidatePoolPolicy,
    CandidatePoolResult,
    CandidatePoolRun,
    CandidatePoolStatus,
    EligibilityCriteria,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.input_snapshot.models import InputSnapshot
from invest_domain.instruments.models import InstrumentId
from invest_domain.market_data.models import BarSource, DailyBar
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_storage.models import InputSnapshotRow
from invest_storage.unit_of_work import UnitOfWork

__all__ = [
    "CandidatePoolPolicyError",
    "CandidatePoolPublishResult",
    "CandidatePoolSnapshotNotFoundError",
    "UnitOfWorkFactory",
    "calculate_and_publish_candidate_pool",
    "load_candidate_pool_policy",
]


UnitOfWorkFactory = Callable[[], UnitOfWork]


_DEFAULT_CALCULATOR = DefaultMinimumCandidatePoolCalculator()


class CandidatePoolPolicyError(ValueError):
    """Raised when a personal candidate-pool policy YAML cannot be parsed.

    A subclass of :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still works while callers that want the
    slice-specific error type can match on this name.
    """


class CandidatePoolSnapshotNotFoundError(LookupError):
    """Raised when ``snapshot_id`` does not match any persisted row.

    The slice refuses to silently fall back to another snapshot, another
    date, or fixture data; the caller is responsible for re-running the
    upstream ``etf_input_snapshot`` asset before retrying.
    """


@dataclass(frozen=True, slots=True)
class CandidatePoolPublishResult:
    """Return shape of :func:`calculate_and_publish_candidate_pool`.

    The :class:`CandidatePoolRun` reflects the terminal ``PUBLISHED``
    state (with ``published_at`` filled) and the :class:`CandidatePoolResult`
    is the pure-function output the calculator produced, so callers can
    audit the decision without re-reading the database.
    """

    run: CandidatePoolRun
    result: CandidatePoolResult


def _now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""

    return datetime.now(UTC)


def _to_finite_decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        raise CandidatePoolPolicyError(
            f"{field_name} must be a number, got bool {value!r}"
        )
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except Exception as exc:
            raise CandidatePoolPolicyError(
                f"{field_name} must be a numeric string, got {value!r}"
            ) from exc
    else:
        raise CandidatePoolPolicyError(
            f"{field_name} must be a number or numeric string, got {type(value).__name__}"
        )
    if not result.is_finite():
        raise CandidatePoolPolicyError(
            f"{field_name} must be a finite Decimal, got {result!s}"
        )
    return result


def _require_non_empty_str(value: Any, *, field_name: str) -> str:
    if isinstance(value, bool):
        raise CandidatePoolPolicyError(
            f"{field_name} must be a non-empty string, got bool {value!r}"
        )
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise CandidatePoolPolicyError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise CandidatePoolPolicyError(
            f"{field_name} must be a non-empty string, got {value!r}"
        )
    return stripped


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidatePoolPolicyError(
            f"{field_name} must be a mapping, got {type(value).__name__}"
        )
    return value


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CandidatePoolPolicyError(
            f"{field_name} must be a positive integer, got {type(value).__name__}: {value!r}"
        )
    if value < 1:
        raise CandidatePoolPolicyError(
            f"{field_name} must be >= 1, got {value}"
        )
    return value


def load_candidate_pool_policy(path: Path) -> CandidatePoolPolicy:
    """Load and validate a personal Candidate Pool policy YAML.

    The YAML must provide:

    * ``algorithm.key`` / ``algorithm.version`` / ``algorithm.parameter_set_key``
    * ``eligibility.min_volume`` / ``eligibility.min_amount``
    * ``selection.max_candidates``

    All other currently-required structural policy fields are filled
    with the smallest explicit legal defaults so the calculator receives
    a well-formed :class:`CandidatePoolPolicy` without the slice
    inventing any scoring behaviour. :meth:`CandidatePoolPolicy.__post_init__`
    computes the deterministic ``parameter_hash`` from those defaults,
    so repeated identical loads always produce the same hash.
    """

    if not path.exists():
        raise CandidatePoolPolicyError(f"policy file not found: {path}")
    if not path.is_file():
        raise CandidatePoolPolicyError(f"policy path is not a file: {path}")

    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)

    if not isinstance(payload, dict):
        raise CandidatePoolPolicyError(
            "policy root must be a mapping with keys algorithm, eligibility, selection"
        )

    algorithm = _require_mapping(payload.get("algorithm"), field_name="policy.algorithm")
    algorithm_key = _require_non_empty_str(
        algorithm.get("key"), field_name="policy.algorithm.key"
    )
    algorithm_version = _require_non_empty_str(
        algorithm.get("version"), field_name="policy.algorithm.version"
    )
    parameter_set_key = _require_non_empty_str(
        algorithm.get("parameter_set_key"),
        field_name="policy.algorithm.parameter_set_key",
    )

    eligibility = _require_mapping(
        payload.get("eligibility"), field_name="policy.eligibility"
    )
    min_volume = _to_finite_decimal(
        eligibility.get("min_volume", 0), field_name="policy.eligibility.min_volume"
    )
    min_amount = _to_finite_decimal(
        eligibility.get("min_amount", 0), field_name="policy.eligibility.min_amount"
    )
    if min_volume < 0:
        raise CandidatePoolPolicyError(
            f"policy.eligibility.min_volume must be >= 0, got {min_volume!s}"
        )
    if min_amount < 0:
        raise CandidatePoolPolicyError(
            f"policy.eligibility.min_amount must be >= 0, got {min_amount!s}"
        )

    selection = _require_mapping(
        payload.get("selection"), field_name="policy.selection"
    )
    max_candidates = _require_positive_int(
        selection.get("max_candidates"), field_name="policy.selection.max_candidates"
    )

    return CandidatePoolPolicy(
        algorithm_key=algorithm_key,
        algorithm_version=algorithm_version,
        parameter_set_key=parameter_set_key,
        eligibility=EligibilityCriteria(
            min_volume=min_volume,
            min_amount=min_amount,
        ),
        liquidity=LiquidityCriteria(lookback_days=1, min_valid_days=1),
        price_quality=PriceQualityCriteria(
            lookback_days=1,
            max_missing_ratio=Decimal("0"),
            max_zero_volume_days=0,
        ),
        risk=RiskCriteria(
            volatility_lookback_days=1,
            drawdown_lookback_days=1,
        ),
        selection=SelectionCriteria(max_candidates=max_candidates),
        score_weights=ScoreWeights(
            weights={
                "liquidity": Decimal("0"),
                "stability": Decimal("0"),
                "data_quality": Decimal("0"),
                "listing_maturity": Decimal("0"),
            }
        ),
    )


def _load_snapshot_by_id(uow: UnitOfWork, snapshot_id: UUID) -> InputSnapshot:
    """Resolve the snapshot by id through the UoW session.

    The :class:`InputSnapshotRepository` does not yet expose ``get_by_id``
    so the slice uses the session directly. The query is wrapped in a
    slice-specific error so callers can react programmatically without
    catching generic SQLAlchemy exceptions.
    """

    session: Any = uow.session
    row = session.get(InputSnapshotRow, snapshot_id)
    if row is None:
        raise CandidatePoolSnapshotNotFoundError(
            f"input_snapshot {snapshot_id!s} not found in analytics.input_snapshots"
        )
    instrument_ids = tuple(
        value if isinstance(value, UUID) else UUID(str(value))
        for value in row.instrument_ids
    )
    return InputSnapshot(
        id=row.id,
        snapshot_date=row.snapshot_date,
        instrument_ids=instrument_ids,
        content_hash=row.content_hash,
        row_count=row.row_count,
        created_at=row.created_at,
    )


def _load_bars_for_trade_date(
    uow: UnitOfWork,
    *,
    instrument_ids: tuple[UUID, ...],
    trade_date: date,
) -> list[DailyBar]:
    """Read the latest bar per instrument for ``trade_date`` and rebuild domain bars.

    Bars whose ``trade_date != trade_date`` or whose ``adjustment !=
    ``Adjust.NONE`` are filtered at the storage layer by
    :meth:`SqlAlchemyDailyBarRepository.get_latest`; a missing bar
    remains in the snapshot and surfaces downstream as ``no_data``.
    """

    bars: list[DailyBar] = []
    for instrument_uuid in instrument_ids:
        stored = uow.daily_bars.get_latest(
            instrument_id=instrument_uuid,
            trade_date=trade_date,
            adjustment=Adjust.NONE,
        )
        if stored is None:
            continue
        if stored.source_batch_id is None:
            raise ValueError(
                "daily bar is missing source_batch_id for "
                f"instrument={instrument_uuid} trade_date={trade_date}"
            )
        source_batch_id = stored.source_batch_id
        source = BarSource(
            provider_key=stored.source_provider,
            source_batch_id=source_batch_id,
            observed_at=stored.observed_at,
        )
        bar = DailyBar.build(
            instrument_id=InstrumentId(stored.instrument_id),
            trade_date=stored.trade_date,
            open=stored.open,
            high=stored.high,
            low=stored.low,
            close=stored.close,
            prev_close=stored.prev_close,
            volume=stored.volume,
            amount=stored.amount,
            adjustment=Adjust.NONE,
            trading_status=TradingStatus(stored.trading_status),
            source=source,
            revision=stored.revision,
        )
        bars.append(bar)
    return bars


def calculate_and_publish_candidate_pool(
    *,
    uow_factory: UnitOfWorkFactory,
    trade_date: date,
    snapshot_id: UUID,
    policy: CandidatePoolPolicy,
    now_factory: Callable[[], datetime] = _now_utc,
    calculator: Any = _DEFAULT_CALCULATOR,
) -> CandidatePoolPublishResult:
    """Run the personal candidate-pool calculation and publish it.

    The function performs these steps inside a single UnitOfWork:

    1. Resolve the :class:`InputSnapshot` by ``snapshot_id`` or raise
       :class:`CandidatePoolSnapshotNotFoundError`.
    2. Reject ``trade_date`` values that do not match the snapshot's
       ``snapshot_date`` (no silent fallback).
    3. Read only ``trade_date`` bars with ``Adjust.NONE`` and rebuild
       them through the domain :class:`DailyBar` model.
    4. Compute :data:`market_data_fingerprint` over the exact selected
       bar revisions via
       :func:`invest_domain.candidate_pool.fingerprint.compute_market_data_fingerprint`.
       The helper accepts an empty selection, so a ``no_data`` trade day
       still produces a stable 64-character lowercase-hex fingerprint.
    5. Run :class:`DefaultMinimumCandidatePoolCalculator` against the
       snapshot, bars and ``policy`` to obtain the deterministic
       result.
    6. Look up an existing run by the six-part natural unique key
       ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
       input_snapshot_id, market_data_fingerprint)``. If one is already
       published, return it paired with the freshly calculated result
       without writing anything (idempotent rerun).
    7. Otherwise, persist the run and items; verify the inserted item
       count matches the calculator result count.
    8. Transition the run ``CALCULATED -> VALIDATED -> PUBLISHED`` with
       timezone-aware UTC timestamps.

    The returned :class:`CandidatePoolPublishResult` carries the
    terminal :class:`CandidatePoolRun` (with ``published_at`` set) and
    the pure-function :class:`CandidatePoolResult` for audit.

    Safety contract:
        * Identical selected bar revisions reuse the existing
          :class:`CandidatePoolRun` row (the database unique constraint
          never fires; no state-machine transitions run).
        * A revised, or previously-missing, bar in the selection
          produces a fresh fingerprint and therefore a new immutable
          :class:`CandidatePoolRun` row that lives alongside the prior
          row. The audit history is preserved instead of overwritten.
    """

    with uow_factory() as uow:
        snapshot = _load_snapshot_by_id(uow, snapshot_id)
        if snapshot.snapshot_date != trade_date:
            raise ValueError(
                f"trade_date {trade_date.isoformat()} does not match "
                f"snapshot.snapshot_date {snapshot.snapshot_date.isoformat()} "
                f"for snapshot_id {snapshot_id!s}; the personal candidate-pool "
                "service refuses to silently fall back to another trade_date"
            )

        bars = _load_bars_for_trade_date(
            uow, instrument_ids=snapshot.instrument_ids, trade_date=trade_date
        )
        market_data_fingerprint = compute_market_data_fingerprint(bars)
        result: CandidatePoolResult = calculator.calculate(snapshot, bars, policy)

        existing = uow.candidate_pool_runs.get_by_natural_key(
            trade_date=trade_date,
            algorithm_key=policy.algorithm_key,
            algorithm_version=policy.algorithm_version,
            parameter_hash=policy.parameter_hash,
            input_snapshot_id=snapshot.id,
            market_data_fingerprint=market_data_fingerprint,
        )
        if existing is not None:
            uow.commit()
            return CandidatePoolPublishResult(run=existing, result=result)

        finished_at = now_factory()
        run = CandidatePoolRun(
            id=uuid.uuid4(),
            trade_date=trade_date,
            algorithm_key=policy.algorithm_key,
            algorithm_version=policy.algorithm_version,
            parameter_set_key=policy.parameter_set_key,
            parameter_hash=policy.parameter_hash,
            input_snapshot_id=snapshot.id,
            input_row_count=len(snapshot.instrument_ids),
            included_count=result.summary.included_count,
            status=CandidatePoolStatus.CALCULATED,
            created_at=finished_at,
            market_data_fingerprint=market_data_fingerprint,
        )
        persisted_run = uow.candidate_pool_runs.add(run)
        inserted = uow.candidate_pool_items.bulk_add(
            persisted_run.id, result.items
        )
        if inserted != len(result.items):
            raise RuntimeError(
                f"bulk_add inserted {inserted} items but the calculator "
                f"produced {len(result.items)} items; refusing to transition "
                "with a mismatched count"
            )

        validated = uow.candidate_pool_runs.transition_status(
            persisted_run.id,
            CandidatePoolStatus.VALIDATED,
            at=finished_at,
        )
        published = uow.candidate_pool_runs.transition_status(
            validated.id,
            CandidatePoolStatus.PUBLISHED,
            at=finished_at,
        )
        uow.commit()
        return CandidatePoolPublishResult(run=published, result=result)
