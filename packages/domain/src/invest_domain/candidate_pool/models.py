"""Pure domain models for the ``candidate_pool`` bounded context.

The module contains:

- The state machine (:class:`CandidatePoolStatus` + :class:`CandidatePoolRun`)
  that records the lifecycle of one calculation; only the transitions
  approved in M0-DECISIONS §2 are legal, and terminal states are irreversible.
- The input contract (:class:`CalculationContext`,
  :class:`CandidatePoolPolicy`, :class:`EligibilityCriteria`,
  :class:`LiquidityCriteria`, :class:`PriceQualityCriteria`,
  :class:`RiskCriteria`, :class:`SelectionCriteria`) consumed by the pure
  ``build_candidate_pool`` function. None of these values come from the
  environment — they are passed explicitly.
- The output contract (:class:`RuleOutcome`, :class:`ExclusionReason`,
  :class:`CandidatePoolItem`, :class:`CandidatePoolSummary`,
  :class:`CandidatePoolResult`) carrying enough explanation per
  ADR-0008 / plan §5.6/§5.7 to audit every include / exclude decision.

The M1 increment does not include a candidate pool algorithm. Only the
contracts are defined so that storage, application services and the
calculator can be wired in M2+.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from invest_domain.shared.canonical import CANONICAL_HASH_SCHEMA_VERSION, content_hash

if TYPE_CHECKING:
    from invest_domain.instruments.models import Instrument, InstrumentId
    from invest_domain.market_data.models import DailyBar


# Module-level constant for the canonical score-weight keys. Living
# outside :class:`ScoreWeights` keeps the dataclass-slot machinery from
# turning it into a per-instance field.
_SCORE_WEIGHT_KEYS: tuple[str, ...] = (
    "liquidity",
    "stability",
    "data_quality",
    "listing_maturity",
)


class CandidatePoolStatus(StrEnum):
    """Lifecycle states for a :class:`CandidatePoolRun`.

    Mirrors M0-DECISIONS §2 / ADR-0008. The only legal transitions are:

    - ``CALCULATED`` -> ``VALIDATED``
    - ``VALIDATED`` -> ``PUBLISHED``
    - ``VALIDATED`` -> ``REJECTED``

    ``PUBLISHED`` and ``REJECTED`` are terminal; the run can be superseded
    only by a new run, never by reverting its own state.
    """

    CALCULATED = "calculated"
    VALIDATED = "validated"
    PUBLISHED = "published"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in (CandidatePoolStatus.PUBLISHED, CandidatePoolStatus.REJECTED)

    def can_transition_to(self, target: "CandidatePoolStatus") -> bool:
        if self.is_terminal:
            return False
        if self is CandidatePoolStatus.CALCULATED:
            return target is CandidatePoolStatus.VALIDATED
        if self is CandidatePoolStatus.VALIDATED:
            return target in (
                CandidatePoolStatus.PUBLISHED,
                CandidatePoolStatus.REJECTED,
            )
        return False


class RuleSeverity(StrEnum):
    """Severity tiers for a :class:`RuleOutcome` and quality report.

    Mirrors plan §5.5 / ADR-0010 ``data_quality_results.severity``.
    """

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ExclusionReason:
    """Machine-readable reason an instrument was excluded from the pool.

    The ``code`` is a stable string (``min_listing_days``, ``liquidity``,
    ``suspended``, ...) so that downstream tools can group reasons without
    parsing free text. The ``message`` is a human-readable explanation
    and is intentionally non-canonical.
    """

    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("ExclusionReason.code must not be empty")
        if not self.message or not self.message.strip():
            raise ValueError("ExclusionReason.message must not be empty")


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Outcome of one rule applied to one instrument.

    ``value`` and ``threshold`` are optional Decimal; rules that produce
    a boolean result can leave them as ``None``.
    """

    rule_key: str
    passed: bool
    severity: RuleSeverity = RuleSeverity.ERROR
    value: Decimal | None = None
    threshold: Decimal | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_key or not self.rule_key.strip():
            raise ValueError("RuleOutcome.rule_key must not be empty")
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError(
                f"RuleOutcome.value must be a Decimal or None, got {type(self.value).__name__}"
            )
        if self.threshold is not None and not isinstance(self.threshold, Decimal):
            raise TypeError(
                "RuleOutcome.threshold must be a Decimal or None, "
                f"got {type(self.threshold).__name__}"
            )
        if self.value is not None and not self.value.is_finite():
            raise ValueError(f"RuleOutcome.value must be a finite Decimal, got {self.value!s}")
        if self.threshold is not None and not self.threshold.is_finite():
            raise ValueError(
                f"RuleOutcome.threshold must be a finite Decimal, got {self.threshold!s}"
            )


@dataclass(frozen=True, slots=True)
class EligibilityCriteria:
    """Hard eligibility filters applied before scoring.

    The plan §9.2 example thresholds are intentionally **not** encoded
    here as production constants; ``min_listing_days`` and the allowed
    exchanges are policy inputs that the user must confirm via O-5
    before they enter a versioned policy set.

    ``min_volume`` / ``min_amount`` are the basic OHLCV thresholds
    consumed by the PR-08 minimum candidate-pool calculator. The richer
    liquidity rule (rolling-window median) is layered on top of these in
    M4; here they default to ``Decimal("0")`` so the higher-level
    liquidity filter is the only active gate when callers leave the
    defaults in place.
    """

    min_listing_days: int = 0
    require_current_day_bar: bool = True
    exclude_suspended: bool = True
    min_volume: Decimal = Decimal("0")
    min_amount: Decimal = Decimal("0")
    allowed_exchanges: tuple[str, ...] = ("SSE", "SZSE")

    def __post_init__(self) -> None:
        if self.min_listing_days < 0:
            raise ValueError(
                f"EligibilityCriteria.min_listing_days must be >= 0, got {self.min_listing_days}"
            )
        _require_non_negative_decimal(
            self.min_volume, field_name="EligibilityCriteria.min_volume"
        )
        _require_non_negative_decimal(
            self.min_amount, field_name="EligibilityCriteria.min_amount"
        )
        if not self.allowed_exchanges:
            raise ValueError("EligibilityCriteria.allowed_exchanges must not be empty")
        for exchange in self.allowed_exchanges:
            if not exchange or not exchange.strip():
                raise ValueError(
                    "EligibilityCriteria.allowed_exchanges must not contain empty entries"
                )


@dataclass(frozen=True, slots=True)
class LiquidityCriteria:
    """Lookback-window structural parameters for the liquidity rule.

    No numeric thresholds are baked in here; the policy decides the
    concrete ``min_median_amount_cny`` value. Keeping the shape in the
    domain lets the calculator (M4) and the storage layer reason about
    the rule without parsing free text.
    """

    lookback_days: int
    min_valid_days: int

    def __post_init__(self) -> None:
        if self.lookback_days <= 0:
            raise ValueError(
                f"LiquidityCriteria.lookback_days must be > 0, got {self.lookback_days}"
            )
        if self.min_valid_days <= 0:
            raise ValueError(
                f"LiquidityCriteria.min_valid_days must be > 0, got {self.min_valid_days}"
            )
        if self.min_valid_days > self.lookback_days:
            raise ValueError(
                "LiquidityCriteria.min_valid_days must be <= lookback_days "
                f"({self.min_valid_days} > {self.lookback_days})"
            )


@dataclass(frozen=True, slots=True)
class PriceQualityCriteria:
    """Lookback-window parameters for the price-quality rule."""

    lookback_days: int
    max_missing_ratio: Decimal
    max_zero_volume_days: int

    def __post_init__(self) -> None:
        if self.lookback_days <= 0:
            raise ValueError(
                f"PriceQualityCriteria.lookback_days must be > 0, got {self.lookback_days}"
            )
        if not isinstance(self.max_missing_ratio, Decimal) or not (
            0 <= self.max_missing_ratio <= 1
        ):
            raise ValueError(
                "PriceQualityCriteria.max_missing_ratio must be a Decimal in [0, 1], "
                f"got {self.max_missing_ratio!r}"
            )
        if self.max_zero_volume_days < 0:
            raise ValueError(
                "PriceQualityCriteria.max_zero_volume_days must be >= 0, "
                f"got {self.max_zero_volume_days}"
            )


@dataclass(frozen=True, slots=True)
class RiskCriteria:
    """Lookback-window parameters for the risk rule."""

    volatility_lookback_days: int
    drawdown_lookback_days: int

    def __post_init__(self) -> None:
        if self.volatility_lookback_days <= 0:
            raise ValueError(
                "RiskCriteria.volatility_lookback_days must be > 0, "
                f"got {self.volatility_lookback_days}"
            )
        if self.drawdown_lookback_days <= 0:
            raise ValueError(
                "RiskCriteria.drawdown_lookback_days must be > 0, "
                f"got {self.drawdown_lookback_days}"
            )


@dataclass(frozen=True, slots=True)
class SelectionCriteria:
    """Top-level selection limits (rank-cut and pool-size bounds)."""

    max_candidates: int

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise ValueError(
                f"SelectionCriteria.max_candidates must be > 0, got {self.max_candidates}"
            )


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """Weights used to combine sub-scores into ``total_score``.

    Weights need not sum to 1.0; the calculator (M4) is responsible for
    normalising the final score. The domain only checks that every
    weight is a non-negative finite Decimal and the keys are the
    canonical set expected by the algorithm.
    """

    weights: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.weights, Mapping):
            raise TypeError(
                f"ScoreWeights.weights must be a Mapping, got {type(self.weights).__name__}"
            )
        missing = [key for key in _SCORE_WEIGHT_KEYS if key not in self.weights]
        if missing:
            raise ValueError(
                f"ScoreWeights.weights is missing required keys: {missing!r}"
            )
        unknown = sorted(set(self.weights) - set(_SCORE_WEIGHT_KEYS))
        if unknown:
            raise ValueError(
                f"ScoreWeights.weights contains unknown keys: {unknown!r}; "
                f"allowed: {list(_SCORE_WEIGHT_KEYS)}"
            )
        for key, value in self.weights.items():
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(
                    f"ScoreWeights.weights[{key!r}] must be a non-negative finite Decimal, "
                    f"got {value!r}"
                )


@dataclass(frozen=True, slots=True)
class CandidatePoolPolicy:
    """A versioned, immutable bundle of policy parameters for one run.

    The instance carries the algorithm key, version, parameter-set key
    and a deterministic ``parameter_hash`` so that storage can enforce
    the ADR-0008 unique constraint
    ``(trade_date, algorithm_key, algorithm_version, parameter_hash, input_snapshot_id)``
    without re-parsing the values. The structural criteria (windows, max
    candidates, score weights) are policy inputs; concrete numeric
    thresholds from plan §9.2 are not embedded because O-5 is unresolved.
    """

    algorithm_key: str
    algorithm_version: str
    parameter_set_key: str
    eligibility: EligibilityCriteria
    liquidity: LiquidityCriteria
    price_quality: PriceQualityCriteria
    risk: RiskCriteria
    selection: SelectionCriteria
    score_weights: ScoreWeights
    parameter_hash: str = ""
    hash_schema_version: int = CANONICAL_HASH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.algorithm_key or not self.algorithm_key.strip():
            raise ValueError("CandidatePoolPolicy.algorithm_key must not be empty")
        if not self.algorithm_version or not self.algorithm_version.strip():
            raise ValueError("CandidatePoolPolicy.algorithm_version must not be empty")
        if not self.parameter_set_key or not self.parameter_set_key.strip():
            raise ValueError("CandidatePoolPolicy.parameter_set_key must not be empty")
        if self.hash_schema_version != CANONICAL_HASH_SCHEMA_VERSION:
            raise ValueError(
                "CandidatePoolPolicy.hash_schema_version "
                f"{self.hash_schema_version} does not match the current canonical "
                f"version {CANONICAL_HASH_SCHEMA_VERSION}"
            )
        computed = self.compute_parameter_hash()
        if not self.parameter_hash:
            object.__setattr__(self, "parameter_hash", computed)
        elif self.parameter_hash != computed:
            raise ValueError(
                "CandidatePoolPolicy.parameter_hash does not match the deterministic hash "
                "of the policy payload"
            )

    def compute_parameter_hash(self) -> str:
        payload = {
            "algorithm_key": self.algorithm_key,
            "algorithm_version": self.algorithm_version,
            "eligibility": {
                "allowed_exchanges": list(self.eligibility.allowed_exchanges),
                "exclude_suspended": self.eligibility.exclude_suspended,
                "min_amount": self.eligibility.min_amount,
                "min_listing_days": self.eligibility.min_listing_days,
                "min_volume": self.eligibility.min_volume,
                "require_current_day_bar": self.eligibility.require_current_day_bar,
            },
            "hash_schema_version": self.hash_schema_version,
            "liquidity": {
                "lookback_days": self.liquidity.lookback_days,
                "min_valid_days": self.liquidity.min_valid_days,
            },
            "parameter_set_key": self.parameter_set_key,
            "price_quality": {
                "lookback_days": self.price_quality.lookback_days,
                "max_missing_ratio": self.price_quality.max_missing_ratio,
                "max_zero_volume_days": self.price_quality.max_zero_volume_days,
            },
            "risk": {
                "drawdown_lookback_days": self.risk.drawdown_lookback_days,
                "volatility_lookback_days": self.risk.volatility_lookback_days,
            },
            "score_weights": {
                key: self.score_weights.weights[key] for key in _SCORE_WEIGHT_KEYS
            },
            "selection": {"max_candidates": self.selection.max_candidates},
        }
        return content_hash(payload)


@dataclass(frozen=True, slots=True)
class CalculationContext:
    """Explicit input context for a candidate-pool calculation.

    Per ADR-0008, the calculator is a pure function. Every value that
    could otherwise be sourced from ``datetime.now()``,
    ``os.environ[...]`` or a global config is passed in here. ``as_of``
    is the run's "current" timestamp in UTC; ``trade_date`` is the
    local trading day in Asia/Shanghai (see ADR-0004).
    """

    trade_date: date
    as_of_utc: datetime
    input_snapshot_id: UUID
    pipeline_run_id: UUID | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware_utc(self.as_of_utc, "as_of_utc")
        if not isinstance(self.input_snapshot_id, UUID):
            raise TypeError(
                "CalculationContext.input_snapshot_id must be a UUID, "
                f"got {type(self.input_snapshot_id).__name__}"
            )
        if self.pipeline_run_id is not None and not isinstance(self.pipeline_run_id, UUID):
            raise TypeError(
                "CalculationContext.pipeline_run_id must be a UUID or None, "
                f"got {type(self.pipeline_run_id).__name__}"
            )
        if not isinstance(self.notes, tuple):
            raise ValueError("CalculationContext.notes must be a tuple[str, ...]")


@dataclass(frozen=True, slots=True)
class CandidatePoolItem:
    """The per-instrument judgment of a candidate pool run.

    Mirrors plan §5.7. Every input instrument must appear exactly once
    so that the result can explain both inclusions and exclusions
    (ADR-0008 / plan §5.7 last paragraph). ``rule_results`` and
    ``metrics`` are JSON-compatible mappings to keep the storage layer
    free of ORM-specific types.
    """

    instrument_id: "InstrumentId"
    included: bool
    rank: int | None
    total_score: Decimal | None
    metrics: Mapping[str, Decimal] = field(default_factory=dict)
    rule_results: tuple[RuleOutcome, ...] = ()
    exclusion_reasons: tuple[ExclusionReason, ...] = ()

    def __post_init__(self) -> None:
        from invest_domain.instruments.models import InstrumentId

        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError(
                "CandidatePoolItem.instrument_id must be an InstrumentId, "
                f"got {type(self.instrument_id).__name__}"
            )
        if self.included:
            if self.rank is None:
                raise ValueError("included items must have a rank")
            if self.rank < 1:
                raise ValueError(f"included item rank must be >= 1, got {self.rank}")
            if self.total_score is None:
                raise ValueError("included items must carry a total_score")
        else:
            if self.rank is not None:
                raise ValueError("excluded items must not carry a rank")
            if self.total_score is not None:
                raise ValueError("excluded items must not carry a total_score")
            if not self.exclusion_reasons:
                raise ValueError("excluded items must carry at least one exclusion reason")
        if self.total_score is not None and (
            not isinstance(self.total_score, Decimal) or not self.total_score.is_finite()
        ):
            raise ValueError(
                f"CandidatePoolItem.total_score must be a finite Decimal, got {self.total_score!r}"
            )
        if not isinstance(self.metrics, Mapping):
            raise TypeError(
                "CandidatePoolItem.metrics must be a Mapping[str, Decimal], "
                f"got {type(self.metrics).__name__}"
            )
        if not isinstance(self.rule_results, tuple):
            raise ValueError("CandidatePoolItem.rule_results must be a tuple[RuleOutcome, ...]")
        if not isinstance(self.exclusion_reasons, tuple):
            raise ValueError(
                "CandidatePoolItem.exclusion_reasons must be a tuple[ExclusionReason, ...]"
            )


@dataclass(frozen=True, slots=True)
class CandidatePoolSummary:
    """Aggregate counts and timing for a :class:`CandidatePoolResult`."""

    input_count: int
    included_count: int
    excluded_count: int
    rule_error_count: int
    rule_warn_count: int

    def __post_init__(self) -> None:
        if self.input_count < 0:
            raise ValueError(f"input_count must be >= 0, got {self.input_count}")
        if self.included_count < 0:
            raise ValueError(f"included_count must be >= 0, got {self.included_count}")
        if self.excluded_count < 0:
            raise ValueError(f"excluded_count must be >= 0, got {self.excluded_count}")
        if self.rule_error_count < 0:
            raise ValueError(f"rule_error_count must be >= 0, got {self.rule_error_count}")
        if self.rule_warn_count < 0:
            raise ValueError(f"rule_warn_count must be >= 0, got {self.rule_warn_count}")
        if self.included_count + self.excluded_count > self.input_count:
            raise ValueError(
                "included_count + excluded_count must be <= input_count "
                f"({self.included_count} + {self.excluded_count} > {self.input_count})"
            )


@dataclass(frozen=True, slots=True)
class CandidatePoolResult:
    """The output contract of :class:`CandidatePoolCalculator.build_candidate_pool`.

    Carries every per-instrument item plus an aggregate summary. The
    calculator does not need to enforce rank uniqueness or sort order;
    that contract is the storage layer's responsibility per ADR-0008.
    """

    policy: CandidatePoolPolicy
    context: CalculationContext
    items: tuple[CandidatePoolItem, ...]
    summary: CandidatePoolSummary

    def __post_init__(self) -> None:
        seen: set = set()
        for item in self.items:
            if item.instrument_id in seen:
                raise ValueError(
                    "CandidatePoolResult.items contains duplicate instrument_id "
                    f"{item.instrument_id!s}"
                )
            seen.add(item.instrument_id)
        if len(self.items) < self.summary.input_count:
            raise ValueError(
                "CandidatePoolResult.items count must be >= summary.input_count "
                f"({len(self.items)} < {self.summary.input_count})"
            )

    @property
    def included_items(self) -> tuple[CandidatePoolItem, ...]:
        return tuple(item for item in self.items if item.included)

    @property
    def excluded_items(self) -> tuple[CandidatePoolItem, ...]:
        return tuple(item for item in self.items if not item.included)


@dataclass(frozen=True, slots=True)
class CandidatePoolRun:
    """The persistent record of one candidate-pool calculation.

    Mirrors plan §5.6 (id, trade_date, algorithm_key, algorithm_version,
    parameter_set_key, parameter_hash, input_snapshot_id, status,
    counts, timestamps). The state machine is enforced by
    :meth:`transition`; the dataclass itself never allows an illegal
    transition.
    """

    id: UUID
    trade_date: date
    algorithm_key: str
    algorithm_version: str
    parameter_set_key: str
    parameter_hash: str
    input_snapshot_id: UUID
    input_row_count: int
    included_count: int
    status: CandidatePoolStatus
    created_at: datetime
    finished_at: datetime | None = None
    published_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError(f"CandidatePoolRun.id must be a UUID, got {type(self.id).__name__}")
        if not isinstance(self.input_snapshot_id, UUID):
            raise TypeError(
                "CandidatePoolRun.input_snapshot_id must be a UUID, "
                f"got {type(self.input_snapshot_id).__name__}"
            )
        if not self.algorithm_key.strip():
            raise ValueError("CandidatePoolRun.algorithm_key must not be empty")
        if not self.algorithm_version.strip():
            raise ValueError("CandidatePoolRun.algorithm_version must not be empty")
        if not self.parameter_set_key.strip():
            raise ValueError("CandidatePoolRun.parameter_set_key must not be empty")
        if not self.parameter_hash.strip():
            raise ValueError("CandidatePoolRun.parameter_hash must not be empty")
        if self.input_row_count < 0:
            raise ValueError(
                f"CandidatePoolRun.input_row_count must be >= 0, got {self.input_row_count}"
            )
        if self.included_count < 0:
            raise ValueError(
                f"CandidatePoolRun.included_count must be >= 0, got {self.included_count}"
            )
        if self.included_count > self.input_row_count:
            raise ValueError(
                "CandidatePoolRun.included_count must be <= input_row_count "
                f"({self.included_count} > {self.input_row_count})"
            )
        _require_aware_utc(self.created_at, "created_at")
        _require_aware_utc_or_none(self.finished_at, "finished_at")
        _require_aware_utc_or_none(self.published_at, "published_at")
        _require_aware_utc_or_none(self.rejected_at, "rejected_at")
        if self.status is CandidatePoolStatus.REJECTED and not self.rejection_reason:
            raise ValueError(
                "CandidatePoolRun with status=REJECTED must carry a rejection_reason"
            )
        if self.status is CandidatePoolStatus.PUBLISHED and self.published_at is None:
            raise ValueError(
                "CandidatePoolRun with status=PUBLISHED must carry a published_at"
            )

    def transition_to(
        self,
        new_status: CandidatePoolStatus,
        *,
        at: datetime | None = None,
        rejection_reason: str | None = None,
    ) -> "CandidatePoolRun":
        """Return a new :class:`CandidatePoolRun` with ``new_status``.

        The application service is responsible for supplying ``at`` (a
        timezone-aware UTC datetime) when transitioning to a terminal
        state, and for supplying ``rejection_reason`` when transitioning
        to ``REJECTED``. Without those, the post-construction invariant
        check rejects the resulting run.

        Raises ``ValueError`` if the transition is not in the legal set
        ``CALCULATED -> VALIDATED -> {PUBLISHED, REJECTED}``. Terminal
        states are irreversible.
        """
        if not self.status.can_transition_to(new_status):
            raise ValueError(
                f"illegal candidate-pool state transition: {self.status.value!r} -> "
                f"{new_status.value!r}"
            )
        changes: dict[str, object] = {"status": new_status}
        if new_status is CandidatePoolStatus.PUBLISHED:
            changes["published_at"] = at if at is not None else self.published_at
        if new_status is CandidatePoolStatus.REJECTED:
            changes["rejected_at"] = at if at is not None else self.rejected_at
            if rejection_reason is not None:
                changes["rejection_reason"] = rejection_reason
        return replace(self, **changes)


__all__ = [
    "CalculationContext",
    "CandidatePoolItem",
    "CandidatePoolPolicy",
    "CandidatePoolResult",
    "CandidatePoolRun",
    "CandidatePoolStatus",
    "CandidatePoolSummary",
    "EligibilityCriteria",
    "ExclusionReason",
    "LiquidityCriteria",
    "PriceQualityCriteria",
    "RiskCriteria",
    "RuleOutcome",
    "RuleSeverity",
    "ScoreWeights",
    "SelectionCriteria",
]


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime (UTC recommended)")


def _require_aware_utc_or_none(value: datetime | None, field_name: str) -> None:
    if value is None:
        return
    _require_aware_utc(value, field_name)


def _require_non_negative_decimal(value: Decimal, *, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal, got {value!s}")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value!s}")
