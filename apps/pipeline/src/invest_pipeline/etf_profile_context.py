"""Pure pipeline builder for the ETF Profile ``ResearchContextPack``.

Slice 1 of Task C3 (ETF Profile Context Builder). The builder is the
single deterministic projection from the inbound
:class:`invest_domain.etf_profile.models.FieldEvidence` rows to the
canonical :class:`invest_domain.research.ResearchContextPack` for the
``etf_profile`` context type. It is intentionally pure-domain:

- No Provider adapter, no Storage, no clock, no RNG.
- No dagster / fastapi / sqlalchemy imports.
- No environment access.

Pipeline chain honoured (plan §"Task C3"):

    FieldEvidence -> Resolver -> canonical EtfProfile -> ContextItem
        -> ResearchContextPack

The builder never reaches back to a Provider, never reaches back to
SQLAlchemy, and never fabricates a business value when the resolver
itself returns ``None`` (plan §6 — "AUM is never equated with total
market value"). The Resolver's
:class:`~invest_domain.etf_profile.resolver.ResolutionStatus` drives the
per-field ``ContextItem`` shape:

- :attr:`ResolutionStatus.RESOLVED` →
  - ``value`` = the resolved business value
  - ``quality_status`` = ``COMPLETE``
  - ``confidence_score`` = the selected evidence row's confidence score
  - ``evidence_refs`` = the selected evidence row's ``content_hash``
  - provenance propagated from the selected row.
- :attr:`ResolutionStatus.CONFLICT` →
  - ``value`` = ``None`` (no winner selected, plan §5 — "禁止覆盖")
  - ``quality_status`` = ``CONFLICT``
  - ``confidence_score`` = the best-ranked candidate's confidence score
    (audit only; the builder does not invent a value)
  - ``evidence_refs`` = the ``content_hash`` of every conflict row
  - provenance propagated from a stable sentinel (the first conflict row
    in the audit order) so the source chain stays anchored.
- :attr:`ResolutionStatus.MISSING` →
  - ``value`` = ``None`` (no fabricated business placeholder)
  - ``quality_status`` = ``MISSING``
  - ``confidence_score`` = ``0``
  - ``evidence_refs`` = ``()`` (no source row fed the resolver)
  - provenance = the resolver's :class:`FieldEvidenceSource` policy
    (``"resolver"`` / ``"etf_profile_resolution"``) so the audit chain
    still has a row to anchor to.

The resolver output already enforces the AUM / MARKET_VALUE /
TURNOVER_VALUE distinction (plan §6). The builder preserves the
separation by emitting exactly one :class:`ContextItem` per canonical
field. Evidence for non-canonical ``MARKET_VALUE`` and
``TURNOVER_VALUE`` fields is ignored; an ``AUM`` row never contributes to
either slot and vice-versa.

The module is the single source of truth for the ``etf_profile``
``ContextItem`` taxonomy. Slices 2 onward (persistence through
``uow.research_context_packs``) only consume this builder's output.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from invest_domain.etf_profile.models import (
    FieldEvidence,
    FieldKey,
    FieldValueType,
)
from invest_domain.etf_profile.resolver import (
    ResolutionStatus,
    ResolvedField,
    resolve_etf_profile_evidence,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.research.context import (
    ContextItem,
    ContextValueType,
    ResearchContextPack,
)
from invest_domain.research.models import QualityStatus

__all__ = [
    "ETF_PROFILE_CONTEXT_TYPE",
    "build_etf_profile_context_pack",
]


#: Canonical ``context_type`` for ETF Profile items.
ETF_PROFILE_CONTEXT_TYPE: str = "etf_profile"

#: Resolver-side provenance used when the resolver has no observation
#: to anchor a missing field to. Surfaced on the ``ContextItem`` so the
#: audit chain still has a stable source reference for a ``MISSING``
#: outcome; the builder never fabricates a Provider identifier here.
_RESOLVER_PROVIDER_KEY: str = "resolver"
_RESOLVER_DATASET_KEY: str = "etf_profile_resolution"

_CANONICAL_FIELDS: tuple[FieldKey, ...] = (
    FieldKey.MANAGER,
    FieldKey.BENCHMARK_INDEX,
    FieldKey.CATEGORY,
    FieldKey.INCEPTION_DATE,
    FieldKey.FUND_TYPE,
    FieldKey.MANAGEMENT_FEE,
    FieldKey.CUSTODY_FEE,
    FieldKey.AUM,
    FieldKey.SHARES,
)

_CANONICAL_VALUE_TYPES: dict[FieldKey, ContextValueType] = {
    FieldKey.MANAGER: ContextValueType.TEXT,
    FieldKey.BENCHMARK_INDEX: ContextValueType.TEXT,
    FieldKey.CATEGORY: ContextValueType.TEXT,
    FieldKey.INCEPTION_DATE: ContextValueType.DATE,
    FieldKey.FUND_TYPE: ContextValueType.TEXT,
    FieldKey.MANAGEMENT_FEE: ContextValueType.DECIMAL,
    FieldKey.CUSTODY_FEE: ContextValueType.DECIMAL,
    FieldKey.AUM: ContextValueType.DECIMAL,
    FieldKey.SHARES: ContextValueType.DECIMAL,
}


def _context_value_type_for(value_type: FieldValueType) -> ContextValueType:
    """Map a :class:`FieldValueType` to its :class:`ContextValueType` peer.

    Both enumerations share the ``text`` / ``decimal`` / ``date`` triple
    so the mapping is purely symbolic; the explicit conversion keeps
    the two type systems decoupled at the call site.
    """

    if value_type is FieldValueType.TEXT:
        return ContextValueType.TEXT
    if value_type is FieldValueType.DECIMAL:
        return ContextValueType.DECIMAL
    if value_type is FieldValueType.DATE:
        return ContextValueType.DATE
    raise ValueError(f"unsupported FieldValueType: {value_type!r}")


def _build_item_for_field(
    *,
    field_key: FieldKey,
    resolved: ResolvedField,
    observed_at: datetime,
) -> ContextItem:
    """Project one :class:`ResolvedField` into a ``ContextItem``.

    The function is the per-field implementation of the public builder.
    The three branches correspond to the three ``ResolutionStatus``
    outcomes; the three branches never share business logic.
    """

    canonical_key = f"{ETF_PROFILE_CONTEXT_TYPE}.{field_key.value}"
    context_type = ETF_PROFILE_CONTEXT_TYPE

    if resolved.status is ResolutionStatus.RESOLVED:
        selected = resolved.selected_evidence
        assert selected is not None  # invariant of ResolvedField.__post_init__
        return ContextItem(
            context_type=context_type,
            key=canonical_key,
            value=resolved.value,
            value_type=_context_value_type_for(selected.value_type),
            source_provider=selected.source.provider_key,
            source_dataset=selected.source.dataset_key,
            observed_at=selected.source.observed_at,
            source_batch_id=selected.source.source_batch_id,
            source_revision=selected.source.revision,
            quality_status=QualityStatus.COMPLETE,
            confidence_score=selected.confidence_score,
            evidence_refs=(selected.content_hash,),
        )

    if resolved.status is ResolutionStatus.CONFLICT:
        # Plan §5: "禁止覆盖" — the builder never picks a winner. The
        # ``value`` is always ``None`` and the audit chain carries the
        # ``content_hash`` of every conflicting row in
        # ``evidence_refs``. The provenance is anchored on the first
        # conflict row (deterministic order through the resolver's
        # sort key) so the source chain is not orphaned.
        conflicts = resolved.conflicts
        first_conflict = conflicts[0]
        return ContextItem(
            context_type=context_type,
            key=canonical_key,
            value=None,
            value_type=_CANONICAL_VALUE_TYPES[field_key],
            source_provider=first_conflict.source.provider_key,
            source_dataset=first_conflict.source.dataset_key,
            observed_at=first_conflict.source.observed_at,
            source_batch_id=first_conflict.source.source_batch_id,
            source_revision=first_conflict.source.revision,
            quality_status=QualityStatus.CONFLICT,
            confidence_score=first_conflict.confidence_score,
            evidence_refs=tuple(row.content_hash for row in conflicts),
        )

    if resolved.status is ResolutionStatus.MISSING:
        # ``MISSING`` carries no usable evidence; the builder never
        # invents a business value. The audit chain is anchored to the
        # resolver-side provider so the ``ContextItem`` still has a
        # stable source reference without a fabricated value.
        return ContextItem(
            context_type=context_type,
            key=canonical_key,
            value=None,
            value_type=_CANONICAL_VALUE_TYPES[field_key],
            source_provider=_RESOLVER_PROVIDER_KEY,
            source_dataset=_RESOLVER_DATASET_KEY,
            observed_at=observed_at,
            source_batch_id=None,
            source_revision=1,
            quality_status=QualityStatus.MISSING,
            confidence_score=Decimal("0"),
            evidence_refs=(),
        )

    raise ValueError(
        f"unsupported ResolutionStatus for {field_key.value!r}: {resolved.status!r}"
    )


def build_etf_profile_context_pack(
    evidence_rows: Sequence[FieldEvidence],
    *,
    instrument_id: UUID | InstrumentId | None = None,
    observed_at: datetime,
    created_at: datetime | None = None,
    context_version: int = 1,
) -> ResearchContextPack:
    """Build a :class:`ResearchContextPack` for the ``etf_profile`` context.

    Parameters
    ----------
    evidence_rows:
        :class:`FieldEvidence` rows for **one** instrument. The
        resolver refuses to mix rows across instruments; the caller's
        instrument id is taken from the first row when ``instrument_id``
        is not supplied.
    instrument_id:
        Optional explicit instrument id. When supplied, the resolver
        checks that every row shares the same id and raises
        :class:`~invest_domain.etf_profile.resolver.ResolutionPolicyError`
        on a mismatch. The id is required when ``evidence_rows`` is
        empty so the resulting pack still points at a real instrument.
    observed_at:
        Timezone-aware ``datetime`` stamped on every emitted
        :class:`ContextItem`. The builder does not consult a clock; the
        caller passes the pipeline-level ``observed_at`` so the context
        pack stays traceable to the upstream provider attempt.
    created_at:
        Optional audit timestamp recorded on the enclosing
        :class:`ResearchContextPack`. ``None`` means "let the
        repository stamp it"; the builder excludes ``created_at`` from
        the canonical ``content_hash`` so the digest stays stable across
        re-runs.
    context_version:
        Business revision counter (default ``1``). A different
        ``context_version`` produces a different ``content_hash`` and
        lands at a different row in ``analytics.research_context_packs``
        per the storage layer's
        ``(instrument_id, context_version)`` index.

    Returns
    -------
    ResearchContextPack
        An immutable, hash-stable pack ready for persistence through
        :class:`invest_storage.repositories.SqlAlchemyResearchContextPackRepository`.
        The pack carries exactly one ``ContextItem`` for each canonical
        ETF Profile field. Fields without evidence are emitted as
        ``MISSING``; non-canonical evidence is not projected.
    """

    resolver_instrument_id: UUID | None
    if isinstance(instrument_id, InstrumentId):
        resolver_instrument_id = instrument_id.value
    else:
        resolver_instrument_id = instrument_id

    resolution = resolve_etf_profile_evidence(
        evidence_rows,
        instrument_id=resolver_instrument_id,
    )

    # Build the items in a deterministic order so the pack's
    # ``content_hash`` is stable across runs. ``FieldKey`` is the
    # closed-set vocabulary; sorting by ``.value`` pins the order to
    # the canonical enum naming.
    items: list[ContextItem] = []
    for field_key in _CANONICAL_FIELDS:
        resolved = resolution.fields.get(
            field_key,
            ResolvedField(field_key=field_key, status=ResolutionStatus.MISSING),
        )
        items.append(
            _build_item_for_field(
                field_key=field_key,
                resolved=resolved,
                observed_at=observed_at,
            )
        )

    pack_instrument_id = (
        instrument_id if isinstance(instrument_id, InstrumentId) else None
    )
    if pack_instrument_id is None:
        pack_instrument_id = InstrumentId(resolution.instrument_id)

    return ResearchContextPack(
        instrument_id=pack_instrument_id,
        items=tuple(items),
        context_version=context_version,
        created_at=created_at,
    )
