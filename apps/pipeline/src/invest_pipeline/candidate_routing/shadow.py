"""Dynamic candidate-pool shadow MVP (composes the existing ETF universe classifier).

This module is a pure, deterministic application-layer function that
chains the two already-existing domain primitives:

1. :func:`invest_domain.candidate_pool.universe.build_etf_universe` —
   classifies every input instrument into ``FULL`` / ``PARTIAL`` /
   ``INELIGIBLE`` based on the bar history and staleness thresholds.
2. :class:`invest_domain.candidate_pool.calculator.DefaultMinimumCandidatePoolCalculator`
   — runs the existing minimum candidate-pool calculation on the
   ``FULL`` slice only.

The shadow contract is deliberately narrow:

* ``FULL`` candidates build a single :class:`InputSnapshot` (UUID
  membership list, sorted by raw UUID bytes) and a single
  :class:`CandidatePoolResult` from the calculator.
* ``PARTIAL`` candidates go to ``watch_only`` in deterministic
  instrument-id order. They are **never** fed to the calculator.
* ``INELIGIBLE`` candidates are silently dropped; they never enter the
  snapshot, the calculator, or ``watch_only``.
* If no ``FULL`` candidate survives, both ``snapshot`` and
  ``candidate_pool_result`` are ``None`` — the shadow never invents an
  empty snapshot to paper over an empty universe.
* Inputs are never mutated. Result ordering is deterministic; with
  pinned ``id_factory`` / ``now_factory`` / ``calculator`` the
  resulting :attr:`CandidatePoolShadowResult.content_hash` is stable
  for equal logical inputs.

The function is intentionally free of PostgreSQL, Dagster, provider,
network and filesystem access. It is a Shadow MVP: it is the analytical
shape of the eventual routed candidate pool, not a publishing path.
The existing personal candidate pool service
(:mod:`invest_pipeline.candidate_pool_service`) continues to own
persistence and state-machine transitions unchanged.

Threshold defaults are the bounded-build defaults documented in the
task brief: 60 full-history days, 20 partial-history days, and a
3-day staleness ceiling. They are exposed as keyword parameters so
tests and downstream callers can override them intentionally without
reaching into the domain.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from invest_domain.candidate_pool.calculator import (
    DefaultMinimumCandidatePoolCalculator,
    MinimumCandidatePoolCalculator,
)
from invest_domain.candidate_pool.models import (
    CandidatePoolPolicy,
    CandidatePoolResult,
)
from invest_domain.candidate_pool.universe import (
    UniverseCandidate,
    UniverseEligibility,
    build_etf_universe,
)
from invest_domain.input_snapshot.models import InputSnapshot
from invest_domain.instruments.models import Instrument, InstrumentId
from invest_domain.market_data.models import DailyBar

DEFAULT_MINIMUM_FULL_HISTORY_DAYS: int = 60
"""Default minimum bar-history length (in trading days) for the FULL slice.

Mirrors the bounded-build default documented in the task brief. The
shadow MVP keeps this constant at module level so downstream callers
can import the same value the function uses by default without having
to repeat the magic number.
"""

DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS: int = 20
"""Default minimum bar-history length for the PARTIAL slice.

PARTIAL instruments are placed in ``watch_only``; the calculator never
sees them. The threshold exists so the universe classifier knows which
instruments are mature enough to track but not yet stable enough to
score.
"""

DEFAULT_MAX_STALE_DAYS: int = 3
"""Default staleness ceiling for the universe classifier.

Instruments whose most recent valid bar is older than
``as_of_date - max_stale_days`` are downgraded to ``INELIGIBLE``,
regardless of their history length. The default matches the
bounded-build default; raise it for backtests, lower it for live
ingest during known outages.
"""


class CandidatePoolShadowError(ValueError):
    """Base class for every Shadow MVP configuration failure.

    Subclasses tag the failure (threshold validation) so callers can
    react programmatically without parsing free text. The base class
    is itself a :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still works.
    """


class InvalidUniverseThresholdsError(CandidatePoolShadowError):
    """The universe threshold keyword arguments are inconsistent.

    Raised when ``minimum_full_history_days < minimum_partial_history_days``,
    when either threshold is non-positive, or when
    ``max_stale_days`` is negative. The shadow function refuses to run
    on an incoherent configuration so the resulting classification
    cannot be silently wrong.
    """


@dataclass(frozen=True, slots=True)
class CandidatePoolShadowResult:
    """Frozen output of :func:`route_candidate_pool_shadow`.

    Attributes
    ----------
    as_of_date:
        The trading day the shadow run describes (Asia/Shanghai local
        calendar). Echoed back from the caller's argument so the result
        is self-describing.
    universe:
        Ordered :class:`UniverseCandidate` classifications, one per
        input instrument, ordered by ``str(instrument_id)``. The
        classifier never reorders its input; the function sorts the
        sequence by instrument-id string so two calls with the same
        logical input produce identical tuples regardless of caller
        ordering.
    watch_only:
        Sorted tuple of :class:`InstrumentId` for the PARTIAL slice.
        INELIGIBLE candidates are excluded; FULL candidates are sent
        to the calculator instead.
    snapshot:
        The :class:`InputSnapshot` built from FULL candidates, or
        ``None`` when no FULL candidate survived. The snapshot is
        always constructed via :meth:`InputSnapshot.create` so its
        ``content_hash`` is deterministic.
    candidate_pool_result:
        The :class:`CandidatePoolResult` from the minimum calculator
        for the FULL slice, or ``None`` when no FULL candidate
        survived. Pairs with ``snapshot`` — both are present or both
        are ``None``.
    full_count:
        Number of FULL candidates that entered the snapshot.
    partial_count:
        Number of PARTIAL candidates that entered ``watch_only``.
    ineligible_count:
        Number of INELIGIBLE candidates the shadow dropped.
    content_hash:
        Stable SHA-256 hex digest over the canonical content of the
        result (universe classifications, watch-only ids, snapshot
        membership, calculator summary). Independent of the absolute
        ``InputSnapshot.id`` and ``created_at`` so a re-run on the
        same logical inputs always produces the same digest.
    """

    as_of_date: date
    universe: tuple[UniverseCandidate, ...]
    watch_only: tuple[InstrumentId, ...]
    snapshot: InputSnapshot | None
    candidate_pool_result: CandidatePoolResult | None
    full_count: int
    partial_count: int
    ineligible_count: int
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.as_of_date, date):
            raise TypeError(
                "CandidatePoolShadowResult.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )
        if not isinstance(self.universe, tuple):
            raise ValueError(
                "CandidatePoolShadowResult.universe must be a tuple[UniverseCandidate, ...]"
            )
        if not isinstance(self.watch_only, tuple):
            raise ValueError(
                "CandidatePoolShadowResult.watch_only must be a tuple[InstrumentId, ...]"
            )
        if (self.snapshot is None) != (self.candidate_pool_result is None):
            raise ValueError(
                "CandidatePoolShadowResult.snapshot and candidate_pool_result must "
                "be both None or both set; refusing to publish a half-built shadow"
            )
        if self.full_count < 0:
            raise ValueError(
                f"CandidatePoolShadowResult.full_count must be >= 0, got {self.full_count}"
            )
        if self.partial_count < 0:
            raise ValueError(
                f"CandidatePoolShadowResult.partial_count must be >= 0, got {self.partial_count}"
            )
        if self.ineligible_count < 0:
            raise ValueError(
                f"CandidatePoolShadowResult.ineligible_count must be >= 0, "
                f"got {self.ineligible_count}"
            )
        if self.full_count + self.partial_count + self.ineligible_count != len(self.universe):
            raise ValueError(
                "CandidatePoolShadowResult universe count must equal "
                f"full+partial+ineligible ({self.full_count}+{self.partial_count}"
                f"+{self.ineligible_count} != {len(self.universe)})"
            )
        if len(self.watch_only) != self.partial_count:
            raise ValueError(
                "CandidatePoolShadowResult.watch_only length must equal partial_count "
                f"({len(self.watch_only)} != {self.partial_count})"
            )
        if self.snapshot is not None and self.snapshot.row_count != self.full_count:
            raise ValueError(
                "CandidatePoolShadowResult.snapshot.row_count must equal full_count "
                f"({self.snapshot.row_count} != {self.full_count})"
            )
        if not isinstance(self.content_hash, str) or len(self.content_hash) != 64:
            raise ValueError(
                "CandidatePoolShadowResult.content_hash must be a 64-character hex string"
            )


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""

    return datetime.now(UTC)


def _validate_thresholds(
    *,
    minimum_full_history_days: int,
    minimum_partial_history_days: int,
    max_stale_days: int,
) -> None:
    """Reject inconsistent universe threshold keyword arguments.

    Mirrors the invariants enforced by
    :func:`invest_domain.candidate_pool.universe.build_etf_universe`
    but raises a Shadow-specific subclass so callers can react
    programmatically. The shadow MVP refuses to run on an incoherent
    configuration; the universe classifier would raise a generic
    ``ValueError`` instead.
    """

    if minimum_partial_history_days < 1:
        raise InvalidUniverseThresholdsError(
            "minimum_partial_history_days must be >= 1, "
            f"got {minimum_partial_history_days}"
        )
    if minimum_full_history_days < minimum_partial_history_days:
        raise InvalidUniverseThresholdsError(
            "minimum_full_history_days must be >= minimum_partial_history_days "
            f"({minimum_full_history_days} < {minimum_partial_history_days})"
        )
    if max_stale_days < 0:
        raise InvalidUniverseThresholdsError(
            f"max_stale_days must be >= 0, got {max_stale_days}"
        )


def _build_full_bars(
    *,
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    full_instrument_ids: Sequence[InstrumentId],
) -> list[DailyBar]:
    """Return the latest bar per FULL instrument, in stable order.

    The minimum calculator only inspects the most recent bar per
    instrument, but it expects a flat list of :class:`DailyBar` rows.
    Bars are deduplicated to the latest ``trade_date`` per
    instrument-id, then flattened in the same byte-sorted order the
    snapshot uses so the calculator's ``_latest_bar_per_instrument``
    walk is a no-op (every instrument has exactly one row).
    """

    latest_by_id: dict[InstrumentId, DailyBar] = {}
    for instrument_id in full_instrument_ids:
        bars = bars_by_instrument.get(instrument_id, ())
        latest: DailyBar | None = None
        for bar in bars:
            if latest is None or bar.trade_date > latest.trade_date:
                latest = bar
        if latest is not None:
            latest_by_id[instrument_id] = latest
    return [
        latest_by_id[instrument_id]
        for instrument_id in full_instrument_ids
        if instrument_id in latest_by_id
    ]


def _compute_content_hash(
    *,
    as_of_date: date,
    universe: tuple[UniverseCandidate, ...],
    watch_only: tuple[InstrumentId, ...],
    snapshot: InputSnapshot | None,
    result: CandidatePoolResult | None,
) -> str:
    """Compute the deterministic content hash for a shadow run.

    The hash covers only the analytical content — universe
    classifications, watch-only membership, snapshot content_hash (not
    ``id`` / ``created_at``), calculator policy parameter_hash and
    per-item (rank, included, exclusion code) — so two runs on the
    same logical inputs produce the same digest regardless of the
    factories that produced their ``InputSnapshot.id`` /
    ``created_at`` stamps.
    """

    universe_payload = (
        (
            str(candidate.instrument_id),
            candidate.eligibility.value,
            candidate.history_days,
            candidate.can_enter_watch_only,
            ",".join(candidate.reasons),
        )
        for candidate in universe
    )

    watch_only_payload = tuple(sorted(str(value) for value in watch_only))

    snapshot_payload: tuple[Any, ...]
    if snapshot is None:
        snapshot_payload = (None,)
    else:
        snapshot_payload = (
            snapshot.snapshot_date.isoformat(),
            [value.bytes for value in snapshot.instrument_ids],
            snapshot.content_hash,
            snapshot.row_count,
        )

    calculator_payload: tuple[Any, ...]
    if result is None:
        calculator_payload = (None,)
    else:
        calculator_payload = (
            result.policy.parameter_hash,
            tuple(
                sorted(
                    (
                        str(item.instrument_id),
                        item.included,
                        item.rank,
                        item.exclusion_reasons[0].code
                        if item.exclusion_reasons
                        else None,
                    )
                    for item in result.items
                )
            ),
            result.summary.included_count,
            result.summary.excluded_count,
            result.summary.input_count,
        )

    payload = {
        "as_of_date": as_of_date.isoformat(),
        "calculator": calculator_payload,
        "snapshot": snapshot_payload,
        "universe": tuple(universe_payload),
        "watch_only": watch_only_payload,
    }
    serialised = repr(payload).encode("utf-8")
    return hashlib.sha256(serialised).hexdigest()


def route_candidate_pool_shadow(
    *,
    instruments: Sequence[Instrument],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
    policy: CandidatePoolPolicy,
    minimum_full_history_days: int = DEFAULT_MINIMUM_FULL_HISTORY_DAYS,
    minimum_partial_history_days: int = DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    id_factory: Callable[[], UUID] = uuid4,
    now_factory: Callable[[], datetime] = _utcnow,
    calculator: MinimumCandidatePoolCalculator | None = None,
) -> CandidatePoolShadowResult:
    """Run the dynamic candidate-pool shadow MVP for ``as_of_date``.

    The function:

    1. Validates the threshold keyword arguments up front.
    2. Calls :func:`invest_domain.candidate_pool.universe.build_etf_universe`
       with the supplied instruments, bars and thresholds. The
       classifier deduplicates by instrument-id and orders its output
       by ``str(instrument_id)`` itself; the shadow does not re-sort
       the result so the universe ordering is owned in one place.
    3. Routes PARTIAL candidates to ``watch_only`` (sorted by
       instrument-id string) and drops INELIGIBLE candidates.
    4. When at least one FULL candidate survives, builds an
       :class:`InputSnapshot` from the FULL set via
       :meth:`InputSnapshot.create` so the membership list is
       UUID-byte-sorted and the content hash is deterministic.
    5. Hands the snapshot, the latest bar per FULL instrument and the
       supplied ``policy`` to the injected calculator
       (default :class:`DefaultMinimumCandidatePoolCalculator`).
    6. When no FULL candidate survives, returns
       ``snapshot=None`` and ``candidate_pool_result=None`` without
       inventing an empty snapshot.
    7. Computes a deterministic ``content_hash`` over the analytical
       content of the result.

    Parameters
    ----------
    instruments:
        ETF instruments to classify. The function does not mutate
        this sequence; ``build_etf_universe`` is responsible for
        deduplicating and ordering.
    bars_by_instrument:
        Mapping from :class:`InstrumentId` to its bar series. The
        function never mutates this mapping; the universe classifier
        and the calculator both consume it read-only.
    as_of_date:
        Trading day the shadow run describes. Echoed back on the
        result and used by the universe classifier and the
        :class:`InputSnapshot` ``snapshot_date``.
    policy:
        The :class:`CandidatePoolPolicy` passed unchanged to the
        minimum calculator. Not interpreted by the shadow itself.
    minimum_full_history_days, minimum_partial_history_days, max_stale_days:
        Universe-classification thresholds. Defaults match the
        bounded-build MVP; tests and downstream callers may override
        intentionally.
    id_factory, now_factory:
        Deterministic factories for :class:`InputSnapshot`
        construction. Defaults are ``uuid.uuid4`` /
        ``datetime.now(timezone.utc)``; tests should pin both to keep
        the result stable across re-runs.
    calculator:
        Optional :class:`MinimumCandidatePoolCalculator`. Defaults to
        :class:`DefaultMinimumCandidatePoolCalculator`; tests may
        inject a stub to observe the delegation contract.

    Returns
    -------
    CandidatePoolShadowResult
        Frozen value object with the universe classifications,
        watch-only ids, optional snapshot + result and a content
        hash.

    Raises
    ------
    InvalidUniverseThresholdsError
        The threshold keyword arguments are inconsistent.
    """

    _validate_thresholds(
        minimum_full_history_days=minimum_full_history_days,
        minimum_partial_history_days=minimum_partial_history_days,
        max_stale_days=max_stale_days,
    )

    active_calculator: MinimumCandidatePoolCalculator
    if calculator is None:
        active_calculator = DefaultMinimumCandidatePoolCalculator()
    else:
        active_calculator = calculator

    universe = build_etf_universe(
        instruments,
        bars_by_instrument,
        as_of_date,
        minimum_full_history_days=minimum_full_history_days,
        minimum_partial_history_days=minimum_partial_history_days,
        max_stale_days=max_stale_days,
    )

    full_candidates: list[UniverseCandidate] = []
    partial_candidates: list[UniverseCandidate] = []
    ineligible_count = 0
    for candidate in universe:
        if candidate.eligibility is UniverseEligibility.FULL:
            full_candidates.append(candidate)
        elif candidate.eligibility is UniverseEligibility.PARTIAL:
            partial_candidates.append(candidate)
        else:
            ineligible_count += 1

    watch_only = tuple(
        sorted(
            (candidate.instrument_id for candidate in partial_candidates),
            key=str,
        )
    )

    snapshot: InputSnapshot | None = None
    result: CandidatePoolResult | None = None
    if full_candidates:
        full_instrument_ids = tuple(
            sorted(
                (candidate.instrument_id for candidate in full_candidates),
                key=lambda value: value.value.bytes,
            )
        )
        snapshot = InputSnapshot.create(
            snapshot_date=as_of_date,
            instrument_ids=tuple(value.value for value in full_instrument_ids),
            id_factory=id_factory,
            now_factory=now_factory,
        )
        calculator_bars = _build_full_bars(
            bars_by_instrument=bars_by_instrument,
            full_instrument_ids=full_instrument_ids,
        )
        result = active_calculator.calculate(snapshot, calculator_bars, policy)

    content_hash = _compute_content_hash(
        as_of_date=as_of_date,
        universe=universe,
        watch_only=watch_only,
        snapshot=snapshot,
        result=result,
    )

    return CandidatePoolShadowResult(
        as_of_date=as_of_date,
        universe=universe,
        watch_only=watch_only,
        snapshot=snapshot,
        candidate_pool_result=result,
        full_count=len(full_candidates),
        partial_count=len(partial_candidates),
        ineligible_count=ineligible_count,
        content_hash=content_hash,
    )


__all__ = [
    "DEFAULT_MAX_STALE_DAYS",
    "DEFAULT_MINIMUM_FULL_HISTORY_DAYS",
    "DEFAULT_MINIMUM_PARTIAL_HISTORY_DAYS",
    "CandidatePoolShadowError",
    "CandidatePoolShadowResult",
    "InvalidUniverseThresholdsError",
    "route_candidate_pool_shadow",
]
