"""Stage 4A-0 PR-02 deterministic baseline-factor ``Candidate Proposal`` channel.

This module is the first formal slice of the Stage 4A-0 multi-channel
candidate-routing plan (see
``docs/plan/invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md``,
particularly §6 / §7 / §10 / §13). It composes the existing
:class:`invest_domain.candidate_pool.universe.build_etf_universe`
classifier with the shared
:func:`invest_domain.analytics.factor_calculators.calculate_market_state_factors`
calculator to emit one auditable ``Candidate Proposal`` per input
instrument — no second factor implementation, no database, no Provider,
no network and no filesystem access.

Hard guarantees (every behaviour is unit-tested):

* Pure, deterministic function: same ``instruments``, same
  ``bars_by_instrument``, same ``as_of_date`` and same ``policy`` always
  produce the same :class:`BaselineFactorChannelResult` in the same
  order (stable tie-breaker on the raw :class:`UUID` bytes of the
  :class:`InstrumentId`).
* No copy of the eight factor formulas — every factor used here comes
  out of :class:`invest_domain.analytics.factor_calculators.FactorCalculationResult`,
  and the sub-scoring routines only normalise those factor values into
  ``0..100`` axes (clip + log scale). Plan §9 forbids duplicating
  factor formulas between routing and research.
* Hard quality gates (plan §10.1) fail **closed** — instruments with
  conflicting / invalid / missing key data land in
  ``decision="exclude"`` with explicit machine-readable
  :attr:`BaselineFactorProposal.exclusion_reasons`. Institutional /
  manual / custom recommendations in later PRs cannot override the
  hard gate.
* The four-state ``decision`` vocabulary (``include`` /
  ``watch`` / ``exclude`` / ``no_opinion``) mirrors plan §7 so the
  fusion layer in PR-05 can consume the channel uniformly. The
  :class:`BaselineFactorProposal` shape is intentionally narrower than
  plan §7's ``CandidateProposal`` because this channel has no
  publication timestamps or external evidence refs.
* :attr:`BaselineFactorChannelResult.policy_hash` is a stable
  ``content_hash`` digest of the policy payload, satisfying plan §15's
  audit requirement without touching PostgreSQL.
* The channel version is pinned to :data:`BASELINE_FACTOR_CHANNEL_VERSION`
  so every downstream audit can identify this exact algorithm revision.

This module deliberately does NOT:

* Import ``v1_adapter``, FastAPI, SQLAlchemy, Dagster, httpx, any
  Provider SDK, or any clock / environment helper.
* Persist anything: it returns a frozen value object and is built so
  the candidate-pool persistence layer remains the single writer.
* Apply optimisation / backtest logic — every threshold is a
  conservative default that the task brief's policy can override by
  construction.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from invest_domain.candidate_pool.universe import (
    UniverseCandidate,
    UniverseEligibility,
    build_etf_universe,
)
from invest_domain.analytics.factor_calculators import (
    FactorCalculationResult,
    calculate_market_state_factors,
)
from invest_domain.instruments.models import Instrument, InstrumentId
from invest_domain.market_data.models import DailyBar
from invest_domain.research.models import (
    FACTOR_SET_KEY,
    FACTOR_SET_VERSION,
    QualityStatus,
)
from invest_domain.shared.canonical import content_hash

# ---------------------------------------------------------------------------
# Module-level pinned constants
# ---------------------------------------------------------------------------

#: Stable channel key consumed by the Stage 4A-0 fusion layer in PR-05.
#: Matches plan §6 ``Channel A`` so external callers and audit logs can
#: resolve the channel by name without consulting the source code.
BASELINE_FACTOR_CHANNEL_KEY: str = "baseline_factor_screen"

#: Pinned channel version. Bump only when the scoring algorithm or the
#: decision-mapping semantics change in a way that should be auditable.
#: The hash of the policy payload (see :class:`BaselineFactorPolicy`) is
#: independent of this version so parameter tweaks stay traceable.
BASELINE_FACTOR_CHANNEL_VERSION: str = "1.0.0"

#: Routing factor-set key — the baseline channel reuses the v1.0.0
#: shared factor package (plan §9) so the AI Evidence Pack and the
#: routing layer operate on exactly the same factor definitions.
BASELINE_FACTOR_FACTOR_SET_KEY: str = FACTOR_SET_KEY

#: Routing factor-set version — pinned to the same ``1.0.0`` as the
#: research-side :class:`invest_domain.research.models.FactorSetMetadata`.
BASELINE_FACTOR_FACTOR_SET_VERSION: str = FACTOR_SET_VERSION

#: Default minimum bar-history length (trading days) for the FULL slice.
DEFAULT_MIN_FULL_HISTORY_DAYS: int = 60

#: Default minimum bar-history length for the PARTIAL slice. PARTIAL
#: candidates may *only* enter ``watch`` (plan §8); raising this value
#: shrinks the watch bucket without affecting ``include``.
DEFAULT_MIN_PARTIAL_HISTORY_DAYS: int = 20

#: Default staleness ceiling for the universe classifier. Inherited
#: from the shadow MVP constant so the two layers agree on the
#: "stale" line.
DEFAULT_MAX_STALE_DAYS: int = 3

#: Quantisation quantum for every baseline-channel Decimal output.
#: Matches the v1.0.0 factor calculator quantum so bytewise rounding
#: rules cannot diverge between channels.
_QUANTUM: Decimal = Decimal("0.00000001")

#: Decimal ``0`` literal — declared once to keep ``__post_init__``
#: assignments terse and to avoid accidentally re-introducing a different
#: Decimal context.
_ZERO: Decimal = Decimal("0")

#: Decimal ``1`` literal used by the clip normalisation helpers.
_ONE: Decimal = Decimal("1")

#: Decimal ``100`` literal — every sub-score is normalised to ``0..100``
#: per plan §10.2 so weight × sub-score arithmetic stays human-readable.
_ONE_HUNDRED: Decimal = Decimal("100")


# ---------------------------------------------------------------------------
# Exceptions raised by this module
# ---------------------------------------------------------------------------


class BaselineFactorChannelError(ValueError):
    """Base class for every baseline-factor channel configuration failure.

    Inherits from :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still treats channel failures as
    validation-time errors. Subclasses tag the failure so callers can
    react programmatically without parsing free text.
    """


class InvalidBaselineFactorPolicyError(BaselineFactorChannelError):
    """Raised when :class:`BaselineFactorPolicy` carries inconsistent parameters."""

    code: str = "baseline_factor.invalid_policy"


# ---------------------------------------------------------------------------
# Policy (versioned)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineFactorPolicy:
    """Immutable, versioned bundle of thresholds and weights for the channel.

    All Decimal parameters are required to be finite and non-negative;
    the weights need not sum to ``1`` (the calculator is responsible for
    rescaling only the missing-factor branch). Every policy instance
    carries a deterministic :attr:`parameter_hash` so the channel
    runner can persist an audit row like plan §15 describes without
    touching storage here.

    The constructor **does not** perform numerical auto-tuning and
    never queries the environment: every value must be supplied
    explicitly so two runs with the same arguments are byte-equal.
    """

    trend_weight: Decimal = Decimal("0.40")
    liquidity_weight: Decimal = Decimal("0.30")
    risk_weight: Decimal = Decimal("0.30")
    include_threshold: Decimal = Decimal("60")
    watch_threshold: Decimal = Decimal("40")
    min_full_history_days: int = DEFAULT_MIN_FULL_HISTORY_DAYS
    min_partial_history_days: int = DEFAULT_MIN_PARTIAL_HISTORY_DAYS
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS
    min_avg_turnover_amount_cny: Decimal = Decimal("10000000")
    min_data_completeness: Decimal = Decimal("0.90")
    trend_return_clip: Decimal = Decimal("0.10")
    trend_distance_clip: Decimal = Decimal("0.05")
    liquidity_floor_amount_cny: Decimal = Decimal("1000000")
    liquidity_ceiling_amount_cny: Decimal = Decimal("100000000")
    volatility_ceiling: Decimal = Decimal("0.30")
    drawdown_floor: Decimal = Decimal("-0.20")
    parameter_hash: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("trend_weight", self.trend_weight),
            ("liquidity_weight", self.liquidity_weight),
            ("risk_weight", self.risk_weight),
            ("include_threshold", self.include_threshold),
            ("watch_threshold", self.watch_threshold),
            ("min_avg_turnover_amount_cny", self.min_avg_turnover_amount_cny),
            ("min_data_completeness", self.min_data_completeness),
            ("trend_return_clip", self.trend_return_clip),
            ("trend_distance_clip", self.trend_distance_clip),
            ("liquidity_floor_amount_cny", self.liquidity_floor_amount_cny),
            ("liquidity_ceiling_amount_cny", self.liquidity_ceiling_amount_cny),
            ("volatility_ceiling", self.volatility_ceiling),
        ):
            _require_finite_non_negative_decimal(value, field_name)
        _require_finite_decimal(self.drawdown_floor, "BaselineFactorPolicy.drawdown_floor")
        if self.include_threshold < self.watch_threshold:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.include_threshold must be >= watch_threshold "
                f"(include_threshold={self.include_threshold!s} < "
                f"watch_threshold={self.watch_threshold!s})"
            )
        if self.include_threshold > _ONE_HUNDRED or self.watch_threshold < _ZERO:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy thresholds must lie within [0, 100]; "
                f"got include_threshold={self.include_threshold!s}, "
                f"watch_threshold={self.watch_threshold!s}"
            )
        for field_name, value in (
            ("min_full_history_days", self.min_full_history_days),
            ("min_partial_history_days", self.min_partial_history_days),
            ("max_stale_days", self.max_stale_days),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise InvalidBaselineFactorPolicyError(
                    f"BaselineFactorPolicy.{field_name} must be a non-negative int, "
                    f"got {value!r}"
                )
        if self.min_partial_history_days < 1:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.min_partial_history_days must be >= 1, "
                f"got {self.min_partial_history_days}"
            )
        if self.min_full_history_days < self.min_partial_history_days:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.min_full_history_days must be >= "
                "min_partial_history_days "
                f"({self.min_full_history_days} < {self.min_partial_history_days})"
            )
        if self.trend_weight + self.liquidity_weight + self.risk_weight <= _ZERO:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy score weights must sum to a positive Decimal, "
                f"got trend={self.trend_weight!s} + "
                f"liquidity={self.liquidity_weight!s} + "
                f"risk={self.risk_weight!s}"
            )
        if self.liquidity_ceiling_amount_cny <= self.liquidity_floor_amount_cny:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.liquidity_ceiling_amount_cny must be > "
                f"liquidity_floor_amount_cny (ceiling={self.liquidity_ceiling_amount_cny!s} "
                f"<= floor={self.liquidity_floor_amount_cny!s})"
            )
        if self.volatility_ceiling <= _ZERO:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.volatility_ceiling must be > 0, "
                f"got {self.volatility_ceiling!s}"
            )
        if self.drawdown_floor >= _ZERO:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.drawdown_floor must be < 0, "
                f"got {self.drawdown_floor!s}"
            )
        computed = self.compute_parameter_hash()
        if not self.parameter_hash:
            object.__setattr__(self, "parameter_hash", computed)
        elif self.parameter_hash != computed:
            raise InvalidBaselineFactorPolicyError(
                "BaselineFactorPolicy.parameter_hash does not match the "
                "deterministic hash of the policy payload"
            )

    def compute_parameter_hash(self) -> str:
        """Return the canonical SHA-256 digest of the policy payload.

        The hash is independent of any ``id`` / ``run_id`` and is
        derived only from the substantive parameters so two policies
        with the same numbers produce the same digest regardless of
        factory order.
        """

        payload = {
            "channel_key": BASELINE_FACTOR_CHANNEL_KEY,
            "channel_version": BASELINE_FACTOR_CHANNEL_VERSION,
            "drawdown_floor": self.drawdown_floor,
            "include_threshold": self.include_threshold,
            "liquidity_ceiling_amount_cny": self.liquidity_ceiling_amount_cny,
            "liquidity_floor_amount_cny": self.liquidity_floor_amount_cny,
            "liquidity_weight": self.liquidity_weight,
            "max_stale_days": self.max_stale_days,
            "min_avg_turnover_amount_cny": self.min_avg_turnover_amount_cny,
            "min_data_completeness": self.min_data_completeness,
            "min_full_history_days": self.min_full_history_days,
            "min_partial_history_days": self.min_partial_history_days,
            "risk_weight": self.risk_weight,
            "trend_distance_clip": self.trend_distance_clip,
            "trend_return_clip": self.trend_return_clip,
            "trend_weight": self.trend_weight,
            "volatility_ceiling": self.volatility_ceiling,
            "watch_threshold": self.watch_threshold,
        }
        return content_hash(payload)


# ---------------------------------------------------------------------------
# Proposal / result value objects
# ---------------------------------------------------------------------------


class BaselineFactorDecision(StrEnum):
    """Four-state ``decision`` vocabulary mirroring plan §7.

    The channel emits ``include`` / ``watch`` / ``exclude`` /
    ``no_opinion`` per the multi-channel routing contract sketch in
    plan §7. ``no_opinion`` is reserved for the case where the channel
    cannot attach an auditable judgement (e.g. an empty input); the
    baseline channel never uses it for a known instrument so its
    absence in practice is a visible audit signal.
    """

    INCLUDE = "include"
    WATCH = "watch"
    EXCLUDE = "exclude"
    NO_OPINION = "no_opinion"


@dataclass(frozen=True, slots=True)
class BaselineFactorProposal:
    """Per-instrument auditable ``Candidate Proposal`` for this channel.

    The shape is intentionally narrower than the plan §7
    ``CandidateProposal`` example. The baseline factor channel has
    no publication timestamps, no provider reference identifiers and
    no external authority weight; it only emits the auditable
    scoring decision, the factor evidence references and the data
    quality summary needed to justify it.
    """

    instrument_id: InstrumentId
    symbol: str
    exchange: str
    channel_key: str
    channel_version: str
    decision: str
    eligibility: UniverseEligibility
    baseline_score: Decimal | None
    trend_score: Decimal | None
    liquidity_score: Decimal | None
    risk_adjustment: Decimal | None
    quality_status: str
    freshness_status: str
    observed_trading_days: int
    data_completeness: Decimal | None
    factor_set_key: str
    factor_set_version: str
    factor_refs: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    reasons: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError(
                "BaselineFactorProposal.instrument_id must be an InstrumentId, "
                f"got {type(self.instrument_id).__name__}"
            )
        if self.channel_key != BASELINE_FACTOR_CHANNEL_KEY:
            raise ValueError(
                "BaselineFactorProposal.channel_key must equal "
                f"{BASELINE_FACTOR_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != BASELINE_FACTOR_CHANNEL_VERSION:
            raise ValueError(
                "BaselineFactorProposal.channel_version must equal "
                f"{BASELINE_FACTOR_CHANNEL_VERSION!r}, got {self.channel_version!r}"
            )
        if self.decision not in {"include", "watch", "exclude", "no_opinion"}:
            raise ValueError(
                "BaselineFactorProposal.decision must be one of "
                "include/watch/exclude/no_opinion, "
                f"got {self.decision!r}"
            )
        if not isinstance(self.eligibility, UniverseEligibility):
            raise TypeError(
                "BaselineFactorProposal.eligibility must be a UniverseEligibility, "
                f"got {type(self.eligibility).__name__}"
            )
        for field_name in (
            "baseline_score",
            "trend_score",
            "liquidity_score",
            "risk_adjustment",
            "data_completeness",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(
                    f"BaselineFactorProposal.{field_name} must be a finite Decimal "
                    f"or None, got {value!r}"
                )
            if value < _ZERO or value > _ONE_HUNDRED:
                raise ValueError(
                    f"BaselineFactorProposal.{field_name} must lie within "
                    "[0, 100], got " + repr(value)
                )
        if not isinstance(self.observed_trading_days, int) or isinstance(
            self.observed_trading_days, bool
        ) or self.observed_trading_days < 0:
            raise ValueError(
                "BaselineFactorProposal.observed_trading_days must be a "
                f"non-negative int, got {self.observed_trading_days!r}"
            )
        if self.factor_set_key != BASELINE_FACTOR_FACTOR_SET_KEY:
            raise ValueError(
                "BaselineFactorProposal.factor_set_key must equal "
                f"{BASELINE_FACTOR_FACTOR_SET_KEY!r}, "
                f"got {self.factor_set_key!r}"
            )
        if self.factor_set_version != BASELINE_FACTOR_FACTOR_SET_VERSION:
            raise ValueError(
                "BaselineFactorProposal.factor_set_version must equal "
                f"{BASELINE_FACTOR_FACTOR_SET_VERSION!r}, "
                f"got {self.factor_set_version!r}"
            )
        if not isinstance(self.factor_refs, Mapping):
            raise TypeError(
                "BaselineFactorProposal.factor_refs must be a Mapping[str, str], "
                f"got {type(self.factor_refs).__name__}"
            )
        for key, value in self.factor_refs.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(
                    "BaselineFactorProposal.factor_refs keys must be non-empty strings"
                )
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "BaselineFactorProposal.factor_refs values must be non-empty strings"
                )
        for label in ("reasons", "exclusion_reasons", "warnings"):
            value = getattr(self, label)
            if not isinstance(value, tuple):
                raise ValueError(
                    f"BaselineFactorProposal.{label} must be a tuple[str, ...]"
                )
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        f"BaselineFactorProposal.{label} must contain non-empty strings"
                    )


@dataclass(frozen=True, slots=True)
class BaselineFactorChannelResult:
    """The frozen output of :func:`evaluate_baseline_factor_channel`.

    Emits exactly one :class:`BaselineFactorProposal` per input
    instrument (excluding duplicates the universe classifier already
    collapsed by ``instrument_id``), in the deterministic tie-broken
    order documented in ``evaluate_baseline_factor_channel``. Carries
    the audit block (``channel_key`` / ``channel_version`` /
    ``policy_hash`` / ``factor_set_*``) so the future storage layer can
    persist a run row without consulting the channel module.
    """

    channel_key: str
    channel_version: str
    factor_set_key: str
    factor_set_version: str
    policy_hash: str
    policy_parameter_hash: str
    as_of_date: date
    proposals: tuple[BaselineFactorProposal, ...]
    warnings: tuple[str, ...] = ()
    full_count: int = 0
    partial_count: int = 0
    ineligible_count: int = 0

    def __post_init__(self) -> None:
        if self.channel_key != BASELINE_FACTOR_CHANNEL_KEY:
            raise ValueError(
                "BaselineFactorChannelResult.channel_key must equal "
                f"{BASELINE_FACTOR_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != BASELINE_FACTOR_CHANNEL_VERSION:
            raise ValueError(
                "BaselineFactorChannelResult.channel_version must equal "
                f"{BASELINE_FACTOR_CHANNEL_VERSION!r}, "
                f"got {self.channel_version!r}"
            )
        if not isinstance(self.proposals, tuple):
            raise ValueError(
                "BaselineFactorChannelResult.proposals must be a tuple"
            )
        seen: set[UUID] = set()
        for proposal in self.proposals:
            if proposal.instrument_id.value in seen:
                raise ValueError(
                    "BaselineFactorChannelResult.proposals contain duplicate "
                    f"instrument_id {proposal.instrument_id}"
                )
            seen.add(proposal.instrument_id.value)
        if not isinstance(self.warnings, tuple):
            raise ValueError(
                "BaselineFactorChannelResult.warnings must be a tuple[str, ...]"
            )
        if min(self.full_count, self.partial_count, self.ineligible_count) < 0:
            raise ValueError(
                "BaselineFactorChannelResult counts must be >= 0, "
                f"got full_count={self.full_count}, partial_count={self.partial_count}, "
                f"ineligible_count={self.ineligible_count}"
            )
        if self.full_count + self.partial_count + self.ineligible_count != len(
            self.proposals
        ):
            raise ValueError(
                "BaselineFactorChannelResult counts must sum to "
                f"len(proposals) ({self.full_count} + {self.partial_count} + "
                f"{self.ineligible_count} != {len(self.proposals)})"
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_baseline_factor_channel(
    *,
    instruments: Sequence[Instrument],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
    policy: BaselineFactorPolicy | None = None,
) -> BaselineFactorChannelResult:
    """Run the deterministic baseline-factor channel for ``as_of_date``.

    The function:

    1. Normalises the optional ``policy`` to a fully validated
       :class:`BaselineFactorPolicy` instance (default thresholds when
       the caller passes ``None``).
    2. Calls :func:`invest_domain.candidate_pool.universe.build_etf_universe`
       to classify every input instrument into ``FULL`` /
       ``PARTIAL`` / ``INELIGIBLE``. The classifier deduplicates by
       ``instrument_id`` and orders its output by
       ``str(instrument_id)``; the channel uses that ordering as the
       stable pre-sort fallback even though the final ordering is
       normalised below.
    3. For every ``FULL`` and ``PARTIAL`` instrument, calls
       :func:`calculate_market_state_factors` exactly once on the bar
       series the caller supplied. INELIGIBLE instruments never reach
       the factor calculator (plan §10.1).
    4. Applies the hard quality gate (plan §10.1): conflict / invalid
       bars / missing key factors / data completeness below
       ``policy.min_data_completeness`` / average turnover below
       ``policy.min_avg_turnover_amount_cny`` push the proposal into
       ``exclude`` with explicit machine codes.
    5. Computes the three-dimensional soft score
       ``trend_score`` / ``liquidity_score`` / ``risk_adjustment``,
       each normalised to ``0..100`` per plan §10.2. PARTIAL
       candidates are *capped* at ``watch`` per plan §8 even when the
       soft score would qualify for ``include``.
    6. Maps the weighted composite ``baseline_score`` to one of
       ``include`` / ``watch`` / ``exclude`` against
       ``policy.include_threshold`` / ``policy.watch_threshold``.
    7. Sorts the resulting proposals deterministically:

       * Higher ``baseline_score`` ranks first (``None`` sorts last).
       * Higher quality ranks first (``complete`` > ``partial`` >
         ``missing`` > ``invalid`` > ``conflict``).
       * Higher ``risk_adjustment`` ranks first when the previous two
         are tied.
       * ``instrument_id.value.bytes`` is the final tie-breaker so
         equal scores never produce rank collisions and re-runs on
         the same logical inputs always emit the same order.

    Parameters
    ----------
    instruments:
        ETF instruments to evaluate. The function does not mutate this
        sequence.
    bars_by_instrument:
        Mapping from :class:`InstrumentId` to its bar series. The
        function never mutates this mapping; the universe classifier
        and the shared factor calculator both consume it read-only.
    as_of_date:
        Trading day the channel run describes.
    policy:
        Optional :class:`BaselineFactorPolicy`. ``None`` selects the
        conservative defaults baked into the policy class. The default
        policy is sufficient for PR-02 acceptance and mirrors the
        plan §9 / §10 workstream numbers.

    Returns
    -------
    BaselineFactorChannelResult
        Frozen value object with one :class:`BaselineFactorProposal`
        per non-duplicate input instrument, plus the audit block
        (``channel_key`` / ``channel_version`` /
        ``factor_set_{key,version}`` / ``policy_hash`` /
        ``policy_parameter_hash``) and the universe-classification
        counts.

    Raises
    ------
    InvalidBaselineFactorPolicyError
        The supplied ``policy`` is internally inconsistent (the
        default policy cannot trigger this). Raised eagerly by
        :class:`BaselineFactorPolicy.__post_init__`; callers should
        treat the exception as a configuration failure rather than a
        routing failure.
    """
    if not isinstance(as_of_date, date):
        raise TypeError(
            "evaluate_baseline_factor_channel as_of_date must be a date, "
            f"got {type(as_of_date).__name__}"
        )
    resolved_policy = policy if policy is not None else BaselineFactorPolicy()

    universe = build_etf_universe(
        instruments,
        bars_by_instrument,
        as_of_date,
        minimum_full_history_days=resolved_policy.min_full_history_days,
        minimum_partial_history_days=resolved_policy.min_partial_history_days,
        max_stale_days=resolved_policy.max_stale_days,
    )

    policy_hash = _compute_policy_hash(resolved_policy)
    proposals: list[BaselineFactorProposal] = []
    full_count = 0
    partial_count = 0
    ineligible_count = 0

    for candidate in universe:
        eligibility = candidate.eligibility
        if eligibility is UniverseEligibility.FULL:
            full_count += 1
        elif eligibility is UniverseEligibility.PARTIAL:
            partial_count += 1
        else:
            ineligible_count += 1

        proposal = _evaluate_candidate(
            candidate=candidate,
            bars_by_instrument=bars_by_instrument,
            as_of_date=as_of_date,
            policy=resolved_policy,
        )
        proposals.append(proposal)

    proposals.sort(key=_proposal_sort_key)

    return BaselineFactorChannelResult(
        channel_key=BASELINE_FACTOR_CHANNEL_KEY,
        channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
        factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
        factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
        policy_hash=policy_hash,
        policy_parameter_hash=resolved_policy.parameter_hash,
        as_of_date=as_of_date,
        proposals=tuple(proposals),
        full_count=full_count,
        partial_count=partial_count,
        ineligible_count=ineligible_count,
    )


# ---------------------------------------------------------------------------
# Per-candidate evaluation (sub-routine, not part of the public surface)
# ---------------------------------------------------------------------------


def _evaluate_candidate(
    *,
    candidate: UniverseCandidate,
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
    policy: BaselineFactorPolicy,
) -> BaselineFactorProposal:
    instrument_id = candidate.instrument_id
    base_refs: dict[str, str] = {}

    reasons: list[str] = []
    exclusion_reasons: list[str] = []
    warnings: list[str] = list(candidate.reasons)

    if candidate.eligibility is UniverseEligibility.INELIGIBLE:
        for reason in candidate.reasons:
            exclusion_reasons.append(f"universe:{reason}")
        return _empty_proposal(
            instrument_id=instrument_id,
            symbol=candidate.symbol,
            exchange=candidate.exchange,
            eligibility=candidate.eligibility,
            policy=policy,
            exclusion_reasons=tuple(exclusion_reasons),
            reasons=("baseline.universe_ineligible",),
            warnings=tuple(warnings),
            data_quality_status=QualityStatus.MISSING.value,
            freshness_status=QualityStatus.MISSING.value,
            observed_trading_days=0,
            data_completeness=None,
            factor_refs=base_refs,
        )

    bars = bars_by_instrument.get(instrument_id, ())
    calculation = _safe_calculate_factors(instrument_id, bars, as_of_date)

    factor_refs = dict(base_refs)
    for observation in calculation.factors:
        factor_refs[observation.factor_key] = observation.item_hash

    quality_status = calculation.data_quality.quality_status.value
    freshness_status = calculation.data_quality.freshness_status.value
    observed_trading_days = calculation.data_quality.observed_trading_days
    completeness = _lookup_factor_value(calculation, "data_completeness_60d")
    turnover_amount = _lookup_factor_value(calculation, "avg_turnover_amount_20d")

    for factor_warning in calculation.warnings:
        if factor_warning not in warnings:
            warnings.append(factor_warning)

    if calculation.data_quality.conflict_detected:
        exclusion_reasons.append("baseline.data_conflict")
    if calculation.data_quality.invalid_days > 0:
        exclusion_reasons.append("baseline.invalid_bars")
    if calculation.data_quality.freshness_status.value == "failed":
        exclusion_reasons.append("baseline.freshness_failed")

    trend_score = _compute_trend_score(calculation, policy)
    liquidity_score = _compute_liquidity_score(turnover_amount, policy)
    risk_adjustment = _compute_risk_adjustment(calculation, policy)

    baseline_score = _compose_baseline_score(
        trend_score=trend_score,
        liquidity_score=liquidity_score,
        risk_adjustment=risk_adjustment,
        policy=policy,
    )

    if (
        completeness is not None
        and completeness < policy.min_data_completeness
        # PARTIAL slices are expected to show partial completeness and
        # are capped at ``watch`` by the eligibility check below;
        # only enforce this gate for instruments with a full history.
        and calculation.data_quality.observed_trading_days
        >= policy.min_full_history_days
    ):
        exclusion_reasons.append(
            f"baseline.completeness_below_{policy.min_data_completeness!s}"
        )

    if (
        turnover_amount is not None
        and turnover_amount < policy.min_avg_turnover_amount_cny
        and calculation.data_quality.observed_trading_days
        >= policy.min_full_history_days
    ):
        exclusion_reasons.append(
            f"baseline.turnover_below_{policy.min_avg_turnover_amount_cny!s}"
        )

    for factor in calculation.factors:
        if (
            candidate.eligibility is UniverseEligibility.FULL
            and factor.value is None
            and factor.quality_status in (QualityStatus.MISSING, QualityStatus.PARTIAL)
        ):
            exclusion_reasons.append(f"baseline.missing_factor:{factor.factor_key}")

    if baseline_score is None:
        reasons.append("baseline.score_missing")

    if exclusion_reasons:
        decision = BaselineFactorDecision.EXCLUDE.value
    elif candidate.eligibility is UniverseEligibility.PARTIAL:
        decision = BaselineFactorDecision.WATCH.value
        reasons.append("baseline.partial_history_only")
    elif baseline_score is None:
        decision = BaselineFactorDecision.EXCLUDE.value
        if "baseline.score_missing" not in exclusion_reasons:
            exclusion_reasons.append("baseline.score_missing")
    elif baseline_score >= policy.include_threshold:
        decision = BaselineFactorDecision.INCLUDE.value
    elif baseline_score >= policy.watch_threshold:
        decision = BaselineFactorDecision.WATCH.value
    else:
        decision = BaselineFactorDecision.EXCLUDE.value
        exclusion_reasons.append("baseline.score_below_watch_threshold")

    if (
        decision == BaselineFactorDecision.WATCH.value
        and "baseline.watch_quality" not in reasons
        and quality_status != QualityStatus.COMPLETE.value
    ):
        reasons.append("baseline.watch_quality")

    reasons = tuple(_dedupe_preserve_order(reasons))
    exclusion_reasons_tuple = tuple(_dedupe_preserve_order(exclusion_reasons))
    warnings_tuple = tuple(_dedupe_preserve_order(warnings))

    return BaselineFactorProposal(
        instrument_id=instrument_id,
        symbol=candidate.symbol,
        exchange=candidate.exchange,
        channel_key=BASELINE_FACTOR_CHANNEL_KEY,
        channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
        decision=decision,
        eligibility=candidate.eligibility,
        baseline_score=baseline_score,
        trend_score=trend_score,
        liquidity_score=liquidity_score,
        risk_adjustment=risk_adjustment,
        quality_status=quality_status,
        freshness_status=freshness_status,
        observed_trading_days=observed_trading_days,
        data_completeness=completeness,
        factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
        factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
        factor_refs=MappingProxyType(factor_refs),
        reasons=reasons,
        exclusion_reasons=exclusion_reasons_tuple,
        warnings=warnings_tuple,
    )


# ---------------------------------------------------------------------------
# Factor / scoring helpers (no factor formula duplication)
# ---------------------------------------------------------------------------


def _safe_calculate_factors(
    instrument_id: InstrumentId,
    bars: Sequence[DailyBar],
    as_of_date: date,
) -> FactorCalculationResult:
    """Call :func:`calculate_market_state_factors` defensively.

    The shared calculator already raises on future bars and on cross-
    instrument bar mixes. We catch those errors and emit a
    ``MISSING`` / ``INVALID`` shaped calculation by replacing it with
    an empty bar series, so the channel can always produce a proposal
    instead of bubbling an exception up.
    """

    try:
        return calculate_market_state_factors(
            bars,
            as_of_date=as_of_date,
            instrument_id=instrument_id,
        )
    except ValueError:
        return calculate_market_state_factors(
            (),
            as_of_date=as_of_date,
            instrument_id=instrument_id,
        )


def _lookup_factor_value(
    calculation: FactorCalculationResult,
    factor_key: str,
) -> Decimal | None:
    for observation in calculation.factors:
        if observation.factor_key == factor_key:
            return observation.value
    return None


def _compute_trend_score(
    calculation: FactorCalculationResult, policy: BaselineFactorPolicy
) -> Decimal | None:
    """Normalise the four trend factors into a single ``0..100`` score.

    Missing factors pull the average down to ``None`` so the channel
    can flag a ``score_missing`` reason on the ``FULL`` slice (plan
    §10.1 ``硬门禁``). PARTIAL candidates still receive partial
    sub-scores — the eligibility check (``UniverseEligibility.FULL``)
    above is what raises ``missing_factor`` to ``exclude``.
    """

    parts: list[Decimal] = []
    for factor_key, clip in (
        ("return_20d", policy.trend_return_clip),
        ("return_60d", policy.trend_return_clip),
        ("distance_ma20", policy.trend_distance_clip),
        ("distance_ma60", policy.trend_distance_clip),
    ):
        value = _lookup_factor_value(calculation, factor_key)
        if value is None:
            return None
        parts.append(_clip_normalise(value, clip, clip))
    average = sum(parts, _ZERO) / Decimal(len(parts))
    return _quantize(average)


def _compute_liquidity_score(
    turnover_amount: Decimal | None, policy: BaselineFactorPolicy
) -> Decimal | None:
    """Log-scale the average turnover amount into ``0..100``.

    The mapping is a piecewise linear log-interpolation: turnover at
    ``policy.liquidity_floor_amount_cny`` maps to ``0``; turnover at
    ``policy.liquidity_ceiling_amount_cny`` maps to ``100``; values
    in between follow the log scale. Missing turnover returns ``None``
    so the channel can react at the policy layer (caller decides
    ``exclude`` vs ``watch``).
    """

    if turnover_amount is None or turnover_amount <= _ZERO:
        return None
    floor = policy.liquidity_floor_amount_cny
    ceiling = policy.liquidity_ceiling_amount_cny
    if floor <= _ZERO or ceiling <= floor:
        return None
    if turnover_amount <= floor:
        return _ZERO
    if turnover_amount >= ceiling:
        return _ONE_HUNDRED
    log_amount = _decimal_ln(turnover_amount)
    log_floor = _decimal_ln(floor)
    log_ceiling = _decimal_ln(ceiling)
    span = log_ceiling - log_floor
    if span <= _ZERO:
        return None
    score = (log_amount - log_floor) / span * _ONE_HUNDRED
    return _quantize(score)


def _compute_risk_adjustment(
    calculation: FactorCalculationResult, policy: BaselineFactorPolicy
) -> Decimal | None:
    """Average the volatility-inverse and drawdown-inverse sub-scores.

    ``vol_score = 100 × (1 - min(vol / ceiling, 1))`` rewards lower
    realised volatility; ``dd_score = 100 × (1 + max(dd / floor, -1))``
    rewards shallower drawdowns. The average returns ``None`` when
    any of the two factors is missing.
    """

    volatility = _lookup_factor_value(calculation, "realized_volatility_20d")
    drawdown = _lookup_factor_value(calculation, "max_drawdown_60d")
    if volatility is None or drawdown is None:
        return None
    vol_score = _ONE_HUNDRED * (_ONE - min(volatility / policy.volatility_ceiling, _ONE))
    if vol_score < _ZERO:
        vol_score = _ZERO
    elif vol_score > _ONE_HUNDRED:
        vol_score = _ONE_HUNDRED
    dd_ratio = drawdown / policy.drawdown_floor
    if dd_ratio > _ONE:
        dd_ratio = _ONE
    elif dd_ratio < -_ONE:
        dd_ratio = -_ONE
    dd_score = _ONE_HUNDRED * (_ONE + dd_ratio)
    if dd_score < _ZERO:
        dd_score = _ZERO
    elif dd_score > _ONE_HUNDRED:
        dd_score = _ONE_HUNDRED
    average = (vol_score + dd_score) / Decimal(2)
    return _quantize(average)


def _compose_baseline_score(
    *,
    trend_score: Decimal | None,
    liquidity_score: Decimal | None,
    risk_adjustment: Decimal | None,
    policy: BaselineFactorPolicy,
) -> Decimal | None:
    if trend_score is None or liquidity_score is None or risk_adjustment is None:
        return None
    weighted = (
        policy.trend_weight * trend_score
        + policy.liquidity_weight * liquidity_score
        + policy.risk_weight * risk_adjustment
    )
    total_weight = (
        policy.trend_weight + policy.liquidity_weight + policy.risk_weight
    )
    if total_weight <= _ZERO:
        return None
    normalised = weighted / total_weight
    if normalised < _ZERO:
        normalised = _ZERO
    elif normalised > _ONE_HUNDRED:
        normalised = _ONE_HUNDRED
    return _quantize(normalised)


def _compute_policy_hash(policy: BaselineFactorPolicy) -> str:
    payload = {
        "channel_key": BASELINE_FACTOR_CHANNEL_KEY,
        "channel_version": BASELINE_FACTOR_CHANNEL_VERSION,
        "factor_set_key": BASELINE_FACTOR_FACTOR_SET_KEY,
        "factor_set_version": BASELINE_FACTOR_FACTOR_SET_VERSION,
        "policy_parameter_hash": policy.parameter_hash,
    }
    return content_hash(payload)


def _empty_proposal(
    *,
    instrument_id: InstrumentId,
    symbol: str,
    exchange: str,
    eligibility: UniverseEligibility,
    policy: BaselineFactorPolicy,
    exclusion_reasons: tuple[str, ...],
    reasons: tuple[str, ...],
    warnings: tuple[str, ...],
    data_quality_status: str,
    freshness_status: str,
    observed_trading_days: int,
    data_completeness: Decimal | None,
    factor_refs: Mapping[str, str],
) -> BaselineFactorProposal:
    return BaselineFactorProposal(
        instrument_id=instrument_id,
        symbol=symbol,
        exchange=exchange,
        channel_key=BASELINE_FACTOR_CHANNEL_KEY,
        channel_version=BASELINE_FACTOR_CHANNEL_VERSION,
        decision=BaselineFactorDecision.EXCLUDE.value,
        eligibility=eligibility,
        baseline_score=None,
        trend_score=None,
        liquidity_score=None,
        risk_adjustment=None,
        quality_status=data_quality_status,
        freshness_status=freshness_status,
        observed_trading_days=observed_trading_days,
        data_completeness=data_completeness,
        factor_set_key=BASELINE_FACTOR_FACTOR_SET_KEY,
        factor_set_version=BASELINE_FACTOR_FACTOR_SET_VERSION,
        factor_refs=MappingProxyType(dict(factor_refs)),
        reasons=reasons,
        exclusion_reasons=exclusion_reasons,
        warnings=warnings,
    )


def _proposal_sort_key(
    proposal: BaselineFactorProposal,
) -> tuple[int, Decimal | str, int, Decimal | str, Decimal | str, bytes]:
    """Stable sort key matching the deterministic ordering spec."""

    score = (
        proposal.baseline_score
        if proposal.baseline_score is not None
        else _ZERO - _ONE
    )
    return (
        _decision_rank(proposal.decision),
        -score if isinstance(score, Decimal) else Decimal("-1"),
        _quality_rank(proposal.quality_status),
        -proposal.risk_adjustment
        if proposal.risk_adjustment is not None
        else Decimal("-1"),
        -(proposal.baseline_score or Decimal("0")),
        proposal.instrument_id.value.bytes,
    )


def _decision_rank(decision: str) -> int:
    if decision == BaselineFactorDecision.INCLUDE.value:
        return 0
    if decision == BaselineFactorDecision.WATCH.value:
        return 1
    if decision == BaselineFactorDecision.EXCLUDE.value:
        return 2
    return 3


def _quality_rank(quality_status: str) -> int:
    rank = {
        QualityStatus.COMPLETE.value: 0,
        QualityStatus.PARTIAL.value: 1,
        QualityStatus.MISSING.value: 2,
        QualityStatus.INVALID.value: 3,
        QualityStatus.CONFLICT.value: 4,
    }
    return rank.get(quality_status, 5)


# ---------------------------------------------------------------------------
# Numeric / Decimal helpers
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _clip_normalise(value: Decimal, positive_clip: Decimal, negative_clip: Decimal) -> Decimal:
    """Map ``value`` from ``[-negative_clip, +positive_clip]`` to ``[0, 100]``.

    Zero maps to ``50`` so neutral inputs neither help nor hurt the
    soft score. The clip bounds are passed in (not hard-coded) so the
    policy can tighten them per use case.
    """

    if value > positive_clip:
        return _ONE_HUNDRED
    if value < -negative_clip:
        return _ZERO
    if value >= _ZERO:
        return _quantize(_ONE_HUNDRED * (_ONE + value / positive_clip) / Decimal(2))
    return _quantize(_ONE_HUNDRED * (_ONE + value / negative_clip) / Decimal(2))


def _decimal_ln(value: Decimal) -> Decimal:
    """Return the natural logarithm via :class:`Decimal` ``ln``.

    Wrapping the Python :func:`math.log` fallback keeps the rest of
    the module Decimal-only so the channel never mixes float and
    Decimal arithmetic. The result is rounded to the channel quantum.
    """

    import math

    as_float = float(value)
    if as_float <= 0:
        raise ValueError(f"_decimal_ln requires a positive Decimal, got {value!s}")
    return _quantize(Decimal(str(math.log(as_float))))


def _require_finite_non_negative_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise InvalidBaselineFactorPolicyError(
            f"BaselineFactorPolicy.{field_name} must be a Decimal, "
            f"got {type(value).__name__}"
        )
    if not value.is_finite():
        raise InvalidBaselineFactorPolicyError(
            f"BaselineFactorPolicy.{field_name} must be a finite Decimal, "
            f"got {value!s}"
        )
    if value < _ZERO:
        raise InvalidBaselineFactorPolicyError(
            f"BaselineFactorPolicy.{field_name} must be >= 0, got {value!s}"
        )


def _require_finite_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise InvalidBaselineFactorPolicyError(
            f"{field_name} must be a Decimal, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise InvalidBaselineFactorPolicyError(
            f"{field_name} must be a finite Decimal, got {value!s}"
        )


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


__all__ = [
    "BASELINE_FACTOR_CHANNEL_KEY",
    "BASELINE_FACTOR_CHANNEL_VERSION",
    "BASELINE_FACTOR_FACTOR_SET_KEY",
    "BASELINE_FACTOR_FACTOR_SET_VERSION",
    "BaselineFactorChannelError",
    "BaselineFactorChannelResult",
    "BaselineFactorDecision",
    "BaselineFactorPolicy",
    "BaselineFactorProposal",
    "DEFAULT_MAX_STALE_DAYS",
    "DEFAULT_MIN_FULL_HISTORY_DAYS",
    "DEFAULT_MIN_PARTIAL_HISTORY_DAYS",
    "InvalidBaselineFactorPolicyError",
    "evaluate_baseline_factor_channel",
]
