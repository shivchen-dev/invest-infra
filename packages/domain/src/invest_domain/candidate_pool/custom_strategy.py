"""Stage 4A-0 PR-04 deterministic declarative custom-strategy channel.

This module is the third formal slice of the Stage 4A-0 multi-channel
candidate-routing plan (see
``docs/plan/invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md``
particularly §5.4, §6 ``Channel C``, §7, §12). It accepts a validated
in-memory strategy definition (parsed from a YAML mapping by the
pipeline boundary) and evaluates it against the existing
:class:`invest_domain.analytics.factor_calculators.calculate_market_state_factors`
output and :func:`invest_domain.candidate_pool.universe.build_etf_universe`
hard gate. The slice ships **no** YAML adapter, **no** CLI, **no**
filesystem, database, network or arbitrary-expression execution — the
mapping parser is the only public ingestion surface.

Hard guarantees (every behaviour is unit-tested):

* Pure, deterministic function: same strategy, same instruments, same
  bars, same factor results and same ``as_of_date`` always produce the
  same :class:`CustomStrategyChannelResult` in the same order (stable
  tie-breaker on the raw :class:`UUID` bytes of the
  :class:`InstrumentId`).
* No copy of the eight factor formulas — every factor used here comes
  out of a :class:`invest_domain.analytics.factor_calculators.FactorCalculationResult`
  and the scoring routine only min/max normalises those values against
  the observed scoring set. Plan §9 forbids duplicating factor formulas
  between routing and research.
* Strict factor / operator / field allow-list: only the eight v1.0.0
  factor keys and the operators ``gt`` / ``gte`` / ``lt`` / ``lte`` /
  ``eq`` / ``in`` (plus the ``all`` / ``any`` filter combinators) are
  accepted. Unknown top-level keys, unknown filter keys, unknown
  score keys and arbitrary Python expressions are rejected eagerly by
  the mapping parser.
* The four-state ``decision`` vocabulary (``include`` / ``watch`` /
  ``exclude`` / ``no_opinion``) mirrors plan §7 so the fusion layer in
  PR-05 can consume the channel uniformly. PARTIAL candidates are
  capped at ``watch`` (plan §8); INELIGIBLE candidates always emit
  ``exclude``.
* ``strategy.enabled = False`` short-circuits the channel with
  ``no_opinion`` proposals so the operator-facing toggle is honoured
  without changing the call surface.
* Hard quality gate: missing factor values fail closed with an
  auditable ``reason`` and ``warning``. The decision is computed only
  from finite :class:`Decimal` factor values.
* Stable score ranking: scoring set is sorted by ``(-score,
  instrument_id.bytes)``. Equal scores break ties on the raw UUID
  bytes per plan §13.
* :attr:`CustomStrategyChannelResult.parameter_hash`,
  :attr:`input_hash` and :attr:`output_hash` are stable
  :func:`content_hash` digests satisfying plan §15's audit requirement
  without touching PostgreSQL.
* The channel version is pinned to
  :data:`CUSTOM_STRATEGY_CHANNEL_VERSION` so every downstream audit
  can identify this exact algorithm revision.

This module deliberately does NOT:

* Import ``yaml``, ``fastapi``, ``sqlalchemy``, ``dagster``, ``httpx``,
  any Provider SDK, or any clock / environment helper. YAML is the
  pipeline boundary's job; the domain only consumes mappings.
* Persist anything: it returns a frozen value object and is built so
  the candidate-pool persistence layer remains the single writer.
* Apply any parameter optimisation — every threshold, weight, factor
  and operator is human-supplied via the validated mapping.
* Import the V1 :class:`V1Proposal.channel_key` whitelist
  (``OFFICIAL_CHANNEL_STRATEGIES`` contains only ``fqir``). The
  custom-strategy channel ships its own
  :class:`CustomStrategyProposal` shape so V1's restriction is not
  loosened.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final
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
from invest_domain.research.factor_set import FACTOR_KEYS
from invest_domain.research.models import FACTOR_SET_KEY, FACTOR_SET_VERSION
from invest_domain.shared.canonical import content_hash

# ---------------------------------------------------------------------------
# Module-level pinned constants
# ---------------------------------------------------------------------------

#: Stable channel key consumed by the Stage 4A-0 fusion layer in PR-05.
#: Matches plan §6 ``Channel C`` so external callers and audit logs can
#: resolve the channel by name without consulting the source code.
CUSTOM_STRATEGY_CHANNEL_KEY: Final[str] = "custom_strategy"

#: Pinned channel version. Bump only when the filter / score semantics,
#: the eligibility cap, or the hash payload change in a way that should
#: be auditable. The hash of the strategy payload
#: (:attr:`CustomStrategyChannelResult.parameter_hash`) is independent
#: of this version so parameter tweaks stay traceable.
CUSTOM_STRATEGY_CHANNEL_VERSION: Final[str] = "1.0.0"

#: Custom strategy always consumes the v1.0.0 shared factor package so
#: the routing layer and the AI Evidence Pack operate on exactly the
#: same factor definitions.
CUSTOM_STRATEGY_FACTOR_SET_KEY: Final[str] = FACTOR_SET_KEY

#: Routing factor-set version — pinned to the same ``1.0.0`` as the
#: research-side :class:`invest_domain.research.models.FactorSetMetadata`.
CUSTOM_STRATEGY_FACTOR_SET_VERSION: Final[str] = FACTOR_SET_VERSION

#: Frozen tuple of factor keys the channel will accept. Exposed as a
#: module constant so the parser can reject any unknown factor without
#: having to re-import the research package on every call.
ALLOWED_FACTOR_KEYS: Final[tuple[str, ...]] = FACTOR_KEYS

#: Frozen tuple of comparison operators the channel will accept. The
#: list mirrors the plan §12 allow-list and intentionally excludes any
#: form of expression / arithmetic / function call.
ALLOWED_OPERATORS: Final[tuple[str, ...]] = (
    "gt",
    "gte",
    "lt",
    "lte",
    "eq",
    "in",
)

#: Frozen tuple of score directions the channel will accept. The list
#: mirrors the plan §12 allow-list (``higher`` / ``lower``).
ALLOWED_DIRECTIONS: Final[tuple[str, ...]] = (
    "higher",
    "lower",
)

#: Quantisation quantum for every channel Decimal output. Matches the
#: v1.0.0 factor calculator quantum so bytewise rounding rules cannot
#: diverge between channels.
_QUANTUM: Final[Decimal] = Decimal("0.00000001")

#: Decimal ``0`` / ``1`` literals kept as module constants so every
#: ``__post_init__`` / scoring branch uses the same Decimal context.
_ZERO: Final[Decimal] = Decimal("0")
_ONE: Final[Decimal] = Decimal("1")
_FIFTY: Final[Decimal] = Decimal("0.5")

#: Allowed top-level keys of a custom-strategy mapping. The parser
#: raises on any key outside this set so YAML schema drift cannot
#: silently widen the channel's surface area.
_ALLOWED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"strategy_key", "version", "enabled", "universe", "filters", "score", "output"}
)

#: Allowed keys of the ``filters`` block.
_ALLOWED_FILTERS_KEYS: Final[frozenset[str]] = frozenset({"all", "any"})

#: Allowed keys of a filter rule.
_ALLOWED_RULE_KEYS: Final[frozenset[str]] = frozenset({"factor", "op", "value"})

#: Allowed keys of a score factor.
_ALLOWED_SCORE_KEYS: Final[frozenset[str]] = frozenset({"factor", "weight", "direction"})

#: Allowed keys of the ``output`` block.
_ALLOWED_OUTPUT_KEYS: Final[frozenset[str]] = frozenset({"include_top_n", "watch_next_n"})

#: Allowed keys of the ``universe`` block.
_ALLOWED_UNIVERSE_KEYS: Final[frozenset[str]] = frozenset({"minimum_history_days"})


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CustomStrategyDecision(StrEnum):
    """Four-state ``decision`` vocabulary mirroring plan §7."""

    INCLUDE = "include"
    WATCH = "watch"
    EXCLUDE = "exclude"
    NO_OPINION = "no_opinion"


# ---------------------------------------------------------------------------
# Exceptions raised by this module
# ---------------------------------------------------------------------------


class CustomStrategyError(ValueError):
    """Base class for every custom-strategy channel configuration failure.

    Inherits from :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still treats channel failures as
    validation-time errors. Subclasses tag the failure so callers can
    react programmatically without parsing free text.
    """


class InvalidCustomStrategyError(CustomStrategyError):
    """Raised when a strategy mapping fails any of the validation rules."""


class CustomStrategyResultInvariantError(CustomStrategyError):
    """Raised when the post-init invariants of the result / proposal are broken."""


# ---------------------------------------------------------------------------
# Strategy value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CustomStrategyFilterRule:
    """A single ``all`` / ``any`` filter rule.

    The field set is the *minimum* the channel needs to evaluate a
    filter: the factor key, the operator and the comparison value. The
    operator drives both the comparison semantics and the type the
    value must carry (``in`` requires a tuple; the others require a
    finite :class:`Decimal`).
    """

    factor: str
    op: str
    value: Decimal | tuple[Decimal, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.factor, str) or not self.factor.strip():
            raise InvalidCustomStrategyError(
                "CustomStrategyFilterRule.factor must be a non-empty string"
            )
        if self.factor not in ALLOWED_FACTOR_KEYS:
            raise InvalidCustomStrategyError(
                f"CustomStrategyFilterRule.factor={self.factor!r} is not in the "
                f"allow-list {sorted(ALLOWED_FACTOR_KEYS)}"
            )
        if not isinstance(self.op, str) or self.op not in ALLOWED_OPERATORS:
            raise InvalidCustomStrategyError(
                f"CustomStrategyFilterRule.op={self.op!r} is not in the "
                f"allow-list {sorted(ALLOWED_OPERATORS)}"
            )
        if self.op == "in":
            if not isinstance(self.value, tuple) or not self.value:
                raise InvalidCustomStrategyError(
                    "CustomStrategyFilterRule.value must be a non-empty tuple of "
                    "finite Decimals when op='in'"
                )
            for index, item in enumerate(self.value):
                _require_finite_decimal(
                    item,
                    f"CustomStrategyFilterRule.value[{index}]",
                )
        else:
            _require_finite_decimal(
                self.value,
                "CustomStrategyFilterRule.value",
            )


@dataclass(frozen=True, slots=True)
class CustomStrategyScoreFactor:
    """A single score factor with weight and direction.

    Weights are normalised across the score list at the
    :class:`CustomStrategy` level so this dataclass only carries the
    raw value supplied by the operator.
    """

    factor: str
    weight: Decimal
    direction: str

    def __post_init__(self) -> None:
        if not isinstance(self.factor, str) or not self.factor.strip():
            raise InvalidCustomStrategyError(
                "CustomStrategyScoreFactor.factor must be a non-empty string"
            )
        if self.factor not in ALLOWED_FACTOR_KEYS:
            raise InvalidCustomStrategyError(
                f"CustomStrategyScoreFactor.factor={self.factor!r} is not in the "
                f"allow-list {sorted(ALLOWED_FACTOR_KEYS)}"
            )
        _require_finite_decimal(self.weight, "CustomStrategyScoreFactor.weight")
        if self.weight <= _ZERO:
            raise InvalidCustomStrategyError(
                "CustomStrategyScoreFactor.weight must be > 0, "
                f"got {self.weight!s}"
            )
        if not isinstance(self.direction, str) or self.direction not in ALLOWED_DIRECTIONS:
            raise InvalidCustomStrategyError(
                f"CustomStrategyScoreFactor.direction={self.direction!r} is not "
                f"in the allow-list {sorted(ALLOWED_DIRECTIONS)}"
            )


@dataclass(frozen=True, slots=True)
class CustomStrategyUniverse:
    """The universe block of a custom strategy.

    The single supported knob is ``minimum_history_days``: the channel
    forwards it to :func:`invest_domain.candidate_pool.universe.build_etf_universe`
    so the hard ``FULL`` / ``PARTIAL`` thresholds can be re-used
    verbatim. PARTIAL → watch-only behaviour is unchanged and is
    implemented in the evaluator.
    """

    minimum_history_days: int

    def __post_init__(self) -> None:
        if not isinstance(self.minimum_history_days, int) or isinstance(
            self.minimum_history_days, bool
        ):
            raise InvalidCustomStrategyError(
                "CustomStrategyUniverse.minimum_history_days must be an int, "
                f"got {type(self.minimum_history_days).__name__}"
            )
        if self.minimum_history_days < 1:
            raise InvalidCustomStrategyError(
                "CustomStrategyUniverse.minimum_history_days must be >= 1, "
                f"got {self.minimum_history_days}"
            )


@dataclass(frozen=True, slots=True)
class CustomStrategyOutput:
    """The output block of a custom strategy.

    Both ``include_top_n`` and ``watch_next_n`` are positive ints; the
    former is the count of proposals that may land in ``include`` (per
    plan §12) and the latter is the count of proposals that may land
    in ``watch`` (taken from the *remaining* scoring set after the
    include list is consumed).
    """

    include_top_n: int
    watch_next_n: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("include_top_n", self.include_top_n),
            ("watch_next_n", self.watch_next_n),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidCustomStrategyError(
                    f"CustomStrategyOutput.{field_name} must be an int, "
                    f"got {type(value).__name__}"
                )
            if value < 0:
                raise InvalidCustomStrategyError(
                    f"CustomStrategyOutput.{field_name} must be >= 0, "
                    f"got {value}"
                )


@dataclass(frozen=True, slots=True)
class CustomStrategy:
    """A validated, versioned custom-strategy definition.

    The dataclass is the canonical post-parse shape consumed by
    :func:`evaluate_custom_strategy_channel`. Construction happens
    exclusively through :func:`parse_custom_strategy_mapping` so
    :attr:`parameter_hash` is always coherent with the payload.
    """

    strategy_key: str
    version: str
    enabled: bool
    universe: CustomStrategyUniverse
    filters_all: tuple[CustomStrategyFilterRule, ...]
    filters_any: tuple[CustomStrategyFilterRule, ...]
    score: tuple[CustomStrategyScoreFactor, ...]
    output: CustomStrategyOutput
    parameter_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_key, str) or not self.strategy_key.strip():
            raise InvalidCustomStrategyError(
                "CustomStrategy.strategy_key must be a non-empty string"
            )
        if not isinstance(self.version, str) or not _SEMVER_PATTERN.fullmatch(self.version):
            raise InvalidCustomStrategyError(
                "CustomStrategy.version must be a semver MAJOR.MINOR.PATCH string, "
                f"got {self.version!r}"
            )
        if not isinstance(self.enabled, bool):
            raise InvalidCustomStrategyError(
                "CustomStrategy.enabled must be a bool, "
                f"got {type(self.enabled).__name__}"
            )
        if not isinstance(self.universe, CustomStrategyUniverse):
            raise InvalidCustomStrategyError(
                "CustomStrategy.universe must be a CustomStrategyUniverse, "
                f"got {type(self.universe).__name__}"
            )
        if not isinstance(self.filters_all, tuple):
            raise InvalidCustomStrategyError(
                "CustomStrategy.filters_all must be a tuple[CustomStrategyFilterRule, ...]"
            )
        for index, rule in enumerate(self.filters_all):
            if not isinstance(rule, CustomStrategyFilterRule):
                raise InvalidCustomStrategyError(
                    f"CustomStrategy.filters_all[{index}] must be a "
                    f"CustomStrategyFilterRule, got {type(rule).__name__}"
                )
        if not isinstance(self.filters_any, tuple):
            raise InvalidCustomStrategyError(
                "CustomStrategy.filters_any must be a tuple[CustomStrategyFilterRule, ...]"
            )
        for index, rule in enumerate(self.filters_any):
            if not isinstance(rule, CustomStrategyFilterRule):
                raise InvalidCustomStrategyError(
                    f"CustomStrategy.filters_any[{index}] must be a "
                    f"CustomStrategyFilterRule, got {type(rule).__name__}"
                )
        if not isinstance(self.score, tuple) or not self.score:
            raise InvalidCustomStrategyError(
                "CustomStrategy.score must be a non-empty tuple of "
                "CustomStrategyScoreFactor entries"
            )
        score_factors = [item.factor for item in self.score]
        if len(set(score_factors)) != len(score_factors):
            raise InvalidCustomStrategyError(
                f"CustomStrategy.score must not list the same factor twice; "
                f"got {score_factors!r}"
            )
        if not isinstance(self.output, CustomStrategyOutput):
            raise InvalidCustomStrategyError(
                "CustomStrategy.output must be a CustomStrategyOutput, "
                f"got {type(self.output).__name__}"
            )
        total_weight = sum((item.weight for item in self.score), _ZERO)
        if total_weight != _ONE:
            raise InvalidCustomStrategyError(
                "CustomStrategy.score weights must sum to exactly 1, "
                f"got {total_weight!s}"
            )
        computed = self.compute_parameter_hash()
        if not self.parameter_hash:
            object.__setattr__(self, "parameter_hash", computed)
        elif self.parameter_hash != computed:
            raise InvalidCustomStrategyError(
                "CustomStrategy.parameter_hash does not match the deterministic "
                "hash of the strategy payload"
            )

    def compute_parameter_hash(self) -> str:
        """Return the canonical SHA-256 digest of the strategy payload.

        The hash is independent of any run-time factory and is derived
        only from the substantive strategy parameters so two strategies
        with the same numbers produce the same digest regardless of
        factory order.
        """

        payload = {
            "channel_key": CUSTOM_STRATEGY_CHANNEL_KEY,
            "channel_version": CUSTOM_STRATEGY_CHANNEL_VERSION,
            "enabled": self.enabled,
            "filters_all": [
                {
                    "factor": rule.factor,
                    "op": rule.op,
                    "value": _serialise_filter_value(rule.value),
                }
                for rule in self.filters_all
            ],
            "filters_any": [
                {
                    "factor": rule.factor,
                    "op": rule.op,
                    "value": _serialise_filter_value(rule.value),
                }
                for rule in self.filters_any
            ],
            "output": {
                "include_top_n": self.output.include_top_n,
                "watch_next_n": self.output.watch_next_n,
            },
            "score": [
                {
                    "direction": item.direction,
                    "factor": item.factor,
                    "weight": item.weight,
                }
                for item in self.score
            ],
            "strategy_key": self.strategy_key,
            "universe": {"minimum_history_days": self.universe.minimum_history_days},
            "version": self.version,
        }
        return content_hash(payload)


# ---------------------------------------------------------------------------
# Proposal / result value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CustomStrategyProposal:
    """One custom-strategy ``Candidate Proposal`` (plan §7).

    The shape is intentionally close to the institutional channel's
    proposal but narrower: the custom-strategy channel has no external
    authority weight, no publication timestamps, and no external
    evidence refs, so the proposal keeps only the auditable scoring
    decision, the per-factor normalised values that drove the score,
    the channel + strategy identity and the reason / warning trail.
    """

    instrument_id: InstrumentId
    symbol: str
    exchange: str
    channel_key: str
    channel_version: str
    strategy_key: str
    strategy_version: str
    decision: str
    normalized_score: Decimal | None
    eligibility: str
    observed_factor_values: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    normalized_factor_values: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    reasons: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.instrument_id must be an InstrumentId, "
                f"got {type(self.instrument_id).__name__}"
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.symbol must be a non-empty string"
            )
        if not isinstance(self.exchange, str) or not self.exchange.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.exchange must be a non-empty string"
            )
        if self.channel_key != CUSTOM_STRATEGY_CHANNEL_KEY:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.channel_key must equal "
                f"{CUSTOM_STRATEGY_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != CUSTOM_STRATEGY_CHANNEL_VERSION:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.channel_version must equal "
                f"{CUSTOM_STRATEGY_CHANNEL_VERSION!r}, "
                f"got {self.channel_version!r}"
            )
        if not isinstance(self.strategy_key, str) or not self.strategy_key.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.strategy_key must be a non-empty string"
            )
        if not isinstance(self.strategy_version, str) or not self.strategy_version.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.strategy_version must be a non-empty string"
            )
        if self.decision not in {item.value for item in CustomStrategyDecision}:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.decision must be one of "
                "include/watch/exclude/no_opinion, got " + repr(self.decision)
            )
        if self.normalized_score is not None:
            _require_finite_decimal(
                self.normalized_score,
                "CustomStrategyProposal.normalized_score",
            )
            if self.normalized_score < _ZERO or self.normalized_score > _ONE:
                raise CustomStrategyResultInvariantError(
                    "CustomStrategyProposal.normalized_score must lie within [0, 1], "
                    f"got {self.normalized_score!s}"
                )
        if self.eligibility not in {item.value for item in UniverseEligibility}:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyProposal.eligibility must be one of "
                f"{[item.value for item in UniverseEligibility]!r}, "
                f"got {self.eligibility!r}"
            )
        for label, mapping in (
            ("observed_factor_values", self.observed_factor_values),
            ("normalized_factor_values", self.normalized_factor_values),
        ):
            if not isinstance(mapping, Mapping):
                raise CustomStrategyResultInvariantError(
                    f"CustomStrategyProposal.{label} must be a Mapping, "
                    f"got {type(mapping).__name__}"
                )
            for key, value in mapping.items():
                if not isinstance(key, str) or not key.strip():
                    raise CustomStrategyResultInvariantError(
                        f"CustomStrategyProposal.{label} keys must be non-empty strings"
                    )
                if key not in ALLOWED_FACTOR_KEYS:
                    raise CustomStrategyResultInvariantError(
                        f"CustomStrategyProposal.{label} key {key!r} is not in "
                        f"the allow-list {sorted(ALLOWED_FACTOR_KEYS)}"
                    )
                _require_finite_decimal(value, f"CustomStrategyProposal.{label}[{key!r}]")
        for key, value in self.normalized_factor_values.items():
            if value < _ZERO or value > _ONE:
                raise CustomStrategyResultInvariantError(
                    f"CustomStrategyProposal.normalized_factor_values[{key!r}] "
                    f"must lie within [0, 1], got {value!s}"
                )
        for label in ("reasons", "exclusion_reasons", "warnings"):
            value = getattr(self, label)
            if not isinstance(value, tuple):
                raise CustomStrategyResultInvariantError(
                    f"CustomStrategyProposal.{label} must be a tuple[str, ...]"
                )
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise CustomStrategyResultInvariantError(
                        f"CustomStrategyProposal.{label} must contain non-empty strings"
                    )


@dataclass(frozen=True, slots=True)
class CustomStrategyChannelResult:
    """The frozen output of :func:`evaluate_custom_strategy_channel`.

    Carries the audit block (``channel_key`` / ``channel_version`` /
    ``strategy_key`` / ``strategy_version`` / ``as_of_date`` /
    ``parameter_hash`` / ``input_hash`` / ``output_hash``) plus the
    stable, sorted proposals and the structured warnings emitted
    during the run. The proposal order is
    ``(decision_rank, -normalized_score, instrument_id.value.bytes)``
    so two runs on the same logical input always emit byte-identical
    ordering (plan §13 ``稳定排序``).
    """

    channel_key: str
    channel_version: str
    strategy_key: str
    strategy_version: str
    as_of_date: date
    parameter_hash: str
    input_hash: str
    output_hash: str
    proposals: tuple[CustomStrategyProposal, ...]
    warnings: tuple[str, ...] = ()
    full_count: int = 0
    partial_count: int = 0
    ineligible_count: int = 0
    include_count: int = 0
    watch_count: int = 0
    exclude_count: int = 0
    no_opinion_count: int = 0

    def __post_init__(self) -> None:
        if self.channel_key != CUSTOM_STRATEGY_CHANNEL_KEY:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.channel_key must equal "
                f"{CUSTOM_STRATEGY_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != CUSTOM_STRATEGY_CHANNEL_VERSION:
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.channel_version must equal "
                f"{CUSTOM_STRATEGY_CHANNEL_VERSION!r}, "
                f"got {self.channel_version!r}"
            )
        if not isinstance(self.strategy_key, str) or not self.strategy_key.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.strategy_key must be a non-empty string"
            )
        if not isinstance(self.strategy_version, str) or not self.strategy_version.strip():
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.strategy_version must be a non-empty string"
            )
        if not isinstance(self.as_of_date, date):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )
        for field_name in ("parameter_hash", "input_hash", "output_hash"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) != 64:
                raise CustomStrategyResultInvariantError(
                    f"CustomStrategyChannelResult.{field_name} must be a "
                    f"64-character hex digest, got {value!r}"
                )
        if not isinstance(self.proposals, tuple):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.proposals must be a "
                "tuple[CustomStrategyProposal, ...]"
            )
        seen: set[UUID] = set()
        for proposal in self.proposals:
            if proposal.instrument_id.value in seen:
                raise CustomStrategyResultInvariantError(
                    "CustomStrategyChannelResult.proposals contain duplicate "
                    f"instrument_id {proposal.instrument_id}"
                )
            seen.add(proposal.instrument_id.value)
        if not isinstance(self.warnings, tuple):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult.warnings must be a tuple[str, ...]"
            )
        for item in self.warnings:
            if not isinstance(item, str) or not item.strip():
                raise CustomStrategyResultInvariantError(
                    "CustomStrategyChannelResult.warnings must contain non-empty strings"
                )
        for field_name in (
            "full_count",
            "partial_count",
            "ineligible_count",
            "include_count",
            "watch_count",
            "exclude_count",
            "no_opinion_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise CustomStrategyResultInvariantError(
                    f"CustomStrategyChannelResult.{field_name} must be a "
                    f"non-negative int, got {value!r}"
                )
        if self.full_count + self.partial_count + self.ineligible_count != len(
            self.proposals
        ):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult counts must sum to "
                f"len(proposals) ({self.full_count} + {self.partial_count} + "
                f"{self.ineligible_count} != {len(self.proposals)})"
            )
        decision_count = (
            self.include_count
            + self.watch_count
            + self.exclude_count
            + self.no_opinion_count
        )
        if decision_count != len(self.proposals):
            raise CustomStrategyResultInvariantError(
                "CustomStrategyChannelResult decision counters must sum to "
                f"len(proposals) ({self.include_count} + {self.watch_count} + "
                f"{self.exclude_count} + {self.no_opinion_count} = {decision_count} "
                f"vs len(proposals)={len(self.proposals)})"
            )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def parse_custom_strategy_mapping(mapping: Mapping[str, object]) -> CustomStrategy:
    """Parse and validate a custom-strategy mapping into a :class:`CustomStrategy`.

    The mapping is the post-``yaml.safe_load`` view: scalars, lists and
    nested mappings. The function accepts arbitrary ``Mapping`` inputs
    so callers (including the pipeline YAML loader and unit tests) can
    exercise the parser directly without touching the filesystem.

    The function is deliberately strict: every allowed key is consumed
    verbatim, every disallowed key raises an
    :class:`InvalidCustomStrategyError`, every scalar is checked
    against the plan §12 / §5.4 allow-list and every nested list is
    type-checked at construction. The resulting
    :attr:`CustomStrategy.parameter_hash` is deterministic, so the
    audit block of the channel result stays stable for the same
    logical strategy content regardless of how the mapping was
    constructed.
    """

    if not isinstance(mapping, Mapping):
        raise InvalidCustomStrategyError(
            "custom strategy root must be a mapping, "
            f"got {type(mapping).__name__}"
        )
    unknown = set(mapping.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise InvalidCustomStrategyError(
            f"custom strategy root has unknown top-level keys: "
            f"{sorted(unknown)!r}; allowed: {sorted(_ALLOWED_TOP_LEVEL_KEYS)}"
        )

    strategy_key = _parse_strategy_key(mapping.get("strategy_key"))
    version = _parse_version(mapping.get("version"))
    enabled = _parse_enabled(mapping.get("enabled", True))
    universe = _parse_universe(mapping.get("universe"))
    filters_block, filters_all, filters_any = _parse_filters(mapping.get("filters"))
    score = _parse_score(mapping.get("score"))
    output = _parse_output(mapping.get("output"))

    return CustomStrategy(
        strategy_key=strategy_key,
        version=version,
        enabled=enabled,
        universe=universe,
        filters_all=filters_all,
        filters_any=filters_any,
        score=score,
        output=output,
    )


def evaluate_custom_strategy_channel(
    *,
    strategy: CustomStrategy,
    instruments: Sequence[Instrument],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    factors_by_instrument: Mapping[InstrumentId, FactorCalculationResult],
    as_of_date: date,
) -> CustomStrategyChannelResult:
    """Run the deterministic custom-strategy channel for ``as_of_date``.

    The function:

    1. Classifies every input instrument into ``FULL`` / ``PARTIAL`` /
       ``INELIGIBLE`` via :func:`invest_domain.candidate_pool.universe.build_etf_universe`
       with ``strategy.universe.minimum_history_days``. The classifier
       deduplicates by ``instrument_id`` and orders its output by
       ``str(instrument_id)``; the channel reuses that ordering.
    2. Pulls each :class:`FactorCalculationResult` from
       ``factors_by_instrument``. Instruments missing from the mapping
       fall back to a single
       :func:`invest_domain.analytics.factor_calculators.calculate_market_state_factors`
       call so the channel stays self-contained when callers pass
       partial inputs. The fallback never overrides a pre-computed
       result.
    3. Applies the hard quality gate (plan §10.1 / §12): every
       ``filters.all`` rule must pass; at least one ``filters.any`` rule
       must pass when ``filters.any`` is non-empty. Every rule is
       evaluated against the
       :attr:`invest_domain.research.models.FactorObservation.value` of
       the relevant factor; missing or non-finite values fail closed
       with an auditable reason and a per-rule warning.
    4. For surviving candidates, normalises each score factor by its
       direction (min/max within the scoring set) and composes the
       weighted score. The resulting ``normalized_score`` is in
       ``[0, 1]`` so the fusion layer can scale it without
       re-deriving the per-factor normalisation.
    5. Sorts the scoring set by ``(-normalized_score,
       instrument_id.value.bytes)`` and applies the stable
       ``include_top_n`` + ``watch_next_n`` selection. PARTIAL
       candidates are capped at ``watch`` even when their score
       qualifies for ``include``; INELIGIBLE candidates are always
       ``exclude`` regardless of score.
    6. When ``strategy.enabled`` is ``False``, short-circuits with
       ``no_opinion`` proposals for every input instrument so the
       operator-facing toggle is honoured without changing the call
       surface or breaking downstream contracts.
    7. Computes a deterministic :attr:`parameter_hash` /
       :attr:`input_hash` / :attr:`output_hash` over the
       :class:`CustomStrategy`, the universe fingerprint and the
       proposals so the audit layer (PR-05) can persist the run row
       without consulting the channel module.

    Parameters
    ----------
    strategy:
        The validated strategy definition. Construction is exclusive
        to :func:`parse_custom_strategy_mapping` so the contract is
        never violated.
    instruments:
        ETF instruments to evaluate. The function does not mutate
        this sequence.
    bars_by_instrument:
        Mapping from :class:`InstrumentId` to its bar series. Used by
        ``build_etf_universe`` and as a fallback for the factor
        calculator. The function never mutates this mapping.
    factors_by_instrument:
        Mapping from :class:`InstrumentId` to its pre-computed
        :class:`FactorCalculationResult`. Missing entries fall back to
        a single ``calculate_market_state_factors`` call. The
        function never mutates this mapping.
    as_of_date:
        Trading day the channel run describes. Echoed back on the
        result and used by ``build_etf_universe`` and the fallback
        factor calculator.

    Returns
    -------
    CustomStrategyChannelResult
        Frozen value object with one :class:`CustomStrategyProposal`
        per input instrument (deduplicated by ``instrument_id``),
        plus the audit block, the universe-classification counts and
        the decision counters.

    Raises
    ------
    TypeError
        ``as_of_date`` is not a date, ``instruments`` / ``bars_by_instrument``
        / ``factors_by_instrument`` are not the documented container
        types, the ``bars_by_instrument`` values are not
        :class:`DailyBar` instances, or the ``factors_by_instrument``
        values are not :class:`FactorCalculationResult` instances.
    """
    if not isinstance(as_of_date, date):
        raise TypeError(
            "evaluate_custom_strategy_channel as_of_date must be a date, "
            f"got {type(as_of_date).__name__}"
        )
    if not isinstance(strategy, CustomStrategy):
        raise TypeError(
            "evaluate_custom_strategy_channel strategy must be a CustomStrategy, "
            f"got {type(strategy).__name__}"
        )
    if not all(isinstance(item, Instrument) for item in instruments):
        raise TypeError(
            "evaluate_custom_strategy_channel instruments must be a "
            f"Sequence[Instrument], got an item of type "
            f"{type(next(iter(instruments), None)).__name__}"
        )
    for instrument_id, bars in bars_by_instrument.items():
        if not isinstance(instrument_id, InstrumentId):
            raise TypeError(
                "evaluate_custom_strategy_channel bars_by_instrument keys must "
                f"be InstrumentId instances, got {type(instrument_id).__name__}"
            )
        if not isinstance(bars, (list, tuple)):
            raise TypeError(
                "evaluate_custom_strategy_channel bars_by_instrument values must "
                f"be a Sequence[DailyBar], got {type(bars).__name__}"
            )
        for bar in bars:
            if not isinstance(bar, DailyBar):
                raise TypeError(
                    "evaluate_custom_strategy_channel bars_by_instrument values "
                    f"must contain DailyBar instances, got {type(bar).__name__}"
                )
    for instrument_id, factors in factors_by_instrument.items():
        if not isinstance(instrument_id, InstrumentId):
            raise TypeError(
                "evaluate_custom_strategy_channel factors_by_instrument keys "
                f"must be InstrumentId instances, got {type(instrument_id).__name__}"
            )
        if not isinstance(factors, FactorCalculationResult):
            raise TypeError(
                "evaluate_custom_strategy_channel factors_by_instrument values "
                "must be FactorCalculationResult instances, got "
                f"{type(factors).__name__}"
            )

    if not strategy.enabled:
        return _build_disabled_result(
            strategy=strategy,
            instruments=instruments,
            bars_by_instrument=bars_by_instrument,
            as_of_date=as_of_date,
        )

    universe = build_etf_universe(
        instruments,
        bars_by_instrument,
        as_of_date,
        minimum_full_history_days=strategy.universe.minimum_history_days,
        minimum_partial_history_days=min(
            strategy.universe.minimum_history_days, 20
        ),
    )
    instrument_by_id: dict[InstrumentId, Instrument] = {
        instrument.instrument_id: instrument
        for instrument in instruments
        if instrument.instrument_id is not None
    }

    proposals: list[CustomStrategyProposal] = []
    warnings: list[str] = []
    full_count = 0
    partial_count = 0
    ineligible_count = 0
    include_count = 0
    watch_count = 0
    exclude_count = 0

    filtered_candidates: list[_ScoredCandidate] = []
    excluded_candidates: list[CustomStrategyProposal] = []
    for candidate in universe:
        instrument_id = candidate.instrument_id
        if candidate.eligibility is UniverseEligibility.FULL:
            full_count += 1
        elif candidate.eligibility is UniverseEligibility.PARTIAL:
            partial_count += 1
        else:
            ineligible_count += 1
            excluded_candidates.append(
                _build_ineligible_proposal(strategy, candidate)
            )
            exclude_count += 1
            continue

        calculation = _resolve_factors(
            instrument_id, factors_by_instrument, bars_by_instrument, as_of_date
        )
        factor_values = {
            observation.factor_key: observation.value
            for observation in calculation.factors
        }

        filter_outcome = _evaluate_filters(strategy, factor_values)
        if not filter_outcome.passed:
            proposal = _build_filtered_proposal(
                strategy=strategy,
                candidate=candidate,
                factor_values=factor_values,
                filter_outcome=filter_outcome,
            )
            excluded_candidates.append(proposal)
            exclude_count += 1
            warnings.extend(filter_outcome.warnings)
            continue

        scored = _score_candidate(strategy, factor_values)
        if scored is None:
            proposal = _build_filtered_proposal(
                strategy=strategy,
                candidate=candidate,
                factor_values=factor_values,
                filter_outcome=_FilterOutcome(
                    passed=False,
                    reasons=("custom_strategy.missing_score_factor",),
                    warnings=("custom_strategy.missing_score_factor",),
                ),
            )
            excluded_candidates.append(proposal)
            exclude_count += 1
            warnings.append(
                f"custom_strategy.missing_score_factor:{instrument_id}"
            )
            continue

        filtered_candidates.append(
            _ScoredCandidate(
                candidate=candidate,
                instrument=instrument_by_id.get(instrument_id),
                observed_values=scored.observed_values,
                normalized_values=scored.normalized_values,
                normalized_score=scored.normalized_score,
            )
        )

    # min/max normalisation is computed against the *scoring set* so the
    # relative ranking is meaningful even when factor values span orders
    # of magnitude.
    scoring_min_max = _compute_min_max(filtered_candidates)
    scored_entries: list[_ScoredCandidate] = []
    for entry in filtered_candidates:
        normalised = _min_max_normalise(entry.observed_values, scoring_min_max)
        score = _compose_score(strategy, normalised)
        scored_entries.append(
            replace(
                entry,
                normalized_values=normalised,
                normalized_score=score,
            )
        )

    filtered_candidates = scored_entries
    filtered_candidates.sort(key=_scored_sort_key)

    include_top_n = strategy.output.include_top_n
    watch_next_n = strategy.output.watch_next_n

    for index, entry in enumerate(filtered_candidates):
        decision, _ = _decide(
            candidate=entry.candidate,
            index=index,
            include_top_n=include_top_n,
            watch_next_n=watch_next_n,
        )
        proposal = _build_scored_proposal(strategy=strategy, entry=entry, decision=decision)
        proposals.append(proposal)
        if decision == CustomStrategyDecision.INCLUDE.value:
            include_count += 1
        elif decision == CustomStrategyDecision.WATCH.value:
            watch_count += 1
        else:
            exclude_count += 1

    # Preserve stable ordering: include then watch within each slice,
    # then the filtered-out candidates, then the ineligible ones.
    proposals.extend(excluded_candidates)
    proposals.sort(key=_result_proposal_sort_key)

    # Sanity: every UniverseCandidate produced exactly one proposal.
    expected_ids = {candidate.instrument_id for candidate in universe}
    actual_ids = {proposal.instrument_id for proposal in proposals}
    if expected_ids != actual_ids:
        raise CustomStrategyResultInvariantError(
            "evaluate_custom_strategy_channel produced a proposal set whose "
            f"instrument_ids differ from the universe; expected={sorted(expected_ids, key=str)!r} "
            f"got={sorted(actual_ids, key=str)!r}"
        )

    parameter_hash = strategy.parameter_hash
    input_hash = _compute_input_hash(
        strategy=strategy,
        as_of_date=as_of_date,
        universe=universe,
    )
    output_hash = _compute_output_hash(proposals, warnings)

    return CustomStrategyChannelResult(
        channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
        channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.version,
        as_of_date=as_of_date,
        parameter_hash=parameter_hash,
        input_hash=input_hash,
        output_hash=output_hash,
        proposals=tuple(proposals),
        warnings=tuple(_dedupe_preserve_order(warnings)),
        full_count=full_count,
        partial_count=partial_count,
        ineligible_count=ineligible_count,
        include_count=include_count,
        watch_count=watch_count,
        exclude_count=exclude_count,
        no_opinion_count=0,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_SEMVER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
_STRATEGY_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class _FilterOutcome:
    passed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    candidate: UniverseCandidate
    instrument: Instrument | None
    observed_values: dict[str, Decimal]
    normalized_values: dict[str, Decimal]
    normalized_score: Decimal


def _parse_strategy_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidCustomStrategyError(
            "strategy_key must be a non-empty string, "
            f"got {type(value).__name__}: {value!r}"
        )
    if not _STRATEGY_KEY_PATTERN.fullmatch(value):
        raise InvalidCustomStrategyError(
            "strategy_key must match [A-Za-z][A-Za-z0-9_]*, "
            f"got {value!r}"
        )
    return value


def _parse_version(value: object) -> str:
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise InvalidCustomStrategyError(
            "version must be a semver MAJOR.MINOR.PATCH string, "
            f"got {type(value).__name__}: {value!r}"
        )
    return value


def _parse_enabled(value: object) -> bool:
    if not isinstance(value, bool):
        raise InvalidCustomStrategyError(
            "enabled must be a bool, "
            f"got {type(value).__name__}: {value!r}"
        )
    return value


def _parse_universe(value: object) -> CustomStrategyUniverse:
    if value is None:
        return CustomStrategyUniverse(minimum_history_days=60)
    if not isinstance(value, Mapping):
        raise InvalidCustomStrategyError(
            "universe must be a mapping with key 'minimum_history_days', "
            f"got {type(value).__name__}"
        )
    unknown = set(value.keys()) - _ALLOWED_UNIVERSE_KEYS
    if unknown:
        raise InvalidCustomStrategyError(
            f"universe has unknown keys: {sorted(unknown)!r}; allowed: "
            f"{sorted(_ALLOWED_UNIVERSE_KEYS)}"
        )
    if "minimum_history_days" not in value:
        raise InvalidCustomStrategyError(
            "universe.minimum_history_days is required"
        )
    return CustomStrategyUniverse(minimum_history_days=int(value["minimum_history_days"]))


def _parse_filters(
    value: object,
) -> tuple[
    Mapping[str, object],
    tuple[CustomStrategyFilterRule, ...],
    tuple[CustomStrategyFilterRule, ...],
]:
    if value is None:
        return (MappingProxyType({}), (), ())
    if not isinstance(value, Mapping):
        raise InvalidCustomStrategyError(
            "filters must be a mapping with keys 'all' / 'any', "
            f"got {type(value).__name__}"
        )
    unknown = set(value.keys()) - _ALLOWED_FILTERS_KEYS
    if unknown:
        raise InvalidCustomStrategyError(
            f"filters has unknown keys: {sorted(unknown)!r}; allowed: "
            f"{sorted(_ALLOWED_FILTERS_KEYS)}"
        )
    all_rules = _parse_filter_rules(value.get("all"), "all")
    any_rules = _parse_filter_rules(value.get("any"), "any")
    return (MappingProxyType(dict(value)), all_rules, any_rules)


def _parse_filter_rules(
    value: object,
    section: str,
) -> tuple[CustomStrategyFilterRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise InvalidCustomStrategyError(
            f"filters.{section} must be a list of rule mappings, "
            f"got {type(value).__name__}"
        )
    rules: list[CustomStrategyFilterRule] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise InvalidCustomStrategyError(
                f"filters.{section}[{index}] must be a mapping, "
                f"got {type(raw).__name__}"
            )
        unknown = set(raw.keys()) - _ALLOWED_RULE_KEYS
        if unknown:
            raise InvalidCustomStrategyError(
                f"filters.{section}[{index}] has unknown keys: {sorted(unknown)!r}; "
                f"allowed: {sorted(_ALLOWED_RULE_KEYS)}"
            )
        for required in ("factor", "op", "value"):
            if required not in raw:
                raise InvalidCustomStrategyError(
                    f"filters.{section}[{index}] is missing required key {required!r}"
                )
        factor = raw["factor"]
        op = raw["op"]
        raw_value = raw["value"]
        if op == "in":
            if not isinstance(raw_value, list) or not raw_value:
                raise InvalidCustomStrategyError(
                    f"filters.{section}[{index}].value must be a non-empty list "
                    f"when op='in', got {type(raw_value).__name__}"
                )
            try:
                value_tuple: Decimal | tuple[Decimal, ...] = tuple(
                    Decimal(str(item)) for item in raw_value
                )
            except (ArithmeticError, ValueError, TypeError) as exc:
                raise InvalidCustomStrategyError(
                    f"filters.{section}[{index}].value contains a non-finite Decimal: "
                    f"{raw_value!r} ({exc})"
                ) from exc
        else:
            if isinstance(raw_value, bool):
                raise InvalidCustomStrategyError(
                    f"filters.{section}[{index}].value must be a finite Decimal "
                    f"for op={op!r}, got bool {raw_value!r}"
                )
            try:
                value_tuple = Decimal(str(raw_value))
            except (ArithmeticError, ValueError, TypeError) as exc:
                raise InvalidCustomStrategyError(
                    f"filters.{section}[{index}].value must be a finite Decimal "
                    f"for op={op!r}, got {type(raw_value).__name__}: {raw_value!r} ({exc})"
                ) from exc
        rules.append(
            CustomStrategyFilterRule(
                factor=str(factor),
                op=str(op),
                value=value_tuple,
            )
        )
    return tuple(rules)


def _parse_score(value: object) -> tuple[CustomStrategyScoreFactor, ...]:
    if not isinstance(value, list) or not value:
        raise InvalidCustomStrategyError(
            "score must be a non-empty list of score-factor mappings"
        )
    factors: list[CustomStrategyScoreFactor] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise InvalidCustomStrategyError(
                f"score[{index}] must be a mapping, got {type(raw).__name__}"
            )
        unknown = set(raw.keys()) - _ALLOWED_SCORE_KEYS
        if unknown:
            raise InvalidCustomStrategyError(
                f"score[{index}] has unknown keys: {sorted(unknown)!r}; allowed: "
                f"{sorted(_ALLOWED_SCORE_KEYS)}"
            )
        for required in ("factor", "weight", "direction"):
            if required not in raw:
                raise InvalidCustomStrategyError(
                    f"score[{index}] is missing required key {required!r}"
                )
        try:
            weight = Decimal(str(raw["weight"]))
        except (ArithmeticError, ValueError, TypeError) as exc:
            raise InvalidCustomStrategyError(
                f"score[{index}].weight must be a finite Decimal, "
                f"got {raw['weight']!r} ({exc})"
            ) from exc
        factors.append(
            CustomStrategyScoreFactor(
                factor=str(raw["factor"]),
                weight=weight,
                direction=str(raw["direction"]),
            )
        )
    return tuple(factors)


def _parse_output(value: object) -> CustomStrategyOutput:
    if not isinstance(value, Mapping):
        raise InvalidCustomStrategyError(
            "output must be a mapping with keys 'include_top_n' and 'watch_next_n'"
        )
    unknown = set(value.keys()) - _ALLOWED_OUTPUT_KEYS
    if unknown:
        raise InvalidCustomStrategyError(
            f"output has unknown keys: {sorted(unknown)!r}; allowed: "
            f"{sorted(_ALLOWED_OUTPUT_KEYS)}"
        )
    for required in ("include_top_n", "watch_next_n"):
        if required not in value:
            raise InvalidCustomStrategyError(
                f"output.{required} is required"
            )
    return CustomStrategyOutput(
        include_top_n=int(value["include_top_n"]),
        watch_next_n=int(value["watch_next_n"]),
    )


def _resolve_factors(
    instrument_id: InstrumentId,
    factors_by_instrument: Mapping[InstrumentId, FactorCalculationResult],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
) -> FactorCalculationResult:
    if instrument_id in factors_by_instrument:
        return factors_by_instrument[instrument_id]
    bars = bars_by_instrument.get(instrument_id, ())
    return calculate_market_state_factors(
        bars,
        as_of_date=as_of_date,
        instrument_id=instrument_id,
    )


def _evaluate_filters(
    strategy: CustomStrategy,
    factor_values: Mapping[str, Decimal | None],
) -> _FilterOutcome:
    reasons: list[str] = []
    warnings: list[str] = []

    if strategy.filters_all:
        for rule in strategy.filters_all:
            outcome = _evaluate_rule(rule, factor_values)
            if not outcome.passed:
                reasons.append(
                    f"custom_strategy.filter_all_failed:{rule.factor}:{rule.op}"
                )
                warnings.append(
                    f"custom_strategy.filter_all_failed:{rule.factor}:{rule.op}:{outcome.detail}"
                )

    if strategy.filters_any:
        any_passed = False
        any_detail: list[str] = []
        for rule in strategy.filters_any:
            outcome = _evaluate_rule(rule, factor_values)
            if outcome.passed:
                any_passed = True
            else:
                any_detail.append(
                    f"{rule.factor}:{rule.op}:{outcome.detail}"
                )
        if not any_passed:
            reasons.append("custom_strategy.filter_any_failed")
            warnings.append(
                "custom_strategy.filter_any_failed:" + "|".join(any_detail)
            )

    return _FilterOutcome(
        passed=not reasons,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class _RuleOutcome:
    passed: bool
    detail: str


def _evaluate_rule(
    rule: CustomStrategyFilterRule,
    factor_values: Mapping[str, Decimal | None],
) -> _RuleOutcome:
    value = factor_values.get(rule.factor)
    if value is None or not isinstance(value, Decimal) or not value.is_finite():
        return _RuleOutcome(passed=False, detail="missing")
    if rule.op == "in":
        if not isinstance(rule.value, tuple):
            return _RuleOutcome(passed=False, detail="invalid_in_value")
        return _RuleOutcome(passed=value in rule.value, detail=str(value))
    if not isinstance(rule.value, Decimal):
        return _RuleOutcome(passed=False, detail="invalid_scalar_value")
    if rule.op == "gt":
        return _RuleOutcome(passed=value > rule.value, detail=str(value))
    if rule.op == "gte":
        return _RuleOutcome(passed=value >= rule.value, detail=str(value))
    if rule.op == "lt":
        return _RuleOutcome(passed=value < rule.value, detail=str(value))
    if rule.op == "lte":
        return _RuleOutcome(passed=value <= rule.value, detail=str(value))
    if rule.op == "eq":
        return _RuleOutcome(passed=value == rule.value, detail=str(value))
    return _RuleOutcome(passed=False, detail="unsupported_op")


def _score_candidate(
    strategy: CustomStrategy,
    factor_values: Mapping[str, Decimal | None],
) -> _ScoredOutcome | None:
    observed: dict[str, Decimal] = {}
    for score in strategy.score:
        value = factor_values.get(score.factor)
        if value is None or not isinstance(value, Decimal) or not value.is_finite():
            return None
        observed[score.factor] = value
    return _ScoredOutcome(
        observed_values=observed,
        normalized_values=dict(observed),
        normalized_score=_ZERO,
    )


@dataclass(frozen=True, slots=True)
class _ScoredOutcome:
    observed_values: dict[str, Decimal]
    normalized_values: dict[str, Decimal]
    normalized_score: Decimal


def _compute_min_max(
    entries: Sequence[_ScoredCandidate],
) -> dict[str, tuple[Decimal, Decimal]]:
    mins: dict[str, Decimal | None] = {}
    maxs: dict[str, Decimal | None] = {}
    for entry in entries:
        for factor_key, value in entry.observed_values.items():
            current_min = mins.get(factor_key)
            current_max = maxs.get(factor_key)
            if current_min is None or value < current_min:
                mins[factor_key] = value
            if current_max is None or value > current_max:
                maxs[factor_key] = value
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for factor_key in mins:
        if factor_key not in maxs or mins[factor_key] is None or maxs[factor_key] is None:
            continue
        result[factor_key] = (mins[factor_key], maxs[factor_key])  # type: ignore[assignment]
    return result


def _min_max_normalise(
    observed: Mapping[str, Decimal],
    min_max: Mapping[str, tuple[Decimal, Decimal]],
) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for factor_key, value in observed.items():
        bounds = min_max.get(factor_key)
        if bounds is None:
            out[factor_key] = _FIFTY
            continue
        lower, upper = bounds
        if upper == lower:
            out[factor_key] = _FIFTY
            continue
        out[factor_key] = _quantize((value - lower) / (upper - lower))
    return out


def _compose_score(
    strategy: CustomStrategy,
    normalized_values: Mapping[str, Decimal],
) -> Decimal:
    total = _ZERO
    for score in strategy.score:
        normalised = normalized_values.get(score.factor, _FIFTY)
        if score.direction == "lower":
            normalised = _ONE - normalised
        total += score.weight * normalised
    return _quantize(total)


def _decide(
    *,
    candidate: UniverseCandidate,
    index: int,
    include_top_n: int,
    watch_next_n: int,
) -> tuple[str, tuple[str, ...]]:
    if candidate.eligibility is UniverseEligibility.INELIGIBLE:
        return CustomStrategyDecision.EXCLUDE.value, ("custom_strategy.universe_ineligible",)
    if candidate.eligibility is UniverseEligibility.PARTIAL:
        if index < include_top_n:
            return (
                CustomStrategyDecision.WATCH.value,
                (
                    "custom_strategy.partial_history_capped_at_watch",
                    "custom_strategy.score_qualifies_for_include",
                ),
            )
        if index < include_top_n + watch_next_n:
            return (
                CustomStrategyDecision.WATCH.value,
                ("custom_strategy.partial_history_capped_at_watch",),
            )
        return (
            CustomStrategyDecision.EXCLUDE.value,
            (
                "custom_strategy.partial_history_capped_at_watch",
                "custom_strategy.below_watch_threshold",
            ),
        )
    if index < include_top_n:
        return CustomStrategyDecision.INCLUDE.value, ("custom_strategy.include",)
    if index < include_top_n + watch_next_n:
        return CustomStrategyDecision.WATCH.value, ("custom_strategy.watch",)
    return (
        CustomStrategyDecision.EXCLUDE.value,
        ("custom_strategy.below_watch_threshold",),
    )


def _build_ineligible_proposal(
    strategy: CustomStrategy,
    candidate: UniverseCandidate,
) -> CustomStrategyProposal:
    reasons = ("custom_strategy.universe_ineligible",)
    exclusion_reasons = tuple(f"universe:{reason}" for reason in candidate.reasons)
    return CustomStrategyProposal(
        instrument_id=candidate.instrument_id,
        symbol=candidate.symbol,
        exchange=candidate.exchange,
        channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
        channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.version,
        decision=CustomStrategyDecision.EXCLUDE.value,
        normalized_score=None,
        eligibility=candidate.eligibility.value,
        reasons=reasons,
        exclusion_reasons=exclusion_reasons,
        warnings=(),
    )


def _build_filtered_proposal(
    *,
    strategy: CustomStrategy,
    candidate: UniverseCandidate,
    factor_values: Mapping[str, Decimal | None],
    filter_outcome: _FilterOutcome,
) -> CustomStrategyProposal:
    observed: dict[str, Decimal] = {
        key: value
        for key, value in factor_values.items()
        if isinstance(value, Decimal) and value.is_finite()
    }
    return CustomStrategyProposal(
        instrument_id=candidate.instrument_id,
        symbol=candidate.symbol,
        exchange=candidate.exchange,
        channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
        channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.version,
        decision=CustomStrategyDecision.EXCLUDE.value,
        normalized_score=None,
        eligibility=candidate.eligibility.value,
        observed_factor_values=MappingProxyType(observed),
        reasons=filter_outcome.reasons,
        exclusion_reasons=filter_outcome.reasons,
        warnings=filter_outcome.warnings,
    )


def _build_scored_proposal(
    *,
    strategy: CustomStrategy,
    entry: _ScoredCandidate,
    decision: str,
) -> CustomStrategyProposal:
    reasons: list[str] = []
    if decision == CustomStrategyDecision.INCLUDE.value:
        reasons.append("custom_strategy.include")
    elif decision == CustomStrategyDecision.WATCH.value:
        reasons.append("custom_strategy.watch")
    else:
        reasons.append("custom_strategy.exclude")
    if entry.candidate.eligibility is UniverseEligibility.PARTIAL:
        reasons.append("custom_strategy.partial_history_capped_at_watch")
    return CustomStrategyProposal(
        instrument_id=entry.candidate.instrument_id,
        symbol=entry.candidate.symbol,
        exchange=entry.candidate.exchange,
        channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
        channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.version,
        decision=decision,
        normalized_score=entry.normalized_score,
        eligibility=entry.candidate.eligibility.value,
        observed_factor_values=MappingProxyType(dict(entry.observed_values)),
        normalized_factor_values=MappingProxyType(dict(entry.normalized_values)),
        reasons=tuple(_dedupe_preserve_order(reasons)),
    )


def _build_disabled_result(
    *,
    strategy: CustomStrategy,
    instruments: Sequence[Instrument],
    bars_by_instrument: Mapping[InstrumentId, Sequence[DailyBar]],
    as_of_date: date,
) -> CustomStrategyChannelResult:
    universe = build_etf_universe(
        instruments,
        bars_by_instrument,
        as_of_date,
        minimum_full_history_days=strategy.universe.minimum_history_days,
        minimum_partial_history_days=min(
            strategy.universe.minimum_history_days, 20
        ),
    )
    proposals: list[CustomStrategyProposal] = []
    full_count = 0
    partial_count = 0
    ineligible_count = 0
    no_opinion_count = 0
    for candidate in universe:
        if candidate.eligibility is UniverseEligibility.FULL:
            full_count += 1
        elif candidate.eligibility is UniverseEligibility.PARTIAL:
            partial_count += 1
        else:
            ineligible_count += 1
        proposals.append(
            CustomStrategyProposal(
                instrument_id=candidate.instrument_id,
                symbol=candidate.symbol,
                exchange=candidate.exchange,
                channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
                channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
                strategy_key=strategy.strategy_key,
                strategy_version=strategy.version,
                decision=CustomStrategyDecision.NO_OPINION.value,
                normalized_score=None,
                eligibility=candidate.eligibility.value,
                reasons=("custom_strategy.disabled",),
            )
        )
        no_opinion_count += 1
    proposals.sort(key=_result_proposal_sort_key)
    input_hash = _compute_input_hash(
        strategy=strategy,
        as_of_date=as_of_date,
        universe=universe,
    )
    output_hash = _compute_output_hash(proposals, ())
    return CustomStrategyChannelResult(
        channel_key=CUSTOM_STRATEGY_CHANNEL_KEY,
        channel_version=CUSTOM_STRATEGY_CHANNEL_VERSION,
        strategy_key=strategy.strategy_key,
        strategy_version=strategy.version,
        as_of_date=as_of_date,
        parameter_hash=strategy.parameter_hash,
        input_hash=input_hash,
        output_hash=output_hash,
        proposals=tuple(proposals),
        warnings=("custom_strategy.disabled",),
        full_count=full_count,
        partial_count=partial_count,
        ineligible_count=ineligible_count,
        no_opinion_count=no_opinion_count,
    )


def _compute_input_hash(
    *,
    strategy: CustomStrategy,
    as_of_date: date,
    universe: Sequence[UniverseCandidate],
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "channel_key": CUSTOM_STRATEGY_CHANNEL_KEY,
        "channel_version": CUSTOM_STRATEGY_CHANNEL_VERSION,
        "parameter_hash": strategy.parameter_hash,
        "universe": [
            {
                "eligibility": candidate.eligibility.value,
                "exchange": candidate.exchange,
                "history_days": candidate.history_days,
                "instrument_id": candidate.instrument_id.value,
                "latest_trade_date": candidate.latest_trade_date,
                "stale_days": candidate.stale_days,
                "symbol": candidate.symbol,
            }
            for candidate in universe
        ],
    }
    return content_hash(payload)


def _compute_output_hash(
    proposals: Sequence[CustomStrategyProposal],
    warnings: Iterable[str],
) -> str:
    payload = {
        "channel_key": CUSTOM_STRATEGY_CHANNEL_KEY,
        "channel_version": CUSTOM_STRATEGY_CHANNEL_VERSION,
        "proposals": [
            {
                "channel_key": proposal.channel_key,
                "channel_version": proposal.channel_version,
                "decision": proposal.decision,
                "eligibility": proposal.eligibility,
                "exchange": proposal.exchange,
                "instrument_id": proposal.instrument_id.value,
                "normalized_factor_values": {
                    key: _quantize(value)
                    for key, value in proposal.normalized_factor_values.items()
                },
                "normalized_score": _quantize(proposal.normalized_score)
                if proposal.normalized_score is not None
                else None,
                "observed_factor_values": {
                    key: _quantize(value)
                    for key, value in proposal.observed_factor_values.items()
                },
                "reasons": list(proposal.reasons),
                "strategy_key": proposal.strategy_key,
                "strategy_version": proposal.strategy_version,
                "symbol": proposal.symbol,
            }
            for proposal in proposals
        ],
        "warnings": sorted(warnings),
    }
    return content_hash(payload)


def _scored_sort_key(entry: _ScoredCandidate) -> tuple[Decimal, bytes]:
    return (-entry.normalized_score, entry.candidate.instrument_id.value.bytes)


def _result_proposal_sort_key(
    proposal: CustomStrategyProposal,
) -> tuple[int, Decimal, bytes]:
    decision_rank = _decision_rank(proposal.decision)
    if proposal.normalized_score is None:
        score_key: Decimal = Decimal("2")
    else:
        score_key = -proposal.normalized_score
    return (decision_rank, score_key, proposal.instrument_id.value.bytes)


def _decision_rank(decision: str) -> int:
    if decision == CustomStrategyDecision.INCLUDE.value:
        return 0
    if decision == CustomStrategyDecision.WATCH.value:
        return 1
    if decision == CustomStrategyDecision.EXCLUDE.value:
        return 2
    return 3


def _serialise_filter_value(value: Decimal | tuple[Decimal, ...]) -> str | tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(_quantize(item).__format__("f") for item in value)
    return _quantize(value).__format__("f")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _require_finite_decimal(value: object, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise InvalidCustomStrategyError(
            f"{field_name} must be a Decimal, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise InvalidCustomStrategyError(
            f"{field_name} must be a finite Decimal, got {value!s}"
        )


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


__all__ = [
    "ALLOWED_DIRECTIONS",
    "ALLOWED_FACTOR_KEYS",
    "ALLOWED_OPERATORS",
    "CUSTOM_STRATEGY_CHANNEL_KEY",
    "CUSTOM_STRATEGY_CHANNEL_VERSION",
    "CUSTOM_STRATEGY_FACTOR_SET_KEY",
    "CUSTOM_STRATEGY_FACTOR_SET_VERSION",
    "CustomStrategy",
    "CustomStrategyChannelResult",
    "CustomStrategyDecision",
    "CustomStrategyError",
    "CustomStrategyFilterRule",
    "CustomStrategyOutput",
    "CustomStrategyProposal",
    "CustomStrategyResultInvariantError",
    "CustomStrategyScoreFactor",
    "CustomStrategyUniverse",
    "InvalidCustomStrategyError",
    "evaluate_custom_strategy_channel",
    "parse_custom_strategy_mapping",
]
