"""Profile Resolver for the ``etf_profile`` bounded context (``PR-ETF-PROFILE-03``).

The Profile Resolver is the third stage of the ETF Profile Evidence
Framework pipeline:

```
Provider Raw Evidence  ->  Field Evidence  ->  Profile Resolver  ->  EtfProfile
```

It takes one or more :class:`~invest_domain.etf_profile.models.FieldEvidence`
rows for a single instrument, groups them by ``field_key`` and emits a
:class:`ProfileResolution` describing the *current best* value for each
field together with the full audit chain that supports it.

Public contract
---------------

The module exposes four pure-domain value types:

- :class:`ResolutionStatus` — closed-set vocabulary of audit outcomes
  (``RESOLVED`` / ``MISSING`` / ``CONFLICT``).
- :class:`ProviderPriorityPolicy` — audit-friendly provider-tier
  ordering for the prioritised fields (``manager`` / ``benchmark_index``
  / ``aum``). Fields outside the explicit table fall back to a stable
  alphabetical provider_key order so the resolver remains fully
  deterministic even without a configured mapping.
- :class:`ResolvedField` — one resolved field. Carries the resolved
  value (or ``None``), the selected evidence row (or ``None``), the
  full candidate list (every row that contributed) and any conflict
  rows when the resolver refuses to overwrite.
- :class:`ProfileResolution` — aggregation of one
  :class:`ResolvedField` per ``FieldKey`` observed in the input plus
  an overall :class:`ResolutionStatus`.

The behaviour pinned by ``PR-ETF-PROFILE-03``:

- The resolver never aliases :class:`~invest_domain.etf_profile.models.
  FieldKey`.``AUM`` with ``MARKET_VALUE`` or ``TURNOVER_VALUE`` (plan
  §6). Evidence rows target a single ``field_key``; market / turnover
  value evidence never feeds the AUM slot.
- The resolver never silently overwrites conflicting observations
  (plan §5): when two evidence rows carry distinct non-None values for
  the same field, the resolution becomes :attr:`ResolutionStatus.CONFLICT`
  with the offending rows preserved in :attr:`ResolvedField.conflicts`
  and ``value=None``.
- Agreement on a single value with multiple providers is resolved by
  priority; the highest-priority row becomes :attr:`ResolvedField.
  selected_evidence` and lower-priority rows remain candidates. Ties
  are broken deterministically by ``observed_at`` then ``content_hash``.
- All dataclasses in this module are ``frozen=True`` + ``slots=True``;
  the resolver is reusable across instruments but cannot be mutated.

The module is pure-domain: no Provider adapter, no Storage, no clock,
no RNG, no environment access.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from invest_domain.etf_profile.models import (
    FieldEvidence,
    FieldKey,
)

__all__ = [
    "DEFAULT_PROVIDER_PRIORITY_POLICY",
    "ProfileResolution",
    "ProfileResolver",
    "ProviderPriorityPolicy",
    "ResolutionPolicyError",
    "ResolutionStatus",
    "ResolvedField",
    "resolve_etf_profile_evidence",
]


_DATETIME_MAX_AWARE: datetime = datetime.max.replace(tzinfo=UTC)


class ResolutionPolicyError(ValueError):
    """Raised when the resolver input violates the resolver's preconditions.

    The resolver expects all evidence rows in a single call to belong
    to the same instrument. A mixed-instrument input is an
    unrecoverable audit failure and cannot be reconciled by the
    resolver; the application layer must partition the input before
    calling ``resolve(...)``.
    """


class ResolutionStatus(StrEnum):
    """Audit outcome of one ``ResolvedField``.

    - :attr:`RESOLVED` — exactly one non-None value survived; the row
      with the highest priority drives :attr:`ResolvedField.value`.
    - :attr:`MISSING` — no row supplied a non-None value, or no row
      was supplied at all. ``value`` is ``None``; the resolver
      deliberately fills nothing.
    - :attr:`CONFLICT` — two or more rows supplied distinct non-None
      values for the field. The resolver refuses to pick a winner
      (plan §5 — "禁止覆盖"). ``value`` is ``None``; the offending
      rows are preserved verbatim in
      :attr:`ResolvedField.conflicts`.
    """

    RESOLVED = "resolved"
    MISSING = "missing"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ProviderPriorityPolicy:
    """Audit-friendly provider tier ordering for the prioritised fields.

    The default ``DEFAULT_PROVIDER_PRIORITY_POLICY`` carves out the
    three fields the plan §5 names explicitly:

    - ``manager`` ::
        fund_announcement > fund_official > exchange > third_party
    - ``benchmark_index`` ::
        fund_announcement > index_provider > fund_official > third_party
    - ``aum`` ::
        fund_announcement > fund_official > third_party

    Other :class:`~invest_domain.etf_profile.models.FieldKey` members
    are not in the explicit table; the resolver falls back to a
    *stable* conservative rule — alphabetical provider_key order —
    so the result remains fully deterministic even without a
    configured mapping.

    Construction rules:

    - All keys must be :class:`~invest_domain.etf_profile.models.
      FieldKey` instances. ``str`` keys are rejected because the
      vocabulary is closed-set.
    - All provider_keys must be non-empty strings. Empty entries are
      rejected because they would never match any
      :class:`~invest_domain.etf_profile.models.FieldEvidenceSource`.
    - Provider_key duplicates inside a single tier are rejected so the
      priority rank is unambiguous.
    """

    priorities: Mapping[FieldKey, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        frozen: dict[FieldKey, tuple[str, ...]] = {}
        for key, value in self.priorities.items():
            if not isinstance(key, FieldKey):
                raise TypeError(
                    "ProviderPriorityPolicy.priorities keys must be FieldKey, "
                    f"got {type(key).__name__}"
                )
            if isinstance(value, bool) or not isinstance(value, (tuple, list)):
                raise TypeError(
                    "ProviderPriorityPolicy.priorities values must be a tuple "
                    f"or list of str, got {type(value).__name__}"
                )
            seen: set[str] = set()
            normalised: list[str] = []
            for provider_key in value:
                if (
                    not isinstance(provider_key, str)
                    or isinstance(provider_key, bool)
                ):
                    raise TypeError(
                        "ProviderPriorityPolicy provider_key must be a str, "
                        f"got {type(provider_key).__name__}"
                    )
                if not provider_key.strip():
                    raise ValueError(
                        "ProviderPriorityPolicy provider_key must not be empty"
                    )
                if provider_key in seen:
                    raise ValueError(
                        "ProviderPriorityPolicy duplicate provider_key: "
                        f"{provider_key!r}"
                    )
                seen.add(provider_key)
                normalised.append(provider_key)
            frozen[key] = tuple(normalised)
        object.__setattr__(
            self,
            "priorities",
            MappingProxyType(frozen),
        )

    @classmethod
    def from_dict(
        cls, priorities: Mapping[FieldKey, Sequence[str]]
    ) -> ProviderPriorityPolicy:
        """Build a policy from a plain ``dict`` (or any mutable mapping)."""

        return cls(priorities=dict(priorities))

    def priority_for(self, field_key: FieldKey) -> tuple[str, ...]:
        """Return the priority tuple for ``field_key`` or ``()`` if absent.

        ``()`` is the explicit carrier for "no explicit priority" and
        tells the resolver to apply the stable alphabetical fallback
        rule for this field.
        """

        return self.priorities.get(field_key, ())

    def keys(self) -> Iterable[FieldKey]:
        """Return the FieldKeys for which the policy has an explicit priority."""

        return tuple(self.priorities.keys())


def _default_priority_table() -> Mapping[FieldKey, tuple[str, ...]]:
    """Build the immutable default priority table.

    The categories follow the plan §5 ordering, expressed as opaque
    provider_key strings so the policy is fully machine-readable.
    """

    return MappingProxyType(
        {
            FieldKey.MANAGER: (
                "fund_announcement",
                "fund_official",
                "exchange",
                "third_party",
            ),
            FieldKey.BENCHMARK_INDEX: (
                "fund_announcement",
                "index_provider",
                "fund_official",
                "third_party",
            ),
            FieldKey.AUM: (
                "fund_announcement",
                "fund_official",
                "third_party",
            ),
        }
    )


DEFAULT_PROVIDER_PRIORITY_POLICY: Final[ProviderPriorityPolicy] = (
    ProviderPriorityPolicy(priorities=_default_priority_table())
)


def _provider_rank(
    provider_key: str,
    priority_for_field: tuple[str, ...],
) -> tuple[int, int | str, str]:
    """Return the (priority_kind, priority_value, provider_key) sort key.

    Sort lower to win. The tuple structure is:

    - ``(0, idx, provider_key)`` — known provider_key, ordered by its
      position in the explicit priority tuple (``idx`` ascending;
      smaller index means higher priority).
    - ``(1, provider_key, provider_key)`` — unknown provider_key, ordered
      by provider_key ascending. This is the "stable conservative rule"
      applied when no explicit mapping exists or when a provider_key is
      outside the configured tiers.

    ``provider_key`` is repeated at index ``2`` so two rows from the
    same priority bucket break ties deterministically by their
    provider_key alphabetical order.
    """

    if provider_key in priority_for_field:
        return (0, priority_for_field.index(provider_key), provider_key)
    return (1, provider_key, provider_key)


def _observed_at_ascending_key(observed_at: datetime) -> tuple[float, int]:
    """Sort key that puts later observations *first* (descending order).

    ``datetime.max - observed_at`` is the canonical gap; the gap is
    smaller for later observations, so ascending sort by the gap
    directly puts later observations first.

    Microseconds are folded in via the timedelta ``.microseconds``
    attribute so two observations on the same wall-clock second still
    produce a fully deterministic order.
    """

    delta = _DATETIME_MAX_AWARE - observed_at
    return (delta.total_seconds(), delta.microseconds)


def _evidence_sort_key(
    evidence: FieldEvidence,
    priority_for_field: tuple[str, ...],
) -> tuple[Any, ...]:
    """Composite deterministic sort key for one evidence row.

    Order of preference (lowest sort wins):

    1. Provider tier rank (explicit priority beats alphabetical fallback).
    2. Within the same tier, prefer the alphabetically earlier
       provider_key.
    3. Within the same provider_key, prefer the most recent observation.
    4. Within the same observation timestamp, prefer the lower
       ``content_hash`` so two calls over identical input produce the
       same winner.
    """

    rank = _provider_rank(evidence.source.provider_key, priority_for_field)
    return (
        rank,
        *_observed_at_ascending_key(evidence.source.observed_at),
        evidence.content_hash,
    )


def _distinct_values(values: Iterable[Any]) -> tuple[Any, ...]:
    """Return the distinct values of ``values`` in first-occurrence order.

    Distinctness uses Python's ``==`` / ``!=`` semantics so the same
    ``Decimal`` representations collapse even when written with
    different scales, and ``str`` values collapse after the
    whitespace stripping the ``FieldEvidence`` constructor enforces.
    """

    seen: list[Any] = []
    seen_set: set[Any] = set()
    for value in values:
        marker = (type(value), value) if value is not None else ("__none__", None)
        if marker in seen_set:
            continue
        seen_set.add(marker)
        seen.append(value)
    return tuple(seen)


def _select_best(
    rows: Sequence[FieldEvidence],
    priority_for_field: tuple[str, ...],
) -> FieldEvidence:
    """Pick the best evidence row by priority + deterministic tie-breakers."""

    return min(
        rows,
        key=lambda evidence: _evidence_sort_key(evidence, priority_for_field),
    )


def _resolve_field(
    field_key: FieldKey,
    rows: Sequence[FieldEvidence],
    priority_for_field: tuple[str, ...],
) -> ResolvedField:
    """Resolve one ``FieldKey`` group into a ``ResolvedField``.

    The candidate list passed to :class:`ResolvedField` is the full
    input sequence (audit chain). The ``conflicts`` attribute is
    populated only when multiple distinct non-None values are observed
    for the field; rows whose value is ``None`` are candidates but
    never offenders.
    """

    if not rows:
        return ResolvedField(
            field_key=field_key,
            status=ResolutionStatus.MISSING,
            value=None,
            candidates=(),
            selected_evidence=None,
            conflicts=(),
            observed_distinct_values=(),
        )

    if len(rows) == 1 and rows[0].value is None:
        # Single ``None``-valued row (typically ``QualityStatus.
        # MISSING``) carries no observable value.
        return ResolvedField(
            field_key=field_key,
            status=ResolutionStatus.MISSING,
            value=None,
            candidates=(),
            selected_evidence=None,
            conflicts=(),
            observed_distinct_values=(),
        )

    non_null_rows = [row for row in rows if row.value is not None]
    distinct_values = _distinct_values(row.value for row in non_null_rows)

    if not distinct_values:
        # Every supplied row had a ``None`` value; nothing to resolve.
        return ResolvedField(
            field_key=field_key,
            status=ResolutionStatus.MISSING,
            value=None,
            candidates=(),
            selected_evidence=None,
            conflicts=(),
            observed_distinct_values=(),
        )

    if len(distinct_values) >= 2:
        # Plan §5: "禁止覆盖"; multiple distinct values => conflict.
        return ResolvedField(
            field_key=field_key,
            status=ResolutionStatus.CONFLICT,
            value=None,
            candidates=tuple(rows),
            selected_evidence=None,
            conflicts=tuple(non_null_rows),
            observed_distinct_values=distinct_values,
        )

    # Exactly one distinct value. Pick the best evidence row among those
    # carrying that value.
    matching_rows = [row for row in rows if row.value == distinct_values[0]]
    selected = _select_best(matching_rows, priority_for_field)
    return ResolvedField(
        field_key=field_key,
        status=ResolutionStatus.RESOLVED,
        value=distinct_values[0],
        candidates=tuple(rows),
        selected_evidence=selected,
        conflicts=(),
        observed_distinct_values=distinct_values,
    )


def _check_input_instrument(
    evidence_rows: Sequence[FieldEvidence],
    *,
    instrument_id: UUID | None,
) -> UUID:
    """Resolve the instrument_id for a resolver call.

    Behaviour:

    - When ``evidence_rows`` is empty, the caller must supply
      ``instrument_id`` explicitly; the resolver cannot otherwise
      audit which instrument it is resolving.
    - When ``evidence_rows`` is non-empty, the first row's
      ``instrument_id`` is the canonical reference. Any row whose
      ``instrument_id`` differs raises
      :class:`ResolutionPolicyError`; the resolver refuses to
      partition silently across instruments.
    - If the caller supplies ``instrument_id`` alongside a non-empty
      ``evidence_rows``, the supplied value must match the rows;
      mismatches raise :class:`ResolutionPolicyError`.
    """

    if not evidence_rows:
        if instrument_id is None:
            raise ResolutionPolicyError(
                "ProfileResolver.resolve requires an explicit instrument_id "
                "when the evidence sequence is empty"
            )
        if not isinstance(instrument_id, UUID) or isinstance(instrument_id, bool):
            raise TypeError(
                "ProfileResolver.resolve instrument_id must be a UUID"
            )
        if instrument_id == UUID(int=0):
            raise ValueError(
                "ProfileResolver.resolve instrument_id must not be "
                "the all-zero UUID"
            )
        return instrument_id

    resolved_instrument_id = evidence_rows[0].instrument_id
    for index, evidence in enumerate(evidence_rows[1:], start=1):
        if evidence.instrument_id != resolved_instrument_id:
            raise ResolutionPolicyError(
                "ProfileResolver.resolve received evidence rows targeting "
                "different instrument_id values: row 0 has "
                f"{resolved_instrument_id!s}, row {index} has "
                f"{evidence.instrument_id!s}"
            )
    if (
        instrument_id is not None
        and instrument_id != resolved_instrument_id
    ):
        raise ResolutionPolicyError(
            "ProfileResolver.resolve instrument_id argument "
            f"({instrument_id!s}) does not match the evidence rows "
            f"({resolved_instrument_id!s})"
        )
    return resolved_instrument_id


def _aggregate_overall_status(
    resolved: Mapping[FieldKey, ResolvedField],
) -> ResolutionStatus:
    """Compute the overall status from the per-field statuses.

    Rules:

    - Any :attr:`ResolutionStatus.CONFLICT` field wins: the resolver
      refuses to overwrite a conflict, so the profile as a whole
      reflects that.
    - If no field is populated (or every field is ``MISSING``), the
      overall status is :attr:`ResolutionStatus.MISSING`.
    - Otherwise, the overall status is :attr:`ResolutionStatus.RESOLVED`
      even if some fields are still missing: at least one field
      supplied a resolved value.
    """

    if not resolved:
        return ResolutionStatus.MISSING
    statuses = {field.status for field in resolved.values()}
    if ResolutionStatus.CONFLICT in statuses:
        return ResolutionStatus.CONFLICT
    if statuses == {ResolutionStatus.MISSING}:
        return ResolutionStatus.MISSING
    return ResolutionStatus.RESOLVED


@dataclass(frozen=True, slots=True)
class ResolvedField:
    """Per-field resolution result.

    Every populated attribute carries a clear meaning:

    - :attr:`field_key` — the closed-set
      :class:`~invest_domain.etf_profile.models.FieldKey` whose evidence
      was resolved.
    - :attr:`status` — :class:`ResolutionStatus` outcome.
    - :attr:`value` — the resolved value when ``status is RESOLVED``,
      otherwise ``None``. ``None`` is the explicit carrier for
      "unknown / not disclosed / conflict" (plan §5).
    - :attr:`selected_evidence` — the evidence row that drove the
      resolved value, when ``status is RESOLVED``. ``MISSING`` and
      ``CONFLICT`` resolutions leave this ``None``.
    - :attr:`candidates` — every evidence row that fed this field,
      preserved verbatim for the audit chain (including ``None``-valued
      rows that did not contribute to the value).
    - :attr:`conflicts` — the subset of :attr:`candidates` whose
      non-``None`` values disagreed; populated only on
      :attr:`ResolutionStatus.CONFLICT`.
    - :attr:`observed_distinct_values` — the distinct non-``None``
      values seen for the field, in first-occurrence order. Useful for
      audit dashboards that visualise the conflict set.
    """

    field_key: FieldKey
    status: ResolutionStatus
    value: Any = None
    candidates: tuple[FieldEvidence, ...] = ()
    selected_evidence: FieldEvidence | None = None
    conflicts: tuple[FieldEvidence, ...] = ()
    observed_distinct_values: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.field_key, FieldKey):
            raise TypeError(
                "ResolvedField.field_key must be a FieldKey, "
                f"got {type(self.field_key).__name__}"
            )
        if not isinstance(self.status, ResolutionStatus):
            raise TypeError(
                "ResolvedField.status must be a ResolutionStatus, "
                f"got {type(self.status).__name__}"
            )
        for name in ("candidates", "conflicts", "observed_distinct_values"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise TypeError(
                    f"ResolvedField.{name} must be a tuple, "
                    f"got {type(value).__name__}"
                )

        if self.selected_evidence is not None and not isinstance(
            self.selected_evidence, FieldEvidence
        ):
            raise TypeError(
                "ResolvedField.selected_evidence must be a FieldEvidence or "
                f"None, got {type(self.selected_evidence).__name__}"
            )

        if self.status is ResolutionStatus.RESOLVED:
            if self.selected_evidence is None:
                raise ValueError(
                    "ResolvedField.status=RESOLVED requires "
                    "selected_evidence to be set"
                )
            if self.value is None:
                raise ValueError(
                    "ResolvedField.status=RESOLVED requires a non-None value"
                )
            if self.selected_evidence.value != self.value:
                raise ValueError(
                    "ResolvedField.selected_evidence.value must match the "
                    "resolved value"
                )
            if self.conflicts:
                raise ValueError(
                    "ResolvedField.status=RESOLVED must not carry conflicts"
                )
        elif self.status is ResolutionStatus.CONFLICT:
            if self.value is not None:
                raise ValueError(
                    "ResolvedField.status=CONFLICT must carry value=None"
                )
            if not self.conflicts:
                raise ValueError(
                    "ResolvedField.status=CONFLICT must carry at least one "
                    "conflict evidence row"
                )
            if not self.observed_distinct_values:
                raise ValueError(
                    "ResolvedField.status=CONFLICT must carry at least one "
                    "observed distinct value"
                )
        elif self.status is ResolutionStatus.MISSING:
            if self.selected_evidence is not None:
                raise ValueError(
                    "ResolvedField.status=MISSING must not set "
                    "selected_evidence"
                )
            if self.conflicts:
                raise ValueError(
                    "ResolvedField.status=MISSING must not carry conflicts"
                )
            if self.candidates:
                # ``MISSING`` means no usable evidence; allowing
                # ``None``-value-only candidates would be auditable
                # noise. Drop them at construction time.
                raise ValueError(
                    "ResolvedField.status=MISSING must not carry candidates; "
                    "every candidate had a None value"
                )


@dataclass(frozen=True, slots=True)
class ProfileResolution:
    """Aggregated resolution outcome for one instrument.

    ``fields`` exposes one :class:`ResolvedField` per
    :class:`~invest_domain.etf_profile.models.FieldKey` observed in the
    input; the mapping is a :class:`types.MappingProxyType` so callers
    cannot mutate the resolver's output.

    ``overall_status`` follows
    :func:`_aggregate_overall_status`: any conflict short-circuits to
    :attr:`ResolutionStatus.CONFLICT`; an all-``MISSING`` bag is
    reported as :attr:`ResolutionStatus.MISSING`; otherwise the
    overall status is :attr:`ResolutionStatus.RESOLVED`.
    """

    instrument_id: UUID
    fields: Mapping[FieldKey, ResolvedField] = field(
        default_factory=lambda: MappingProxyType({})
    )
    overall_status: ResolutionStatus = ResolutionStatus.MISSING

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, UUID) or isinstance(self.instrument_id, bool):
            raise TypeError(
                "ProfileResolution.instrument_id must be a UUID, "
                f"got {type(self.instrument_id).__name__}"
            )
        if self.instrument_id == UUID(int=0):
            raise ValueError(
                "ProfileResolution.instrument_id must not be the all-zero UUID"
            )
        if not isinstance(self.fields, Mapping):
            raise TypeError(
                "ProfileResolution.fields must be a mapping of FieldKey to "
                "ResolvedField"
            )
        for key, value in self.fields.items():
            if not isinstance(key, FieldKey):
                raise TypeError(
                    "ProfileResolution.fields keys must be FieldKey, "
                    f"got {type(key).__name__}"
                )
            if not isinstance(value, ResolvedField):
                raise TypeError(
                    "ProfileResolution.fields values must be ResolvedField, "
                    f"got {type(value).__name__}"
                )
        if not isinstance(self.overall_status, ResolutionStatus):
            raise TypeError(
                "ProfileResolution.overall_status must be a ResolutionStatus, "
                f"got {type(self.overall_status).__name__}"
            )


@dataclass(frozen=True, slots=True)
class ProfileResolver:
    """Stateless resolver for ``FieldEvidence`` -> ``ProfileResolution``.

    Construct once with the desired priority policy and reuse across
    many instruments. The resolver is ``frozen=True`` + ``slots=True``
    so callers cannot accidentally mutate the policy after deployment.

    Usage::

        resolver = ProfileResolver()
        resolution = resolver.resolve(evidence_rows_for_one_instrument)
    """

    priority_policy: ProviderPriorityPolicy = DEFAULT_PROVIDER_PRIORITY_POLICY

    def resolve(
        self,
        evidence_rows: Sequence[FieldEvidence],
        *,
        instrument_id: UUID | None = None,
    ) -> ProfileResolution:
        """Resolve one instrument's evidence into a ``ProfileResolution``.

        The input sequence is grouped by ``field_key``; every group is
        resolved independently. Rows whose ``field_key`` is
        :attr:`~invest_domain.etf_profile.models.FieldKey.AUM` never
        share storage with rows whose ``field_key`` is
        :attr:`~invest_domain.etf_profile.models.FieldKey.MARKET_VALUE`
        or :attr:`~invest_domain.etf_profile.models.FieldKey.TURNOVER_VALUE`
        (plan §6). When two rows disagree on the value for the same
        field, the resolution becomes
        :attr:`ResolutionStatus.CONFLICT` and no value is emitted
        (plan §5 — "禁止覆盖").

        ``instrument_id`` is required only when ``evidence_rows`` is
        empty; for a non-empty sequence the resolver derives it from
        the first row and verifies that every subsequent row shares
        it. Mismatches raise :class:`ResolutionPolicyError`; the
        resolver refuses to partition silently across instruments.
        """

        resolved_instrument_id = _check_input_instrument(
            evidence_rows, instrument_id=instrument_id
        )

        by_field: dict[FieldKey, list[FieldEvidence]] = {}
        for evidence in evidence_rows:
            by_field.setdefault(evidence.field_key, []).append(evidence)

        resolved: dict[FieldKey, ResolvedField] = {}
        # Iterate in a deterministic key order (FieldKey.name ordering
        # by raw string) so the output mapping is reproducible.
        for field_key in sorted(by_field.keys(), key=lambda key: key.value):
            rows = by_field[field_key]
            priority_for_field = self.priority_policy.priority_for(field_key)
            resolved[field_key] = _resolve_field(
                field_key, rows, priority_for_field
            )

        overall_status = _aggregate_overall_status(resolved)
        return ProfileResolution(
            instrument_id=resolved_instrument_id,
            fields=MappingProxyType(resolved),
            overall_status=overall_status,
        )


def resolve_etf_profile_evidence(
    evidence_rows: Sequence[FieldEvidence],
    *,
    priority_policy: ProviderPriorityPolicy = DEFAULT_PROVIDER_PRIORITY_POLICY,
    instrument_id: UUID | None = None,
) -> ProfileResolution:
    """Functional helper equivalent to ``ProfileResolver(...).resolve(...)``.

    Useful for one-off calls where constructing a resolver explicitly
    would be ceremonial. The same precedence and conflict rules apply.
    """

    return ProfileResolver(priority_policy=priority_policy).resolve(
        evidence_rows, instrument_id=instrument_id
    )
