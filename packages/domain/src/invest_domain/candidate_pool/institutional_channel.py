"""Stage 4A-0 PR-03 deterministic institutional-recommendation channel.

This module is the second formal slice of the Stage 4A-0 multi-channel
candidate-routing plan (see
``docs/plan/invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md``
particularly §5.3, §6 ``Channel B``, §7, §11). It accepts a validated
in-memory batch of institutional recommendations, applies the source
whitelist, expiry, deduplication and symbol-resolution rules and
emits one auditable ``Candidate Proposal`` per matching instrument.
The slice ships **no** JSON / CSV adapter, **no** CLI, **no**
filesystem, database, network or Provider access — those concerns are
deferred to a later pipeline increment.

Hard guarantees (every behaviour is unit-tested):

* Pure, deterministic function: same batch, same allowed source keys,
  same symbol mapping, same instruments / bars always produce the
  same :class:`InstitutionalRecommendationChannelResult` in the same
  order (stable tie-breaker on the raw :class:`UUID` bytes of the
  :class:`InstrumentId`).
* No copy of the baseline factor formulas — every instrument is first
  classified by
  :func:`invest_domain.candidate_pool.universe.build_etf_universe` so
  the institutional channel can never promote an ineligible ETF into
  a higher bucket (plan §5.3 / §11.4).
* The four-state ``decision`` vocabulary (``include`` / ``watch`` /
  ``exclude`` / ``no_opinion``) mirrors plan §7 so the fusion layer in
  PR-05 can consume the channel uniformly. PARTIAL candidates are
  capped at ``watch`` (plan §8) even when the rating is the strongest
  one; INELIGIBLE candidates always emit ``exclude``.
* Institutional recommendations are marked ``external_opinion=True``
  in the proposal ``metadata`` so downstream Evidence Pack generation
  can distinguish facts from opinions (plan §5.3, §25 row "AI 将机构
  观点当事实").
* Source-key whitelist is fail-closed: an unknown or missing whitelist
  raises :class:`DisallowedInstitutionSourceKeyError` and produces no
  proposal.
* Recommendations are deduped by ``(source_key, source_ref, symbol)``;
  identical-content duplicates collapse silently, conflicting-content
  duplicates are explicitly excluded (with warning) and never silently
  overwrite each other (plan §11.4).
* Expiry is checked against the caller-supplied ``as_of_datetime``;
  expired recommendations do not produce proposals and emit one
  warning per recommendation (plan §11.4).
* :attr:`InstitutionalRecommendationChannelResult.input_hash` and
  :attr:`InstitutionalRecommendationChannelResult.output_hash` are
  stable :func:`content_hash` digests satisfying plan §15's audit
  requirement without touching PostgreSQL.
* The channel version is pinned to
  :data:`INSTITUTIONAL_CHANNEL_VERSION` so every downstream audit can
  identify this exact algorithm revision.

This module deliberately does NOT:

* Import ``baseline_channel``, ``v1_adapter``, FastAPI, SQLAlchemy,
  Dagster, httpx, any Provider SDK or any clock / environment helper.
* Persist anything: it returns a frozen value object and is built so
  the candidate-pool persistence layer remains the single writer.
* Apply any parameter optimisation — every threshold and rating
  mapping is fixed by plan §11.3.
* Reuse the V1 :class:`V1Proposal.channel_key` whitelist
  (``OFFICIAL_CHANNEL_STRATEGIES`` contains only ``fqir``). The
  institutional channel ships its own
  :class:`InstitutionalRecommendationProposal` shape so V1's
  restriction is not loosened.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from invest_domain.candidate_pool.universe import (
    UniverseCandidate,
    UniverseEligibility,
    build_etf_universe,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.shared.canonical import content_hash

# ---------------------------------------------------------------------------
# Module-level pinned constants
# ---------------------------------------------------------------------------

#: Stable channel key consumed by the Stage 4A-0 fusion layer in PR-05.
#: Matches plan §6 ``Channel B`` so external callers and audit logs can
#: resolve the channel by name without consulting the source code.
INSTITUTIONAL_CHANNEL_KEY: Final[str] = "institutional_recommendation"

#: Pinned channel version. Bump only when the rating mapping, the
#: expiry / dedup semantics or the eligibility cap change in a way
#: that should be auditable.
INSTITUTIONAL_CHANNEL_VERSION: Final[str] = "1.0.0"

#: Decimal ``0`` / ``1`` literals kept as module constants so every
#: ``__post_init__`` / scoring branch uses the same Decimal context.
_ZERO: Final[Decimal] = Decimal("0")
_ONE: Final[Decimal] = Decimal("1")

#: Quantisation quantum for the rating → normalised-score mapping
#: (plan §11.3 fixed numbers; the quantum is shared with the baseline
#: factor calculator so bytewise rounding rules cannot diverge
#: between channels).
_SCORE_QUANTUM: Final[Decimal] = Decimal("0.00000001")

#: Sentinel metadata key that marks the proposal as an external opinion
#: rather than a derived system signal (plan §5.3).
EXTERNAL_OPINION_MARKER: Final[str] = "external_opinion"

#: Maximum allowed length (in Unicode code points) for the bounded
#: ``reason_summary`` field. Plan §11.4 forbids persisting the full
#: report text — only the bounded summary is kept — so the validator
#: enforces a deterministic cap so two runs cannot disagree on what
#: "bounded" means and so the audit hash stays reproducible.
REASON_SUMMARY_MAX_LENGTH: Final[int] = 500


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecommendationLevel(StrEnum):
    """The five discrete institutional-rating levels (plan §11.3).

    The string values match the JSON / CSV vocabulary plan §11.1 uses
    on disk; the channel does not import any parser so it only relies
    on the strings being equal to the canonical members.
    """

    RECOMMENDED = "recommended"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    AVOID = "avoid"


class InstitutionalDecision(StrEnum):
    """Four-state ``decision`` vocabulary mirroring plan §7.

    The channel emits ``include`` / ``watch`` / ``exclude`` /
    ``no_opinion`` per the multi-channel routing contract sketch in
    plan §7. ``no_opinion`` is reserved for the case where the channel
    cannot attach an auditable judgement (e.g. an empty input or a
    single no-opinion input); the institutional channel uses it only
    in those audit-only situations.
    """

    INCLUDE = "include"
    WATCH = "watch"
    EXCLUDE = "exclude"
    NO_OPINION = "no_opinion"


#: Plan §11.3 fixed rating → normalised-score mapping. Exposed as a
#: read-only mapping so callers can introspect it without mutating the
#: canonical table at runtime.
RECOMMENDATION_LEVEL_SCORES: Final[Mapping[str, Decimal]] = MappingProxyType(
    {
        RecommendationLevel.RECOMMENDED.value: Decimal("80"),
        RecommendationLevel.POSITIVE.value: Decimal("70"),
        RecommendationLevel.NEUTRAL.value: Decimal("50"),
        RecommendationLevel.NEGATIVE.value: Decimal("20"),
        RecommendationLevel.AVOID.value: Decimal("0"),
    }
)

#: Plan §11.3 fixed rating → ``raw`` decision bucket. The eligibility
#: gate is applied later (PARTIAL caps ``include`` to ``watch``,
#: INELIGIBLE forces ``exclude``); the table below describes the
#: rating-only outcome.
_RAW_DECISION_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType(
    {
        RecommendationLevel.RECOMMENDED.value: InstitutionalDecision.INCLUDE.value,
        RecommendationLevel.POSITIVE.value: InstitutionalDecision.INCLUDE.value,
        RecommendationLevel.NEUTRAL.value: InstitutionalDecision.WATCH.value,
        RecommendationLevel.NEGATIVE.value: InstitutionalDecision.EXCLUDE.value,
        RecommendationLevel.AVOID.value: InstitutionalDecision.EXCLUDE.value,
    }
)


# ---------------------------------------------------------------------------
# Exceptions raised by this module
# ---------------------------------------------------------------------------


class InstitutionalChannelError(ValueError):
    """Base class for every institutional-channel configuration failure.

    Inherits from :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still treats channel failures as
    validation-time errors. Subclasses tag the failure so callers can
    react programmatically without parsing free text.
    """

    code: str = "institutional_channel.error"


class InvalidInstitutionRecommendationError(InstitutionalChannelError):
    """Raised when a single :class:`InstitutionRecommendation` is malformed."""

    code: str = "institutional_channel.invalid_recommendation"


class InvalidInstitutionRecommendationBatchError(InstitutionalChannelError):
    """Raised when an :class:`InstitutionRecommendationBatch` is malformed."""

    code: str = "institutional_channel.invalid_batch"


class DisallowedInstitutionSourceKeyError(InstitutionalChannelError):
    """Raised when the batch's ``source_key`` is not in the allowed whitelist."""

    code: str = "institutional_channel.disallowed_source"

    def __init__(self, source_key: str, allowed: AbstractSet[str]) -> None:
        message = (
            f"InstitutionRecommendationBatch.source_key={source_key!r} is not in "
            f"the supplied whitelist ({sorted(allowed)!r}); the institutional "
            "channel fails closed to avoid leaking unvetted external opinions"
        )
        super().__init__(message)
        self.source_key = source_key
        self.allowed = frozenset(allowed)


class InstitutionChannelResultInvariantError(InstitutionalChannelError):
    """Raised when the post-init invariants of the result / proposal are broken."""

    code: str = "institutional_channel.invalid_result"


# ---------------------------------------------------------------------------
# Input value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstitutionRecommendation:
    """A single institutional-recommendation row (plan §11.1 schema).

    The field set is the *minimum* the channel needs to produce an
    auditable proposal:

    - ``symbol`` — the V2-facing ETF symbol resolved via the caller
      supplied ``symbol_to_instrument`` mapping.
    - ``recommendation_level`` — the discrete rating bucket, drives
      ``normalized_score`` and the ``include`` / ``watch`` /
      ``exclude`` raw decision (plan §11.3).
    - ``source_ref`` — the citation identifier the institution itself
      emitted (e.g. ``"institution_x:report_20260803"``); participates
      in the dedup key.
    - ``confidence`` — finite ``Decimal`` in ``[0, 1]`` describing how
      strongly the institution stands behind the rating.
    - ``reason_summary`` — bounded human-readable summary; only the
      bounded string is preserved (plan §11.4 forbids storing the full
      report text).
    - ``original_score`` / ``original_scale`` — optional description
      of the institution's native scoring scale (e.g. ``4`` on a
      ``1-5`` scale); preserved verbatim in ``metadata``.
    """

    symbol: str
    recommendation_level: RecommendationLevel
    source_ref: str
    confidence: Decimal
    reason_summary: str
    original_score: Decimal | None = None
    original_scale: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.symbol must be a non-empty string"
            )
        if not isinstance(self.recommendation_level, RecommendationLevel):
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.recommendation_level must be a "
                f"RecommendationLevel, got {type(self.recommendation_level).__name__}"
            )
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.source_ref must be a non-empty string"
            )
        if not isinstance(self.confidence, Decimal) or not self.confidence.is_finite():
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.confidence must be a finite Decimal, "
                f"got {self.confidence!r}"
            )
        if not (_ZERO <= self.confidence <= _ONE):
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.confidence must lie within [0, 1], "
                f"got {self.confidence!s}"
            )
        if not isinstance(self.reason_summary, str) or not self.reason_summary.strip():
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.reason_summary must be a non-empty string"
            )
        if len(self.reason_summary) > REASON_SUMMARY_MAX_LENGTH:
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.reason_summary must be a bounded "
                f"summary of at most {REASON_SUMMARY_MAX_LENGTH} characters "
                f"(plan §11.4 forbids persisting the full report text); "
                f"got {len(self.reason_summary)} characters"
            )
        if self.original_score is not None and (
            not isinstance(self.original_score, Decimal) or not self.original_score.is_finite()
        ):
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.original_score must be a finite Decimal "
                f"or None, got {self.original_score!r}"
            )
        if self.original_scale is not None and (
            not isinstance(self.original_scale, str) or not self.original_scale.strip()
        ):
            raise InvalidInstitutionRecommendationError(
                "InstitutionRecommendation.original_scale must be a non-empty "
                f"string or None, got {self.original_scale!r}"
            )


@dataclass(frozen=True, slots=True)
class InstitutionRecommendationBatch:
    """An immutable, fully-validated batch of institutional recommendations.

    Carries the ``source_key``, the publication / expiry timestamps
    and the per-symbol recommendations. The channel rejects batches
    whose ``valid_until`` is not strictly after ``published_at`` so
    every downstream computation can treat the window as non-empty.
    """

    source_key: str
    published_at: datetime
    valid_until: datetime
    recommendations: tuple[InstitutionRecommendation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise InvalidInstitutionRecommendationBatchError(
                "InstitutionRecommendationBatch.source_key must be a non-empty string"
            )
        if not isinstance(self.published_at, datetime):
            raise InvalidInstitutionRecommendationBatchError(
                "InstitutionRecommendationBatch.published_at must be a datetime, "
                f"got {type(self.published_at).__name__}"
            )
        _require_aware_datetime(self.published_at, "InstitutionRecommendationBatch.published_at")
        if not isinstance(self.valid_until, datetime):
            raise InvalidInstitutionRecommendationBatchError(
                "InstitutionRecommendationBatch.valid_until must be a datetime, "
                f"got {type(self.valid_until).__name__}"
            )
        _require_aware_datetime(self.valid_until, "InstitutionRecommendationBatch.valid_until")
        if self.valid_until <= self.published_at:
            raise InvalidInstitutionRecommendationBatchError(
                "InstitutionRecommendationBatch.valid_until must be strictly "
                f"after published_at (valid_until={self.valid_until.isoformat()} "
                f"<= published_at={self.published_at.isoformat()})"
            )
        if not isinstance(self.recommendations, tuple):
            raise InvalidInstitutionRecommendationBatchError(
                "InstitutionRecommendationBatch.recommendations must be a "
                "tuple[InstitutionRecommendation, ...]"
            )
        for index, item in enumerate(self.recommendations):
            if not isinstance(item, InstitutionRecommendation):
                raise InvalidInstitutionRecommendationBatchError(
                    f"InstitutionRecommendationBatch.recommendations[{index}] "
                    "must be an InstitutionRecommendation, "
                    f"got {type(item).__name__}"
                )


# ---------------------------------------------------------------------------
# Output value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstitutionalRecommendationProposal:
    """One institutional-recommendation ``Candidate Proposal`` (plan §7).

    The shape is intentionally close to plan §7's ``CandidateProposal``
    sketch (carrying ``published_at`` / ``valid_until`` /
    ``evidence_refs`` / ``metadata``) because the institutional
    channel is the canonical example of a channel with external
    evidence. ``symbol`` and ``exchange`` are duplicated on the row so
    downstream consumers do not need to re-resolve them.
    """

    instrument_id: InstrumentId
    symbol: str
    exchange: str
    channel_key: str
    channel_version: str
    decision: str
    normalized_score: Decimal
    confidence: Decimal
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    published_at: datetime
    valid_until: datetime
    metadata: Mapping[str, Decimal | int | bool | str | None] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.instrument_id must be an "
                f"InstrumentId, got {type(self.instrument_id).__name__}"
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.symbol must be a non-empty string"
            )
        if not isinstance(self.exchange, str) or not self.exchange.strip():
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.exchange must be a non-empty string"
            )
        if self.channel_key != INSTITUTIONAL_CHANNEL_KEY:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.channel_key must equal "
                f"{INSTITUTIONAL_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != INSTITUTIONAL_CHANNEL_VERSION:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.channel_version must equal "
                f"{INSTITUTIONAL_CHANNEL_VERSION!r}, got {self.channel_version!r}"
            )
        if self.decision not in {
            InstitutionalDecision.INCLUDE.value,
            InstitutionalDecision.WATCH.value,
            InstitutionalDecision.EXCLUDE.value,
            InstitutionalDecision.NO_OPINION.value,
        }:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.decision must be one of "
                "include/watch/exclude/no_opinion, got " + repr(self.decision)
            )
        _require_finite_decimal(
            self.normalized_score,
            "InstitutionalRecommendationProposal.normalized_score",
        )
        if not (_ZERO <= self.normalized_score <= Decimal("100")):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.normalized_score must lie "
                f"within [0, 100], got {self.normalized_score!s}"
            )
        _require_finite_decimal(
            self.confidence,
            "InstitutionalRecommendationProposal.confidence",
        )
        if not (_ZERO <= self.confidence <= _ONE):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.confidence must lie "
                f"within [0, 1], got {self.confidence!s}"
            )
        if not isinstance(self.reasons, tuple):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.reasons must be a tuple[str, ...]"
            )
        for item in self.reasons:
            if not isinstance(item, str) or not item.strip():
                raise InstitutionChannelResultInvariantError(
                    "InstitutionalRecommendationProposal.reasons must contain non-empty strings"
                )
        if not isinstance(self.evidence_refs, tuple):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.evidence_refs must be a tuple[str, ...]"
            )
        for item in self.evidence_refs:
            if not isinstance(item, str) or not item.strip():
                raise InstitutionChannelResultInvariantError(
                    "InstitutionalRecommendationProposal.evidence_refs must "
                    "contain non-empty strings"
                )
        _require_aware_datetime(
            self.published_at,
            "InstitutionalRecommendationProposal.published_at",
        )
        _require_aware_datetime(
            self.valid_until,
            "InstitutionalRecommendationProposal.valid_until",
        )
        if self.valid_until <= self.published_at:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.valid_until must be "
                "strictly after published_at"
            )
        if not isinstance(self.metadata, Mapping):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.metadata must be a Mapping, "
                f"got {type(self.metadata).__name__}"
            )
        for key, value in self.metadata.items():
            if not isinstance(key, str) or not key.strip():
                raise InstitutionChannelResultInvariantError(
                    "InstitutionalRecommendationProposal.metadata keys must be non-empty strings"
                )
            if not isinstance(value, (Decimal, int, bool, str, type(None))):
                raise InstitutionChannelResultInvariantError(
                    f"InstitutionalRecommendationProposal.metadata[{key!r}] "
                    "must be one of Decimal/int/bool/str/None, "
                    f"got {type(value).__name__}"
                )
        if not self.metadata.get(EXTERNAL_OPINION_MARKER, False):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationProposal.metadata must carry the "
                f"{EXTERNAL_OPINION_MARKER!r} marker (plan §5.3)"
            )


@dataclass(frozen=True, slots=True)
class InstitutionalRecommendationChannelResult:
    """The frozen output of :func:`evaluate_institutional_recommendation_channel`.

    Carries the audit block (``channel_key`` / ``channel_version`` /
    ``source_key`` / ``as_of_date`` / ``as_of_datetime`` /
    ``input_hash`` / ``output_hash``) plus the stable, sorted
    proposals and the structured warnings emitted during the run.
    The proposal order is ``(eligibility_rank, decision_rank,
    -normalized_score, instrument_id.value.bytes)`` so two runs on
    the same logical input always emit byte-identical ordering
    (plan §13 ``稳定排序``).
    """

    channel_key: str
    channel_version: str
    source_key: str
    as_of_date: date
    as_of_datetime: datetime
    input_hash: str
    output_hash: str
    proposals: tuple[InstitutionalRecommendationProposal, ...]
    warnings: tuple[str, ...] = ()
    unknown_symbol_count: int = 0
    expired_count: int = 0
    conflict_count: int = 0
    include_count: int = 0
    watch_count: int = 0
    exclude_count: int = 0
    no_opinion_count: int = 0

    def __post_init__(self) -> None:
        if self.channel_key != INSTITUTIONAL_CHANNEL_KEY:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.channel_key must equal "
                f"{INSTITUTIONAL_CHANNEL_KEY!r}, got {self.channel_key!r}"
            )
        if self.channel_version != INSTITUTIONAL_CHANNEL_VERSION:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.channel_version must "
                f"equal {INSTITUTIONAL_CHANNEL_VERSION!r}, "
                f"got {self.channel_version!r}"
            )
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.source_key must be a non-empty string"
            )
        if not isinstance(self.as_of_date, date):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.as_of_date must be a "
                f"date, got {type(self.as_of_date).__name__}"
            )
        _require_aware_datetime(
            self.as_of_datetime,
            "InstitutionalRecommendationChannelResult.as_of_datetime",
        )
        if self.as_of_datetime.date() != self.as_of_date:
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.as_of_date must equal "
                "as_of_datetime.date(); got "
                f"as_of_date={self.as_of_date.isoformat()} vs "
                f"as_of_datetime.date()={self.as_of_datetime.date().isoformat()}"
            )
        for field_name in (
            "input_hash",
            "output_hash",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) != 64:
                raise InstitutionChannelResultInvariantError(
                    f"InstitutionalRecommendationChannelResult.{field_name} must "
                    f"be a 64-character SHA-256 hex digest, got {value!r}"
                )
        if not isinstance(self.proposals, tuple):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.proposals must be a "
                "tuple[InstitutionalRecommendationProposal, ...]"
            )
        seen: set[UUID] = set()
        for proposal in self.proposals:
            if proposal.instrument_id.value in seen:
                raise InstitutionChannelResultInvariantError(
                    "InstitutionalRecommendationChannelResult.proposals contain "
                    f"duplicate instrument_id {proposal.instrument_id}"
                )
            seen.add(proposal.instrument_id.value)
        if not isinstance(self.warnings, tuple):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult.warnings must be a tuple[str, ...]"
            )
        for item in self.warnings:
            if not isinstance(item, str) or not item.strip():
                raise InstitutionChannelResultInvariantError(
                    "InstitutionalRecommendationChannelResult.warnings must "
                    "contain non-empty strings"
                )
        for field_name in (
            "unknown_symbol_count",
            "expired_count",
            "conflict_count",
            "include_count",
            "watch_count",
            "exclude_count",
            "no_opinion_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise InstitutionChannelResultInvariantError(
                    f"InstitutionalRecommendationChannelResult.{field_name} must "
                    f"be a non-negative int, got {value!r}"
                )
        decision_count = (
            self.include_count + self.watch_count + self.exclude_count + self.no_opinion_count
        )
        if decision_count != len(self.proposals):
            raise InstitutionChannelResultInvariantError(
                "InstitutionalRecommendationChannelResult decision counters "
                "must sum to len(proposals); got "
                f"include={self.include_count} + watch={self.watch_count} + "
                f"exclude={self.exclude_count} + no_opinion={self.no_opinion_count}"
                f" = {decision_count} vs len(proposals)={len(self.proposals)}"
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_institutional_recommendation_channel(
    *,
    instruments: Sequence[object],
    bars_by_instrument: Mapping[InstrumentId, Sequence[object]],
    batch: InstitutionRecommendationBatch,
    allowed_source_keys: AbstractSet[str],
    as_of_datetime: datetime,
    symbol_to_instrument: Mapping[str, InstrumentId],
    as_of_date: date | None = None,
) -> InstitutionalRecommendationChannelResult:
    """Run the deterministic institutional-recommendation channel.

    The function:

    1. Validates the supplied ``allowed_source_keys`` and ``batch.source_key``;
       both an empty / missing whitelist and a disallowed source key
       raise :class:`DisallowedInstitutionSourceKeyError` (plan §11.4
       source whitelist).
    2. Validates the ``symbol_to_instrument`` mapping is non-empty so
       the channel cannot silently emit proposals that fail to resolve
       an instrument identity.
    3. Calls :func:`invest_domain.candidate_pool.universe.build_etf_universe`
       on the supplied instrument + bar set to classify every input
       instrument into ``FULL`` / ``PARTIAL`` / ``INELIGIBLE``. The
       classifier is the same one the baseline-factor channel uses, so
       the institutional channel can never promote an ineligible ETF
       into a higher bucket (plan §5.3). The full per-instrument
       verdict (eligibility, history_days, latest_trade_date,
       latest_close, stale_days, reasons, can_enter_watch_only,
       identity) is folded into the audit :attr:`input_hash` so a
       change in bars that flips an instrument from ``FULL`` to
       ``INELIGIBLE`` (or to ``PARTIAL``) is auditable in the channel
       digest without re-running the channel.
    4. Iterates over ``batch.recommendations`` in input order; for
       every recommendation it:

       * Resolves the ``symbol`` against ``symbol_to_instrument`` and
         looks up the matching :class:`UniverseCandidate`. An unknown
         symbol produces no proposal and emits a per-row warning.
       * Drops expired recommendations (``as_of_datetime > valid_until``)
         with a per-row warning; the proposal is never built.
       * Dedupes by ``(source_key, source_ref, symbol)``. Identical
         content collapses silently; conflicting content emits a
         per-key warning and produces no proposal for the conflict
         (the *conflict_count* counter and a structured warning keep
         the audit trail honest).
       * Maps ``recommendation_level`` to ``normalized_score`` (plan
         §11.3) and the raw ``include`` / ``watch`` / ``exclude``
         decision. INELIGIBLE instruments force ``exclude``; PARTIAL
         instruments cap the decision at ``watch`` (plan §8).
    5. Sorts the resulting proposals deterministically
       (``eligibility_rank`` ascending, ``decision_rank`` ascending,
       ``normalized_score`` descending, ``instrument_id.value.bytes``
       ascending) and hashes the canonical payload
       (:attr:`input_hash`) plus the canonical proposal payload
       (:attr:`output_hash`).

    Parameters
    ----------
    instruments:
        ETF instruments that feed ``build_etf_universe``. The function
        does not mutate this sequence.
    bars_by_instrument:
        Mapping from :class:`InstrumentId` to its bar series. The
        function never mutates this mapping.
    batch:
        Pre-validated in-memory batch of institutional recommendations.
    allowed_source_keys:
        Explicit whitelist of accepted ``source_key`` values. Must be
        non-empty AND must contain ``batch.source_key``; otherwise the
        channel raises :class:`DisallowedInstitutionSourceKeyError`.
    as_of_datetime:
        Timezone-aware evaluation instant used to gate expiry. Must
        carry a tzinfo so the channel cannot accidentally compare
        naive datetimes across DST or against the timezone-aware
        ``valid_until``.
    symbol_to_instrument:
        Caller-supplied symbol → :class:`InstrumentId` mapping. The
        channel does not look the symbol up against ``instruments`` so
        the caller can pin the resolution externally (e.g. to a
        specific revision of the universe).
    as_of_date:
        Optional explicit trading-day for ``build_etf_universe``.
        Defaults to ``as_of_datetime.date()``.

    Returns
    -------
    InstitutionalRecommendationChannelResult
        Frozen value object with one
        :class:`InstitutionalRecommendationProposal` per surviving
        recommendation, plus the audit block (``channel_key`` /
        ``channel_version`` / ``source_key`` / ``as_of_date`` /
        ``as_of_datetime`` / ``input_hash`` / ``output_hash``),
        structured warnings, and the eligibility / decision counters
        so downstream audits can verify the run without re-deriving
        them.

    Raises
    ------
    DisallowedInstitutionSourceKeyError
        ``allowed_source_keys`` is empty / missing or does not contain
        ``batch.source_key``.
    InvalidInstitutionRecommendationBatchError
        ``batch`` itself is malformed; raised eagerly by the
        :class:`InstitutionRecommendationBatch.__post_init__`.
    TypeError
        ``as_of_datetime`` is not a datetime, ``as_of_date`` is not a
        date, ``allowed_source_keys`` / ``symbol_to_instrument`` are
        not the documented container types, ``instruments`` /
        ``bars_by_instrument`` are not the documented types.
    """
    if not isinstance(allowed_source_keys, (set, frozenset)):
        raise TypeError(
            "evaluate_institutional_recommendation_channel allowed_source_keys "
            "must be a set or frozenset of strings, got "
            f"{type(allowed_source_keys).__name__}"
        )
    if not allowed_source_keys:
        raise DisallowedInstitutionSourceKeyError(
            source_key=batch.source_key,
            allowed=allowed_source_keys,
        )
    if batch.source_key not in allowed_source_keys:
        raise DisallowedInstitutionSourceKeyError(
            source_key=batch.source_key,
            allowed=allowed_source_keys,
        )
    if not isinstance(as_of_datetime, datetime):
        raise TypeError(
            "evaluate_institutional_recommendation_channel as_of_datetime "
            f"must be a datetime, got {type(as_of_datetime).__name__}"
        )
    if as_of_datetime.tzinfo is None or as_of_datetime.utcoffset() is None:
        raise InstitutionalChannelError(
            "evaluate_institutional_recommendation_channel as_of_datetime must "
            f"be timezone-aware; got naive {as_of_datetime.isoformat()}"
        )
    resolved_as_of_date = as_of_date if as_of_date is not None else as_of_datetime.date()
    if not isinstance(resolved_as_of_date, date):
        raise TypeError(
            "evaluate_institutional_recommendation_channel as_of_date must "
            f"be a date or None, got {type(resolved_as_of_date).__name__}"
        )
    if resolved_as_of_date != as_of_datetime.date():
        raise InvalidInstitutionRecommendationBatchError(
            "evaluate_institutional_recommendation_channel as_of_date must "
            "equal as_of_datetime.date(); got "
            f"as_of_date={resolved_as_of_date.isoformat()} vs "
            f"as_of_datetime.date()={as_of_datetime.date().isoformat()}"
        )
    if not isinstance(symbol_to_instrument, Mapping):
        raise TypeError(
            "evaluate_institutional_recommendation_channel symbol_to_instrument "
            f"must be a Mapping[str, InstrumentId], got {type(symbol_to_instrument).__name__}"
        )
    for code, instrument_id in symbol_to_instrument.items():
        if not isinstance(code, str) or not code.strip():
            raise TypeError(
                "evaluate_institutional_recommendation_channel symbol_to_instrument "
                "keys must be non-empty strings"
            )
        if not isinstance(instrument_id, InstrumentId):
            raise TypeError(
                "evaluate_institutional_recommendation_channel symbol_to_instrument "
                "values must be InstrumentId instances"
            )

    from invest_domain.instruments.models import Instrument
    from invest_domain.market_data.models import DailyBar

    if not all(isinstance(item, Instrument) for item in instruments):
        raise TypeError(
            "evaluate_institutional_recommendation_channel instruments must be "
            "a Sequence[Instrument]"
        )
    for instrument_id, bars in bars_by_instrument.items():
        if not isinstance(instrument_id, InstrumentId):
            raise TypeError(
                "evaluate_institutional_recommendation_channel bars_by_instrument "
                "keys must be InstrumentId instances"
            )
        if not isinstance(bars, (list, tuple)):
            raise TypeError(
                "evaluate_institutional_recommendation_channel bars_by_instrument "
                "values must be a Sequence[DailyBar]"
            )
        for bar in bars:
            if not isinstance(bar, DailyBar):
                raise TypeError(
                    "evaluate_institutional_recommendation_channel bars_by_instrument "
                    "values must contain DailyBar instances"
                )

    universe = build_etf_universe(
        instruments,
        bars_by_instrument,
        resolved_as_of_date,
    )
    universe_by_id: dict[InstrumentId, UniverseCandidate] = {
        candidate.instrument_id: candidate for candidate in universe
    }
    instrument_by_id: dict[InstrumentId, object] = {
        instrument.instrument_id: instrument
        for instrument in instruments
        if getattr(instrument, "instrument_id", None) is not None
    }
    universe_fingerprint: list[Mapping[str, object]] = [
        {
            "instrument_id": candidate.instrument_id,
            "symbol": candidate.symbol,
            "exchange": candidate.exchange,
            "eligibility": candidate.eligibility.value,
            "history_days": candidate.history_days,
            "latest_trade_date": candidate.latest_trade_date,
            "latest_close": candidate.latest_close,
            "stale_days": candidate.stale_days,
            "reasons": list(candidate.reasons),
            "can_enter_watch_only": candidate.can_enter_watch_only,
        }
        for candidate in universe
    ]

    input_hash = _compute_input_hash(
        batch=batch,
        allowed_source_keys=allowed_source_keys,
        as_of_datetime=as_of_datetime,
        symbol_to_instrument=symbol_to_instrument,
        universe_fingerprint=universe_fingerprint,
    )

    proposals: list[InstitutionalRecommendationProposal] = []
    warnings: list[str] = []
    unknown_symbol_count = 0
    expired_count = 0
    conflict_count = 0
    include_count = 0
    watch_count = 0
    exclude_count = 0
    no_opinion_count = 0

    dedup_groups: dict[
        tuple[str, str, str],
        list[InstitutionRecommendation],
    ] = {}
    for recommendation in batch.recommendations:
        dedup_key = (
            batch.source_key,
            recommendation.source_ref,
            recommendation.symbol,
        )
        dedup_groups.setdefault(dedup_key, []).append(recommendation)

    conflicting_keys: set[tuple[str, str, str]] = set()
    representative: dict[
        tuple[str, str, str],
        InstitutionRecommendation,
    ] = {}
    for dedup_key, group in dedup_groups.items():
        if len(group) == 1:
            representative[dedup_key] = group[0]
            continue
        first = group[0]
        if all(_recommendation_content_equal(first, item) for item in group[1:]):
            representative[dedup_key] = first
            continue
        conflicting_keys.add(dedup_key)
        conflict_count += 1
        warnings.append(
            f"institutional.conflict:{dedup_key[0]}:{dedup_key[1]}:{dedup_key[2]}:"
            f"count={len(group)}"
        )

    for index, recommendation in enumerate(batch.recommendations):
        dedup_key = (
            batch.source_key,
            recommendation.source_ref,
            recommendation.symbol,
        )
        if dedup_key in conflicting_keys:
            continue
        if dedup_key in representative and representative[dedup_key] is not recommendation:
            continue

        if recommendation.symbol not in symbol_to_instrument:
            unknown_symbol_count += 1
            warnings.append(f"institutional.unknown_symbol:{recommendation.symbol}")
            continue

        instrument_id = symbol_to_instrument[recommendation.symbol]
        universe_candidate = universe_by_id.get(instrument_id)
        if universe_candidate is None:
            unknown_symbol_count += 1
            warnings.append(f"institutional.universe_missing:{recommendation.symbol}")
            continue

        instrument = instrument_by_id.get(instrument_id)
        if instrument is None:
            unknown_symbol_count += 1
            warnings.append(f"institutional.instrument_missing:{recommendation.symbol}")
            continue

        if as_of_datetime > batch.valid_until:
            expired_count += 1
            warnings.append(
                f"institutional.expired:{batch.source_key}:"
                f"{recommendation.source_ref}:{recommendation.symbol}:"
                f"as_of={as_of_datetime.isoformat()}>"
                f"valid_until={batch.valid_until.isoformat()}:row_{index}"
            )
            continue

        proposal = _build_proposal(
            recommendation=recommendation,
            batch=batch,
            universe_candidate=universe_candidate,
            instrument=instrument,
        )
        proposals.append(proposal)
        if proposal.decision == InstitutionalDecision.INCLUDE.value:
            include_count += 1
        elif proposal.decision == InstitutionalDecision.WATCH.value:
            watch_count += 1
        elif proposal.decision == InstitutionalDecision.EXCLUDE.value:
            exclude_count += 1
        else:
            no_opinion_count += 1

    proposals.sort(key=_proposal_sort_key)
    proposals_tuple = tuple(proposals)
    output_hash = _compute_output_hash(proposals_tuple, warnings)

    return InstitutionalRecommendationChannelResult(
        channel_key=INSTITUTIONAL_CHANNEL_KEY,
        channel_version=INSTITUTIONAL_CHANNEL_VERSION,
        source_key=batch.source_key,
        as_of_date=resolved_as_of_date,
        as_of_datetime=as_of_datetime,
        input_hash=input_hash,
        output_hash=output_hash,
        proposals=proposals_tuple,
        warnings=tuple(warnings),
        unknown_symbol_count=unknown_symbol_count,
        expired_count=expired_count,
        conflict_count=conflict_count,
        include_count=include_count,
        watch_count=watch_count,
        exclude_count=exclude_count,
        no_opinion_count=no_opinion_count,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_proposal(
    *,
    recommendation: InstitutionRecommendation,
    batch: InstitutionRecommendationBatch,
    universe_candidate: UniverseCandidate,
    instrument: object,
) -> InstitutionalRecommendationProposal:
    """Map one surviving recommendation onto its ``CandidateProposal``.

    Encapsulates the rating → ``normalized_score`` mapping (plan
    §11.3), the eligibility-driven decision cap (plan §8 / §5.3) and
    the audit ``metadata`` block (with the ``external_opinion``
    marker) so the public entry point stays a thin orchestrator.
    """

    raw_decision = _RAW_DECISION_BY_LEVEL[recommendation.recommendation_level.value]
    eligibility = universe_candidate.eligibility
    decision = _apply_eligibility_cap(raw_decision=raw_decision, eligibility=eligibility)
    reasons = _build_reasons(
        recommendation=recommendation,
        universe_candidate=universe_candidate,
        decision=decision,
    )
    metadata = _build_metadata(
        recommendation=recommendation,
        batch=batch,
        universe_candidate=universe_candidate,
        decision=decision,
    )
    evidence_refs = _build_evidence_refs(recommendation=recommendation, batch=batch)
    exchange = getattr(instrument, "exchange", "")
    return InstitutionalRecommendationProposal(
        instrument_id=universe_candidate.instrument_id,
        symbol=universe_candidate.symbol,
        exchange=exchange,
        channel_key=INSTITUTIONAL_CHANNEL_KEY,
        channel_version=INSTITUTIONAL_CHANNEL_VERSION,
        decision=decision,
        normalized_score=RECOMMENDATION_LEVEL_SCORES[recommendation.recommendation_level.value],
        confidence=recommendation.confidence,
        reasons=reasons,
        evidence_refs=evidence_refs,
        published_at=batch.published_at,
        valid_until=batch.valid_until,
        metadata=metadata,
    )


def _apply_eligibility_cap(*, raw_decision: str, eligibility: UniverseEligibility) -> str:
    """Apply the universe-eligibility cap on the rating-only decision.

    - ``INELIGIBLE`` always forces ``exclude`` so an external opinion
      cannot promote a hard-gated ETF.
    - ``PARTIAL`` caps ``include`` at ``watch`` (plan §8). ``watch``
      and ``exclude`` pass through unchanged so a strongly negative
      institution rating still produces ``exclude`` for PARTIAL.
    - ``FULL`` accepts the rating-only decision verbatim.
    """

    if eligibility is UniverseEligibility.INELIGIBLE:
        return InstitutionalDecision.EXCLUDE.value
    if eligibility is UniverseEligibility.PARTIAL:
        if raw_decision == InstitutionalDecision.INCLUDE.value:
            return InstitutionalDecision.WATCH.value
        return raw_decision
    return raw_decision


def _build_reasons(
    *,
    recommendation: InstitutionRecommendation,
    universe_candidate: UniverseCandidate,
    decision: str,
) -> tuple[str, ...]:
    """Compose the stable reasons list for one proposal.

    The list always starts with the rating token and the eligibility
    token so audit readers can answer "why this decision?" without
    re-deriving the rating mapping. Universe-level exclusion reasons
    are appended verbatim from the :class:`UniverseCandidate` so the
    hard gate is traceable end-to-end.
    """

    reasons: list[str] = []
    reasons.append(f"institutional.rating:{recommendation.recommendation_level.value}")
    reasons.append(f"institutional.eligibility:{universe_candidate.eligibility.value}")
    reasons.append(f"institutional.decision:{decision}")
    for universe_reason in universe_candidate.reasons:
        reasons.append(f"institutional.universe:{universe_reason}")
    if (
        decision == InstitutionalDecision.WATCH.value
        and universe_candidate.eligibility is UniverseEligibility.PARTIAL
    ):
        reasons.append("institutional.partial_history_capped_at_watch")
    return tuple(_dedupe_preserve_order(reasons))


def _build_metadata(
    *,
    recommendation: InstitutionRecommendation,
    batch: InstitutionRecommendationBatch,
    universe_candidate: UniverseCandidate,
    decision: str,
) -> MappingProxyType:
    """Build the JSON-serialisable metadata mapping for one proposal.

    Carries the canonical :data:`EXTERNAL_OPINION_MARKER` plus the
    audit fields the downstream Evidence Pack generation in PR-05
    will rely on: ``channel_source_key``, ``recommendation_level``,
    ``original_score`` / ``original_scale``, the eligibility tag and
    the final ``decision``. Only JSON-serialisable scalar values are
    allowed so the proposal can be persisted without further
    translation (plan §5.3 / §11.4).
    """

    payload: dict[str, Decimal | int | bool | str | None] = {
        EXTERNAL_OPINION_MARKER: True,
        "channel_source_key": batch.source_key,
        "source_ref": recommendation.source_ref,
        "recommendation_level": recommendation.recommendation_level.value,
        "eligibility": universe_candidate.eligibility.value,
        "decision": decision,
    }
    if recommendation.original_score is not None:
        payload["original_score"] = _quantize(recommendation.original_score)
    else:
        payload["original_score"] = None
    payload["original_scale"] = recommendation.original_scale
    payload["reason_summary"] = recommendation.reason_summary
    return MappingProxyType(payload)


def _build_evidence_refs(
    *,
    recommendation: InstitutionRecommendation,
    batch: InstitutionRecommendationBatch,
) -> tuple[str, ...]:
    """Compose the immutable ``evidence_refs`` tuple for one proposal.

    Order is fixed so the proposal hash is stable across re-runs:
    the ``source_ref`` comes first, followed by the ``source_key``
    prefix so audit readers can disambiguate collisions between
    institutions reusing the same internal citation identifier.
    """

    return (
        f"institution.source_ref:{recommendation.source_ref}",
        f"institution.source_key:{batch.source_key}",
    )


def _recommendation_content_equal(
    left: InstitutionRecommendation,
    right: InstitutionRecommendation,
) -> bool:
    """Return ``True`` iff two recommendations carry identical content.

    The dedup key is ``(source_key, source_ref, symbol)``; when the
    same key appears twice, we only treat the duplicates as
    equivalent if every content field matches. Comparing on the
    dataclass directly would also work but the explicit per-field
    check keeps the contract obvious in unit tests.
    """

    return (
        left.symbol == right.symbol
        and left.source_ref == right.source_ref
        and left.recommendation_level == right.recommendation_level
        and left.confidence == right.confidence
        and left.original_score == right.original_score
        and left.original_scale == right.original_scale
        and left.reason_summary == right.reason_summary
    )


def _compute_input_hash(
    *,
    batch: InstitutionRecommendationBatch,
    allowed_source_keys: AbstractSet[str],
    as_of_datetime: datetime,
    symbol_to_instrument: Mapping[str, InstrumentId],
    universe_fingerprint: Sequence[Mapping[str, object]],
) -> str:
    """Stable hash of the entire channel input (plan §15 audit).

    The hash must cover every input that can flip the channel output:
    the batch payload, the source-key whitelist, the symbol→instrument
    mapping and (critically) the universe classifier's verdict for
    every instrument the channel considered. Without the universe
    fingerprint, a change in ``bars_by_instrument`` that moves an
    instrument from ``FULL`` to ``INELIGIBLE`` would leave
    ``input_hash`` byte-identical, violating the "channel input is
    auditable" guarantee in plan §15. The fingerprint is a frozen
    list of per-:class:`UniverseCandidate` payloads sorted by
    ``instrument_id`` so the hash is byte-stable regardless of the
    caller's input order.
    """

    def _normalise_universe_fingerprint(
        entries: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for entry in entries:
            instrument_id = entry["instrument_id"]
            uuid_value = (
                instrument_id.value
                if isinstance(instrument_id, InstrumentId)
                else instrument_id
            )
            latest_close = entry["latest_close"]
            if isinstance(latest_close, Decimal):
                latest_close_serialisable: str | None = _quantize(latest_close)
            else:
                latest_close_serialisable = latest_close
            rows.append(
                {
                    "can_enter_watch_only": bool(entry["can_enter_watch_only"]),
                    "eligibility": entry["eligibility"],
                    "exchange": entry["exchange"],
                    "history_days": int(entry["history_days"]),
                    "instrument_id": uuid_value,
                    "latest_close": latest_close_serialisable,
                    "latest_trade_date": entry["latest_trade_date"],
                    "reasons": sorted(entry["reasons"]),
                    "stale_days": entry["stale_days"],
                    "symbol": entry["symbol"],
                }
            )
        rows.sort(key=lambda item: str(item["instrument_id"]))
        return rows

    payload = {
        "as_of_datetime": as_of_datetime,
        "as_of_date": as_of_datetime.date(),
        "allowed_source_keys": sorted(allowed_source_keys),
        "batch": {
            "published_at": batch.published_at,
            "recommendations": sorted(
                (
                    {
                        "confidence": _quantize(rec.confidence),
                        "original_scale": rec.original_scale,
                        "original_score": (
                            _quantize(rec.original_score)
                            if rec.original_score is not None
                            else None
                        ),
                        "reason_summary": rec.reason_summary,
                        "recommendation_level": rec.recommendation_level.value,
                        "source_ref": rec.source_ref,
                        "symbol": rec.symbol,
                    }
                    for rec in batch.recommendations
                ),
                key=lambda item: (
                    item["symbol"],
                    item["source_ref"],
                    item["recommendation_level"],
                ),
            ),
            "source_key": batch.source_key,
            "valid_until": batch.valid_until,
        },
        "channel_key": INSTITUTIONAL_CHANNEL_KEY,
        "channel_version": INSTITUTIONAL_CHANNEL_VERSION,
        "symbol_to_instrument": sorted(
            (
                {"symbol": symbol, "instrument_id": instrument_id.value}
                for symbol, instrument_id in symbol_to_instrument.items()
            ),
            key=lambda item: item["symbol"],
        ),
        "universe_fingerprint": _normalise_universe_fingerprint(universe_fingerprint),
    }
    return content_hash(payload)


def _compute_output_hash(
    proposals: tuple[InstitutionalRecommendationProposal, ...],
    warnings: Iterable[str],
) -> str:
    """Stable hash of the channel output (plan §15 audit)."""

    payload = {
        "channel_key": INSTITUTIONAL_CHANNEL_KEY,
        "channel_version": INSTITUTIONAL_CHANNEL_VERSION,
        "proposals": [
            {
                "channel_key": proposal.channel_key,
                "channel_version": proposal.channel_version,
                "confidence": _quantize(proposal.confidence),
                "decision": proposal.decision,
                "evidence_refs": list(proposal.evidence_refs),
                "exchange": proposal.exchange,
                "instrument_id": proposal.instrument_id.value,
                "metadata": dict(proposal.metadata),
                "normalized_score": _quantize(proposal.normalized_score),
                "published_at": proposal.published_at,
                "reasons": list(proposal.reasons),
                "symbol": proposal.symbol,
                "valid_until": proposal.valid_until,
            }
            for proposal in proposals
        ],
        "warnings": sorted(warnings),
    }
    return content_hash(payload)


def _proposal_sort_key(
    proposal: InstitutionalRecommendationProposal,
) -> tuple[int, int, Decimal, bytes]:
    """Stable sort key matching the deterministic ordering spec.

    Order (ascending, lowest rank first):

    1. ``eligibility`` (FULL < PARTIAL < INELIGIBLE) — higher
       eligibility ranks first.
    2. ``decision`` (``include`` < ``watch`` < ``exclude`` <
       ``no_opinion``) — stronger decisions rank first so the
       strongest signals sit at the top of the list.
    3. ``-normalized_score`` (descending score → ascending negation)
       — so the channel puts the strongest institutional signal first
       within each eligibility / decision bucket.
    4. ``instrument_id.value.bytes`` — the ultimate deterministic
       tie-breaker mandated by plan §13.
    """

    return (
        _eligibility_rank(proposal.metadata.get("eligibility", "")),
        _decision_rank(proposal.decision),
        -proposal.normalized_score,
        proposal.instrument_id.value.bytes,
    )


def _eligibility_rank(value: object) -> int:
    rank = {
        UniverseEligibility.FULL.value: 0,
        UniverseEligibility.PARTIAL.value: 1,
        UniverseEligibility.INELIGIBLE.value: 2,
    }
    if not isinstance(value, str):
        return 99
    return rank.get(value, 99)


def _decision_rank(decision: str) -> int:
    if decision == InstitutionalDecision.INCLUDE.value:
        return 0
    if decision == InstitutionalDecision.WATCH.value:
        return 1
    if decision == InstitutionalDecision.EXCLUDE.value:
        return 2
    return 3


def _quantize(value: Decimal) -> Decimal:
    """Round to the channel quantum so identical scores stay identical."""

    return value.quantize(_SCORE_QUANTUM)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidInstitutionRecommendationBatchError(
            f"{field_name} must be timezone-aware (utc recommended); got naive {value.isoformat()}"
        )


def _require_finite_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal, got {value!s}")


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
    "DisallowedInstitutionSourceKeyError",
    "EXTERNAL_OPINION_MARKER",
    "INSTITUTIONAL_CHANNEL_KEY",
    "INSTITUTIONAL_CHANNEL_VERSION",
    "InstitutionChannelResultInvariantError",
    "InstitutionRecommendation",
    "InstitutionRecommendationBatch",
    "InstitutionalChannelError",
    "InstitutionalDecision",
    "InstitutionalRecommendationChannelResult",
    "InstitutionalRecommendationProposal",
    "InvalidInstitutionRecommendationBatchError",
    "InvalidInstitutionRecommendationError",
    "REASON_SUMMARY_MAX_LENGTH",
    "RECOMMENDATION_LEVEL_SCORES",
    "RecommendationLevel",
    "evaluate_institutional_recommendation_channel",
]
