"""Pure-function candidate-pool calculator (PR-08 minimum implementation).

The :class:`MinimumCandidatePoolCalculator` is a *pure function* (per
ADR-0008 / plan §9.4): it has no I/O, no environment access, no clock
reads and no global state. Given an :class:`InputSnapshot`, a flat list
of :class:`DailyBar` rows and a :class:`CandidatePoolPolicy`, it returns
a deterministic :class:`CandidatePoolResult` that includes exactly one
:class:`CandidatePoolItem` per input ``instrument_id`` — either
included (with rank ``1..N``) or excluded (with an
:class:`ExclusionReason`).

This module deliberately ships a *minimum* algorithm:

- ``no_data``     — no :class:`DailyBar` row exists for the instrument.
- ``suspended``   — the latest bar is in ``TradingStatus.SUSPENDED``.
- ``invalid_price`` — ``close`` is missing or non-positive (defensive —
  in practice :class:`DailyBar` already rejects NORMAL bars with
  ``close <= 0``).
- ``low_volume``  — ``volume`` is missing or below
  ``policy.eligibility.min_volume``.
- ``low_amount``  — ``amount`` is missing or below
  ``policy.eligibility.min_amount``.

Included items are ranked by ``close * volume`` descending, with the
underlying :class:`UUID` bytes as the deterministic tiebreaker so equal
turnovers never produce rank collisions.

The M4 calculator will conform to the full
:class:`invest_domain.candidate_pool.ports.CandidatePoolCalculator`
Protocol with scored rules; the present Protocol signature intentionally
differs because the minimum algorithm does not yet consume the rolling
histories the M4 contract requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable, TYPE_CHECKING
from uuid import UUID

from invest_domain.candidate_pool.models import (
    CalculationContext,
    CandidatePoolItem,
    CandidatePoolPolicy,
    CandidatePoolResult,
    CandidatePoolSummary,
    ExclusionReason,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.input_snapshot.models import InputSnapshot

if TYPE_CHECKING:
    from invest_domain.market_data.models import DailyBar
    from invest_domain.market_data.values import TradingStatus


@runtime_checkable
class MinimumCandidatePoolCalculator(Protocol):
    """Port for the PR-08 minimum candidate-pool calculator.

    The signature deliberately differs from the M4
    :class:`invest_domain.candidate_pool.ports.CandidatePoolCalculator`:
    the minimum algorithm does not need scored rule results, rolling
    histories or a separate :class:`CalculationContext` argument. The
    :class:`CalculationContext` is derived from the
    :class:`InputSnapshot` so the call site stays minimal.
    """

    def calculate(
        self,
        snapshot: InputSnapshot,
        bars: list[DailyBar],
        policy: CandidatePoolPolicy,
    ) -> CandidatePoolResult: ...


_EXCLUSION_MESSAGES: dict[str, str] = {
    "no_data": "no DailyBar available for the instrument on the snapshot date",
    "suspended": "instrument was suspended on the snapshot date",
    "invalid_price": "close price is missing or non-positive",
    "low_volume": "volume is missing or below the policy minimum",
    "low_amount": "amount is missing or below the policy minimum",
}


def _exclusion_reason(code: str) -> ExclusionReason:
    """Return an :class:`ExclusionReason` carrying the canonical ``code``.

    ``code`` is the stable machine-readable tag downstream tooling groups
    on; ``message`` is the human-readable explanation rendered in logs.
    """

    return ExclusionReason(code=code, message=_EXCLUSION_MESSAGES[code])


def _check_eligibility(
    bar: "DailyBar | None",
    *,
    min_volume: Decimal,
    min_amount: Decimal,
) -> ExclusionReason | None:
    """Return the first failing exclusion reason, or ``None`` if all pass.

    The order of checks matches the task brief: ``no_data`` first
    (catches the missing-row case), then ``suspended`` (so SUSPENDED bars
    are tagged with the most-specific reason), then the OHLCV
    thresholds. The function is intentionally tolerant of
    ``bar.close <= 0`` and ``bar.volume is None`` even though
    :class:`DailyBar.__post_init__` already rejects them in production —
    the defensive check keeps the algorithm correct under fuzz / mock
    inputs and is unit-tested via the public ``calculate`` entry point.
    """

    from invest_domain.market_data.values import TradingStatus

    if bar is None:
        return _exclusion_reason("no_data")
    if bar.trading_status is TradingStatus.SUSPENDED:
        return _exclusion_reason("suspended")
    if bar.close is None or bar.close <= 0:
        return _exclusion_reason("invalid_price")
    if bar.volume is None or bar.volume < min_volume:
        return _exclusion_reason("low_volume")
    if bar.amount is None or bar.amount < min_amount:
        return _exclusion_reason("low_amount")
    return None


def _latest_bar_per_instrument(
    bars: "list[DailyBar]",
) -> dict[InstrumentId, "DailyBar"]:
    """Return the latest :class:`DailyBar` per :class:`InstrumentId`.

    ``trade_date`` is the only ordering key we trust: ``DailyBar`` does
    not carry a wall-clock ingest timestamp and revisions are
    storage-layer concerns outside the calculator's scope. Ties on
    ``trade_date`` keep the *first* bar seen, which matches the
    deterministic snapshot the application service hands in.
    """

    latest: dict[InstrumentId, DailyBar] = {}
    for bar in bars:
        existing = latest.get(bar.instrument_id)
        if existing is None or bar.trade_date > existing.trade_date:
            latest[bar.instrument_id] = bar
    return latest


@dataclass(frozen=True, slots=True)
class DefaultMinimumCandidatePoolCalculator:
    """Default PR-08 minimum implementation of :class:`MinimumCandidatePoolCalculator`.

    Pure function: no I/O, no clock reads, no environment access. Same
    input always yields the same output (the sort key is
    ``(-turnover, instrument_uuid.bytes)`` so equal turnovers rank in
    deterministic UUID order).
    """

    def calculate(
        self,
        snapshot: InputSnapshot,
        bars: list[DailyBar],
        policy: CandidatePoolPolicy,
    ) -> CandidatePoolResult:
        if not isinstance(snapshot, InputSnapshot):
            raise TypeError(
                f"snapshot must be an InputSnapshot, got {type(snapshot).__name__}"
            )
        if not isinstance(policy, CandidatePoolPolicy):
            raise TypeError(
                f"policy must be a CandidatePoolPolicy, got {type(policy).__name__}"
            )
        min_volume = policy.eligibility.min_volume
        min_amount = policy.eligibility.min_amount

        latest_by_id = _latest_bar_per_instrument(bars)

        excluded_items: dict[UUID, CandidatePoolItem] = {}
        included_candidates: list[tuple[Decimal, UUID, DailyBar]] = []

        for instrument_uuid in snapshot.instrument_ids:
            if not isinstance(instrument_uuid, UUID):
                raise TypeError(
                    "InputSnapshot.instrument_ids must contain only UUID instances, "
                    f"got {type(instrument_uuid).__name__}"
                )
            instrument_id = InstrumentId(instrument_uuid)
            latest_bar = latest_by_id.get(instrument_id)
            reason = _check_eligibility(
                latest_bar, min_volume=min_volume, min_amount=min_amount
            )
            if reason is not None:
                excluded_items[instrument_uuid] = CandidatePoolItem(
                    instrument_id=instrument_id,
                    included=False,
                    rank=None,
                    total_score=None,
                    exclusion_reasons=(reason,),
                )
            else:
                turnover = latest_bar.close * latest_bar.volume
                included_candidates.append((turnover, instrument_uuid, latest_bar))

        included_candidates.sort(key=lambda candidate: (-candidate[0], candidate[1].bytes))

        included_items: dict[UUID, CandidatePoolItem] = {}
        for rank, (turnover, instrument_uuid, bar) in enumerate(
            included_candidates, start=1
        ):
            instrument_id = InstrumentId(instrument_uuid)
            included_items[instrument_uuid] = CandidatePoolItem(
                instrument_id=instrument_id,
                included=True,
                rank=rank,
                total_score=turnover,
                metrics={
                    "amount": bar.amount,
                    "close": bar.close,
                    "turnover": turnover,
                    "volume": bar.volume,
                },
            )

        ordered_items: list[CandidatePoolItem] = []
        for uid in snapshot.instrument_ids:
            ordered_items.append(
                included_items[uid] if uid in included_items else excluded_items[uid]
            )

        included_count = len(included_items)
        excluded_count = len(excluded_items)
        summary = CandidatePoolSummary(
            input_count=len(snapshot.instrument_ids),
            included_count=included_count,
            excluded_count=excluded_count,
            rule_error_count=0,
            rule_warn_count=0,
        )
        context = CalculationContext(
            trade_date=snapshot.snapshot_date,
            as_of_utc=snapshot.created_at,
            input_snapshot_id=snapshot.id,
        )
        return CandidatePoolResult(
            policy=policy,
            context=context,
            items=tuple(ordered_items),
            summary=summary,
        )


__all__ = [
    "DefaultMinimumCandidatePoolCalculator",
    "MinimumCandidatePoolCalculator",
]