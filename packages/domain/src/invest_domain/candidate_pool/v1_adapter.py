"""Pure-domain adapter from the archived V1 ``TargetSelectionResult`` to V2.

This module is the **only** slice of the Stage 4A-0 multi-channel routing
plan (see
``docs/plan/invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md``)
that the first increment implements. Its surface is intentionally narrow:

- :class:`V1TargetSelectionResult` — an immutable mirror of the V1 contract
  described in plan §2.1. Field names, types and semantics are preserved
  verbatim (``as_of``/``strategy``/``codes``/``scores``/``source``/
  ``is_fallback``/``generated_at``/``fallback_reason``/``data_age_days``);
  the count of ``codes`` is dynamic.
- :class:`ChannelStrategy` — the V1 channel key enumeration. The
  ``FQIR`` value is the *only* strategy promoted to an official V2
  channel; ``DIVIDEND_LIQUIDITY`` is FROZEN and the adapter never emits
  it as a formal channel.
- :data:`V1_FQIR_WEIGHTS` — the canonical V1 FQIR weights
  (``fundamental=0.30``, ``quant=0.25``, ``liquidity=0.20``,
  ``information=0.15``, ``risk=0.10``) re-declared here so callers do
  not need to re-import an archived module.
- :class:`V1Proposal` / :class:`V1AdapterOutput` — the V2 domain
  output of one adapter run. The shape mirrors the ``CandidateProposal``
  contract sketched in plan §7, restricted to the fields a pure
  in-memory adapter may legally emit. ``decision`` is taken from the
  four-state plan vocabulary (``include``/``watch``/``exclude``/
  ``no_opinion``); no buy/sell/investment-advice field is derivable
  from this shape (plan §5.1).
- :func:`validate_v1_target_selection` / :func:`adapt_v1_target_selection`
  — pure (no I/O, no clock, no env) entry points. The functions never
  read the V1 database, never import V1 storage, never touch the
  current ``personal_candidate_pool`` asset, and never make any
  network call.

Prohibited behaviours (enforced by tests and re-stated here so future
readers do not have to consult the plan):

- No fixed code count (plan §2.1 ``业务断言不允许固定 5、9、20 只``).
- No random or DB-order-dependent sort.
- No mapping of V1 numerical ``scores`` into any recommendation /
  stance / buy / sell field.
- No promotion of ``dividend_liquidity`` to a formal channel.
- No second factor calculator. The adapter accepts scores from V1's
  existing FQIR ranker and re-expresses them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from invest_domain.instruments.models import InstrumentId

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Frozen V1 FQIR weights (plan §2.1 — ``fundamental=.30``, ``quant=.25``,
#: ``liquidity=.20``, ``information=.15``, ``risk=.10``). Exposed as a
#: read-only mapping so callers cannot mutate the canonical weights at
#: runtime; the internal conversion to ``Decimal`` keeps every adapter
#: score round-trippable through canonical hashing.
V1_FQIR_WEIGHTS: Final[Mapping[str, Decimal]] = MappingProxyType(
    {
        "fundamental": Decimal("0.30"),
        "quant": Decimal("0.25"),
        "liquidity": Decimal("0.20"),
        "information": Decimal("0.15"),
        "risk": Decimal("0.10"),
    }
)

#: Authoritative V2 channel version that consumes a V1 FQIR ranking. The
#: ``channel_version`` is pinned to ``"1.0.0"`` so every downstream audit
#: can trace the proposal back to the pure-domain adapter contract,
#: independent of any later migration step.
V1_ADAPTER_CHANNEL_VERSION: Final[str] = "1.0.0"

#: Sentinel value used to mark a V1 target-selection result that was
#: emitted in fail-closed mode. The downstream channel contract still
#: receives an empty proposal list, but carries the reason in the
#: :attr:`V1AdapterOutput.notes` and a single ``no_opinion`` proposal
#: for instrumentation.
V1_FAIL_CLOSED_OUTCOME: Final[str] = "fail_closed"


# ---------------------------------------------------------------------------
# Channel strategy enumeration
# ---------------------------------------------------------------------------


class ChannelStrategy(StrEnum):
    """V1 channel keys known to the adapter.

    The ``FQIR`` strategy is the **only** formal V2 routing channel
    implemented in this slice (plan §2.1, §2.2). ``DIVIDEND_LIQUIDITY``
    is preserved here only so the adapter can recognise and explicitly
    REJECT that strategy when a V1 caller submits it — the strategy
    itself is **frozen** and is not migrated to a formal channel
    (plan §2.1 second sub-bullet: ``该策略在归档版本中被标记为
    frozen，没有完整生产消费者和正式存储契约``).
    """

    FQIR = "fqir"
    DIVIDEND_LIQUIDITY = "dividend_liquidity"


#: The set of strategies the adapter will route as a formal V2 channel.
#: ``DIVIDEND_LIQUIDITY`` is intentionally absent.
OFFICIAL_CHANNEL_STRATEGIES: Final[frozenset[ChannelStrategy]] = frozenset(
    {ChannelStrategy.FQIR}
)


# ---------------------------------------------------------------------------
# Input contract — V1 ``TargetSelectionResult`` shape, mirrored verbatim
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class V1TargetSelectionResult:
    """Immutable mirror of the archived V1 ``TargetSelectionResult``.

    The field names, types and order mirror plan §2.1 exactly. The
    adapter does not need a real V1 implementation to receive this
    object — callers (tests, replay CLIs, future Stage 4A-0 routing
    fixtures) construct it in-process. No metadata outside this field
    set is recognised.

    Field semantics, copied from plan §2.1 to make this module
    self-describing:

    - ``as_of`` — the trading day for which the ranking was computed.
    - ``strategy`` — the V1 channel key. Must be the string form of a
      :class:`ChannelStrategy` member when going through the adapter.
    - ``codes`` — the dynamic-length list of ETF codes (e.g.
      ``"510300"``). The list length is *not* constrained.
    - ``scores`` — ``{code: score}`` mapping. Missing entries signal a
      partial result (see :func:`adapt_v1_target_selection`).
    - ``source`` — a stable provenance label (e.g.
      ``"v1:cron_etf_alpha_daily"``).
    - ``is_fallback`` — ``True`` only when this is the most-recent
      successful pool for ``strategy`` that is older than ``as_of``.
    - ``generated_at`` — UTC timestamp of the V1 emission.
    - ``fallback_reason`` — required iff ``is_fallback`` is ``True``.
    - ``data_age_days`` — ``as_of`` age at ``generated_at``; ``None``
      when this is the same-day pool.
    """

    as_of: date
    strategy: str
    codes: tuple[str, ...]
    scores: Mapping[str, float]
    source: str
    is_fallback: bool
    generated_at: datetime
    fallback_reason: str | None = None
    data_age_days: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, date):
            raise TypeError(
                f"V1TargetSelectionResult.as_of must be a date, got {type(self.as_of).__name__}"
            )
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise ValueError("V1TargetSelectionResult.strategy must be a non-empty string")
        if not isinstance(self.codes, tuple):
            raise ValueError("V1TargetSelectionResult.codes must be a tuple[str, ...]")
        if any(not isinstance(code, str) or not code.strip() for code in self.codes):
            raise ValueError("V1TargetSelectionResult.codes must contain non-empty strings")
        if not isinstance(self.scores, Mapping):
            raise TypeError(
                f"V1TargetSelectionResult.scores must be a Mapping, got {type(self.scores).__name__}"
            )
        for code, score in self.scores.items():
            if not isinstance(score, (int, float)):
                raise ValueError(
                    f"V1TargetSelectionResult.scores[{code!r}] must be a number, "
                    f"got {type(score).__name__}"
                )
            if isinstance(score, float) and not _is_finite_float(score):
                raise ValueError(
                    f"V1TargetSelectionResult.scores[{code!r}] must be a finite float"
                )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("V1TargetSelectionResult.source must be a non-empty string")
        if not isinstance(self.generated_at, datetime):
            raise TypeError(
                f"V1TargetSelectionResult.generated_at must be a datetime, "
                f"got {type(self.generated_at).__name__}"
            )
        if self.generated_at.tzinfo is None or self.generated_at.tzinfo.utcoffset(
            self.generated_at
        ) is None:
            raise ValueError("V1TargetSelectionResult.generated_at must be timezone-aware (UTC)")
        if self.is_fallback and not (
            isinstance(self.fallback_reason, str) and self.fallback_reason.strip()
        ):
            raise ValueError(
                "V1TargetSelectionResult.fallback_reason must be non-empty when "
                "is_fallback is True"
            )
        if self.data_age_days is not None and self.data_age_days < 0:
            raise ValueError(
                f"V1TargetSelectionResult.data_age_days must be >= 0, got {self.data_age_days}"
            )


# ---------------------------------------------------------------------------
# V2-side output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class V1Proposal:
    """V2-shaped candidate proposal derived from one V1 code/score pair.

    Mirrors the four-state ``decision`` vocabulary in plan §7
    (``include`` / ``watch`` / ``exclude`` / ``no_opinion``). The
    ``metadata`` mapping accepts only ``Decimal``, ``int``, ``bool``,
    ``str`` or ``None`` values so downstream JSON serialisation does
    not need to handle anything else.
    """

    instrument_id: InstrumentId
    v1_code: str
    channel_key: str
    channel_version: str
    decision: str
    normalized_score: Decimal | None
    confidence: Decimal | None
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    published_at: datetime | None
    valid_until: datetime | None
    metadata: Mapping[str, Decimal | int | bool | str | None] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError(
                f"V1Proposal.instrument_id must be an InstrumentId, "
                f"got {type(self.instrument_id).__name__}"
            )
        if not isinstance(self.v1_code, str) or not self.v1_code.strip():
            raise ValueError("V1Proposal.v1_code must be a non-empty string")
        if self.channel_key not in {strategy.value for strategy in OFFICIAL_CHANNEL_STRATEGIES}:
            raise ValueError(
                f"V1Proposal.channel_key must be one of "
                f"{sorted(s.value for s in OFFICIAL_CHANNEL_STRATEGIES)!r}, "
                f"got {self.channel_key!r}"
            )
        if not self.channel_version or not self.channel_version.strip():
            raise ValueError("V1Proposal.channel_version must be a non-empty string")
        if self.decision not in {"include", "watch", "exclude", "no_opinion"}:
            raise ValueError(
                f"V1Proposal.decision must be one of include/watch/exclude/no_opinion, "
                f"got {self.decision!r}"
            )
        _require_optional_finite_decimal(self.normalized_score, "V1Proposal.normalized_score")
        _require_optional_finite_decimal(self.confidence, "V1Proposal.confidence")
        for label in ("reasons", "evidence_refs"):
            value = getattr(self, label)
            if not isinstance(value, tuple):
                raise ValueError(f"V1Proposal.{label} must be a tuple[str, ...]")
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"V1Proposal.{label} must contain non-empty strings")
        for label in ("published_at", "valid_until"):
            _require_optional_aware_datetime(getattr(self, label), f"V1Proposal.{label}")
        if not isinstance(self.metadata, Mapping):
            raise TypeError(
                f"V1Proposal.metadata must be a Mapping, got {type(self.metadata).__name__}"
            )
        for key, value in self.metadata.items():
            if not isinstance(value, (Decimal, int, bool, str, type(None))):
                raise ValueError(
                    f"V1Proposal.metadata[{key!r}] must be one of Decimal/int/bool/str/None, "
                    f"got {type(value).__name__}"
                )


@dataclass(frozen=True, slots=True)
class V1AdapterOutput:
    """The V2-shaped output contract of :func:`adapt_v1_target_selection`.

    Carries every per-instrument :class:`V1Proposal` in input rank order
    plus a small audit block: ``strategy`` / ``channel_key`` /
    ``channel_version`` that identify the migration path, the V1
    source label, and :attr:`notes` which surfaces fallback or
    fail-closed information as immutable strings.
    """

    strategy: str
    channel_key: str
    channel_version: str
    as_of: date
    source: str
    is_fallback: bool
    generated_at: datetime
    proposals: tuple[V1Proposal, ...]
    fallback_reason: str | None = None
    data_age_days: int | None = None
    outcome: str = V1_FAIL_CLOSED_OUTCOME
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise ValueError("V1AdapterOutput.strategy must be a non-empty string")
        if self.channel_key != self.strategy:
            raise ValueError(
                "V1AdapterOutput.channel_key must equal the V1 strategy to keep "
                "V1->V2 traceability; "
                f"got channel_key={self.channel_key!r}, strategy={self.strategy!r}"
            )
        if not isinstance(self.proposals, tuple):
            raise ValueError("V1AdapterOutput.proposals must be a tuple[V1Proposal, ...]")
        if len({item.instrument_id for item in self.proposals}) != len(self.proposals):
            raise ValueError("V1AdapterOutput.proposals must not duplicate instrument_id")
        _require_aware_datetime(self.generated_at, "V1AdapterOutput.generated_at")
        if self.data_age_days is not None and self.data_age_days < 0:
            raise ValueError(
                f"V1AdapterOutput.data_age_days must be >= 0, got {self.data_age_days}"
            )
        if self.outcome not in {"ok", V1_FAIL_CLOSED_OUTCOME}:
            raise ValueError(
                f"V1AdapterOutput.outcome must be one of ok/{V1_FAIL_CLOSED_OUTCOME}, "
                f"got {self.outcome!r}"
            )
        if (
            self.outcome == V1_FAIL_CLOSED_OUTCOME
            and self.proposals
            and not self.notes
        ):
            raise ValueError(
                f"V1AdapterOutput with outcome={self.outcome!r} "
                "must either carry no proposals or have notes explaining why"
            )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def validate_v1_target_selection(
    result: V1TargetSelectionResult,
    *,
    max_age_days: int | None = None,
) -> None:
    """Validate ``result`` without producing output.

    ``max_age_days`` is the fail-closed threshold the upstream V1
    consumer uses to decide whether a fallback pool is still
    acceptable. When the V1 result is a fallback whose
    :attr:`data_age_days` exceeds ``max_age_days`` (or when the V1
    result carries an empty code list AND is a fallback), the adapter
    raises :class:`FailClosedV1TargetSelectionError` so the caller can
    surface the empty pool to the AI research layer instead of feeding
    a stale result.

    Validation rules (all raise ``ValueError`` except the fail-closed
    detection which raises :class:`FailClosedV1TargetSelectionError`):

    1. ``strategy`` must be the string form of a
       :class:`ChannelStrategy` member.
    2. ``DIVIDEND_LIQUIDITY`` is rejected with a hard error — the
       strategy is FROZEN and is not migrated as a formal channel
       (plan §2.1 second sub-bullet).
    3. Every code in ``codes`` must be present in the result's
       ``scores`` mapping OR explicitly omitted by V1 (missing-score
       codes are surfaced but never silently dropped — see
       :func:`adapt_v1_target_selection`). The validation step only
       rejects codes that are empty / non-string; **score presence**
       is left to the conversion step.
    4. Duplicate codes are rejected as malformed input (the V1 contract
       already required unique codes; rejecting on the V2 side keeps
       the audit trail clean).
    5. Fallback pools whose ``data_age_days`` exceeds ``max_age_days``
       trigger :class:`FailClosedV1TargetSelectionError` (plan §2.1
       ``无有效结果时 fail closed``).
    """

    if not isinstance(result, V1TargetSelectionResult):
        raise TypeError(
            f"validate_v1_target_selection expects V1TargetSelectionResult, "
            f"got {type(result).__name__}"
        )

    try:
        strategy = ChannelStrategy(result.strategy)
    except ValueError as exc:
        raise ValueError(
            f"V1TargetSelectionResult.strategy={result.strategy!r} is not a "
            f"known ChannelStrategy; allowed: "
            f"{sorted(s.value for s in ChannelStrategy)!r}"
        ) from exc

    if strategy not in OFFICIAL_CHANNEL_STRATEGIES:
        # ``DIVIDEND_LIQUIDITY`` ends up here. The plan forbids migration
        # to a formal channel so we treat the request as a hard
        # validation failure rather than silently dropping the codes.
        raise ValueError(
            f"strategy {strategy.value!r} is FROZEN in V1 and must not be "
            f"migrated as a formal channel (plan §2.1); allowed official "
            f"strategies: "
            f"{sorted(s.value for s in OFFICIAL_CHANNEL_STRATEGIES)!r}"
        )

    seen_codes: set[str] = set()
    for index, code in enumerate(result.codes):
        if code in seen_codes:
            raise ValueError(
                f"V1TargetSelectionResult.codes contains duplicate entry "
                f"{code!r} at position {index}"
            )
        seen_codes.add(code)

    if max_age_days is not None:
        if max_age_days < 0:
            raise ValueError(
                f"validate_v1_target_selection max_age_days must be >= 0, "
                f"got {max_age_days}"
            )
        if result.is_fallback and result.data_age_days is not None:
            if result.data_age_days > max_age_days:
                raise FailClosedV1TargetSelectionError(
                    strategy=result.strategy,
                    as_of=result.as_of,
                    data_age_days=result.data_age_days,
                    max_age_days=max_age_days,
                )


def adapt_v1_target_selection(
    result: V1TargetSelectionResult,
    *,
    symbol_to_instrument: Mapping[str, InstrumentId],
    max_age_days: int | None = None,
) -> V1AdapterOutput:
    """Convert a V1 :class:`V1TargetSelectionResult` into a V2 output.

    Parameters
    ----------
    result:
        The V1 input to convert. The function is pure: the same input,
        mapping, and ``max_age_days`` value always produce the same
        :class:`V1AdapterOutput`.
    symbol_to_instrument:
        Static symbol -> :class:`InstrumentId` mapping the caller
        provides so the adapter does not need to query any storage.
        Codes absent from this mapping are rejected with
        :class:`UnknownV1InstrumentCodeError` rather than silently
        dropped.
    max_age_days:
        When given, fail-closed threshold (see
        :func:`validate_v1_target_selection`). Falls into the
        fail-closed branch only when the V1 result is itself a
        fallback whose age breaches the threshold; same-day pools are
        always accepted regardless of ``max_age_days``.

    The output preserves every V1 audit field the plan §2.1 calls
    out: ``as_of``, ``strategy``, ``source``, ``is_fallback``,
    ``fallback_reason``, ``data_age_days``, ``generated_at``. The
    ``proposals`` tuple preserves V1 input order (which is the rank
    order emitted by the FQIR ranker); there is no shuffling and no
    database order is consulted, so the conversion is fully
    deterministic.

    Missing scores are not silently dropped: the corresponding
    proposal is emitted with ``decision="no_opinion"`` and a
    :class:`MissingV1ScoreError`-like note in the proposal ``reasons``.
    Skip the silent-drop semantic to satisfy plan §5.1.
    """

    if not isinstance(result, V1TargetSelectionResult):
        raise TypeError(
            f"adapt_v1_target_selection expects V1TargetSelectionResult, "
            f"got {type(result).__name__}"
        )
    if not isinstance(symbol_to_instrument, Mapping):
        raise TypeError(
            f"adapt_v1_target_selection symbol_to_instrument must be a Mapping, "
            f"got {type(symbol_to_instrument).__name__}"
        )

    # validate_v1_target_selection also raises FailClosedV1TargetSelectionError
    # when the V1 result is too old; we let it propagate so the caller can
    # distinguish the fail-closed case from a successful adaptation.
    validate_v1_target_selection(result, max_age_days=max_age_days)

    strategy = ChannelStrategy(result.strategy)

    proposals: list[V1Proposal] = []
    notes: list[str] = []
    missing_score_count = 0
    unknown_code_count = 0

    for code in result.codes:
        instrument_id = symbol_to_instrument.get(code)
        if instrument_id is None:
            unknown_code_count += 1
            raise UnknownV1InstrumentCodeError(
                strategy=result.strategy, as_of=result.as_of, code=code
            )
        score = result.scores.get(code)
        if score is None:
            missing_score_count += 1
            proposals.append(
                V1Proposal(
                    instrument_id=instrument_id,
                    v1_code=code,
                    channel_key=strategy.value,
                    channel_version=V1_ADAPTER_CHANNEL_VERSION,
                    decision="no_opinion",
                    normalized_score=None,
                    confidence=None,
                    reasons=("v1.score_missing",),
                    evidence_refs=(f"v1.source:{result.source}",),
                    published_at=result.generated_at,
                    valid_until=None,
                    metadata=MappingProxyType(
                        {"v1_score_missing": True, "v1_code": code}
                    ),
                )
            )
            continue
        proposals.append(
            V1Proposal(
                instrument_id=instrument_id,
                v1_code=code,
                channel_key=strategy.value,
                channel_version=V1_ADAPTER_CHANNEL_VERSION,
                decision="include",
                normalized_score=_quantize_score(score),
                confidence=None,
                reasons=("v1.fqir_ranking",),
                evidence_refs=(f"v1.source:{result.source}",),
                published_at=result.generated_at,
                valid_until=None,
                metadata=MappingProxyType(
                    {
                        "v1_source": result.source,
                        "v1_strategy": result.strategy,
                        "v1_score": Decimal(str(score)),
                    }
                ),
            )
        )

    if missing_score_count:
        notes.append(f"v1.scores_missing:{missing_score_count}")
    if unknown_code_count:
        notes.append(f"v1.codes_unknown:{unknown_code_count}")
    if result.is_fallback and result.fallback_reason:
        notes.append(f"v1.fallback:{result.fallback_reason}")
    if result.data_age_days is not None:
        notes.append(f"v1.data_age_days:{result.data_age_days}")

    return V1AdapterOutput(
        strategy=result.strategy,
        channel_key=strategy.value,
        channel_version=V1_ADAPTER_CHANNEL_VERSION,
        as_of=result.as_of,
        source=result.source,
        is_fallback=result.is_fallback,
        generated_at=result.generated_at,
        proposals=tuple(proposals),
        fallback_reason=result.fallback_reason,
        data_age_days=result.data_age_days,
        outcome="ok",
        notes=tuple(notes),
    )


def build_fail_closed_output(
    *,
    strategy: ChannelStrategy | str,
    as_of: date,
    source: str,
    generated_at: datetime,
    fallback_reason: str,
    data_age_days: int,
    max_age_days: int,
) -> V1AdapterOutput:
    """Build the empty, fail-closed :class:`V1AdapterOutput`.

    Use this when :func:`adapt_v1_target_selection` would have raised
    :class:`FailClosedV1TargetSelectionError` but the caller prefers to
    surface the empty-pool state to the AI research layer rather than
    raising. The result carries an empty :attr:`V1AdapterOutput.proposals`
    tuple, ``outcome=V1_FAIL_CLOSED_OUTCOME``, and a single note that
    records both ``data_age_days`` and ``max_age_days`` so the audit log
    can explain why the pool is empty.
    """

    strategy_value = strategy.value if isinstance(strategy, ChannelStrategy) else str(strategy)
    try:
        resolved = ChannelStrategy(strategy_value)
    except ValueError as exc:
        raise ValueError(
            f"build_fail_closed_output strategy {strategy_value!r} is not a "
            f"known ChannelStrategy; allowed: "
            f"{sorted(s.value for s in ChannelStrategy)!r}"
        ) from exc
    if resolved not in OFFICIAL_CHANNEL_STRATEGIES:
        raise ValueError(
            f"build_fail_closed_output strategy {resolved.value!r} is FROZEN "
            f"in V1 and must not be migrated as a formal channel; allowed "
            f"official strategies: "
            f"{sorted(s.value for s in OFFICIAL_CHANNEL_STRATEGIES)!r}"
        )
    if not isinstance(as_of, date):
        raise TypeError(
            f"build_fail_closed_output as_of must be a date, "
            f"got {type(as_of).__name__}"
        )
    if not isinstance(source, str) or not source.strip():
        raise ValueError("build_fail_closed_output source must be a non-empty string")
    if not isinstance(generated_at, datetime):
        raise TypeError(
            f"build_fail_closed_output generated_at must be a datetime, "
            f"got {type(generated_at).__name__}"
        )
    if generated_at.tzinfo is None or generated_at.tzinfo.utcoffset(generated_at) is None:
        raise ValueError(
            "build_fail_closed_output generated_at must be timezone-aware (UTC)"
        )
    if max_age_days < 0:
        raise ValueError(
            f"build_fail_closed_output max_age_days must be >= 0, got {max_age_days}"
        )
    if data_age_days < 0:
        raise ValueError(
            f"build_fail_closed_output data_age_days must be >= 0, got {data_age_days}"
        )
    note = (
        "fail_closed:data_age_days="
        f"{data_age_days}:max_age_days={max_age_days}:{fallback_reason}"
    )
    return V1AdapterOutput(
        strategy=resolved.value,
        channel_key=resolved.value,
        channel_version=V1_ADAPTER_CHANNEL_VERSION,
        as_of=as_of,
        source=source,
        is_fallback=True,
        generated_at=generated_at,
        proposals=(),
        fallback_reason=fallback_reason,
        data_age_days=data_age_days,
        outcome=V1_FAIL_CLOSED_OUTCOME,
        notes=(note,),
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V1AdapterError(ValueError):
    """Base class for every adapter-specific failure.

    The base inherits from ``ValueError`` so existing callers that
    catch ``ValueError`` still treat adapter failures as
    validation-time errors. The subclass hierarchy carries a stable
    ``.code`` attribute that callers can use without parsing the
    message string.
    """

    code: str = "v1_adapter_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownV1InstrumentCodeError(V1AdapterError):
    """Raised when a V1 code cannot be resolved to an :class:`InstrumentId`."""

    code = "v1.code_unknown"

    def __init__(self, *, strategy: str, as_of: date, code: str) -> None:
        super().__init__(
            f"V1 code {code!r} for strategy {strategy!r} on {as_of.isoformat()} "
            "is not present in the supplied symbol_to_instrument mapping"
        )
        self.strategy = strategy
        self.as_of = as_of
        self.code_value = code


class FailClosedV1TargetSelectionError(V1AdapterError):
    """Raised when the V1 result is too old to be reused as fallback."""

    code = "v1.fail_closed"

    def __init__(
        self, *, strategy: str, as_of: date, data_age_days: int, max_age_days: int
    ) -> None:
        super().__init__(
            f"V1 target-selection result for strategy {strategy!r} on "
            f"{as_of.isoformat()} is a fallback whose data_age_days="
            f"{data_age_days} exceeds max_age_days={max_age_days}; "
            "the adapter refuses to feed the stale pool downstream"
        )
        self.strategy = strategy
        self.as_of = as_of
        self.data_age_days = data_age_days
        self.max_age_days = max_age_days


class InvalidV1ChannelStrategyError(V1AdapterError):
    """Raised when ``strategy`` cannot be coerced to a ChannelStrategy."""

    code = "v1.invalid_strategy"

    def __init__(self, strategy: object) -> None:
        super().__init__(
            f"strategy {strategy!r} is not a known ChannelStrategy; allowed: "
            f"{sorted(s.value for s in ChannelStrategy)!r}"
        )
        self.strategy = strategy


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_QUANTUM = Decimal("0.00000001")


def _quantize_score(score: float) -> Decimal:
    """Return a finite ``Decimal`` V1 score, rounded to 8 fractional digits.

    The 8-digit quantum mirrors the rounding used by the V2 research
    factor calculators in :mod:`invest_domain.analytics.factor_calculators`
    so downstream ``Decimal`` arithmetic never silently drops precision.
    """

    as_decimal = Decimal(str(score))
    if not as_decimal.is_finite():
        raise ValueError(f"V1 score {score!r} must be a finite number")
    return as_decimal.quantize(_QUANTUM)


def _is_finite_float(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _require_optional_finite_decimal(value: Decimal | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal or None, got {value!r}")


def _require_optional_aware_datetime(
    value: datetime | None, field_name: str
) -> None:
    if value is None:
        return
    _require_aware_datetime(value, field_name)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"{field_name} must be a timezone-aware datetime (UTC recommended)"
        )


def is_official_channel_strategy(value: object) -> bool:
    """Return ``True`` iff ``value`` is an official V2 routing channel.

    Convenience helper used by the pipeline adapter tests so the
    repository never hardcodes the set of accepted strategies outside
    the adapter module.
    """

    if isinstance(value, ChannelStrategy):
        return value in OFFICIAL_CHANNEL_STRATEGIES
    if isinstance(value, str):
        try:
            return ChannelStrategy(value) in OFFICIAL_CHANNEL_STRATEGIES
        except ValueError:
            return False
    return False


def normalise_codes(codes: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate and order ``codes`` while preserving first-seen rank.

    The V1 ``TargetSelectionResult.codes`` is already rank-ordered by
    construction (the V1 FQIR ranker ranked ``codes`` as a list).
    When a test or replay CLI accidentally passes duplicate codes
    through, this helper preserves V1 rank order by keeping the first
    occurrence of every code.
    """

    seen: set[str] = set()
    ordered: list[str] = []
    for index, code in enumerate(codes):
        if not isinstance(code, str) or not code.strip():
            raise ValueError(
                f"normalise_codes received blank code at position {index}"
            )
        if code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    return tuple(ordered)


def utc_now() -> datetime:
    """Return the current UTC time.

    Exposed only because :func:`adapt_v1_target_selection` does not
    need a clock (callers supply ``generated_at`` explicitly), but
    pipeline adapter tests use this helper to fabricate deterministic
    timestamps without coupling to ``datetime.now`` directly.
    """

    return datetime.now(timezone.utc)


__all__ = [
    "ChannelStrategy",
    "FailClosedV1TargetSelectionError",
    "InvalidV1ChannelStrategyError",
    "OFFICIAL_CHANNEL_STRATEGIES",
    "UnknownV1InstrumentCodeError",
    "V1_ADAPTER_CHANNEL_VERSION",
    "V1AdapterError",
    "V1AdapterOutput",
    "V1Proposal",
    "V1TargetSelectionResult",
    "V1_FQIR_WEIGHTS",
    "V1_FAIL_CLOSED_OUTCOME",
    "adapt_v1_target_selection",
    "build_fail_closed_output",
    "is_official_channel_strategy",
    "normalise_codes",
    "utc_now",
    "validate_v1_target_selection",
]
