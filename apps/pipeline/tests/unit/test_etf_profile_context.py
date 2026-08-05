"""Unit tests for the pure ETF Profile ``ContextPack`` builder (Slice 1, Task C3).

The builder is a deterministic projection from
:class:`invest_domain.etf_profile.models.FieldEvidence` rows to a
:class:`invest_domain.research.ResearchContextPack`. The slice is
pure-domain: no Provider adapter, no Storage, no clock, no RNG.

The tests pin the four behaviours the user explicitly listed:

- **Resolved**: the emitted ``ContextItem`` carries the selected
  evidence row's value, the selected provenance, and the selected
  ``content_hash`` as its lone ``evidence_ref``.
- **Conflict**: ``value`` is ``None`` and ``quality_status`` is
  ``CONFLICT``; the ``evidence_refs`` tuple contains the
  ``content_hash`` of every conflicting row; the builder never invents
  a single resolved value.
- **Missing**: ``value`` is ``None`` and ``quality_status`` is
  ``MISSING``; ``confidence_score`` is ``0``; ``evidence_refs`` is
  empty; the builder never fabricates a business placeholder.
- **AUM distinct from MARKET_VALUE / TURNOVER_VALUE**: each
  ``FieldKey`` maps to its own ``ContextItem`` with a unique
  ``etf_profile.<field>`` key, and a ``MARKET_VALUE`` ``FieldEvidence``
  row never feeds the ``AUM`` slot (and vice-versa).

Plus regression covers:

- the canonical field set is exactly the nine canonical fields
  (``manager`` / ``benchmark_index`` / ``category`` /
  ``inception_date`` / ``fund_type`` / ``management_fee`` /
  ``custody_fee`` / ``aum`` / ``shares``) when a fully-resolved
  snapshot is supplied, one ``ContextItem`` per field with
  ``context_type="etf_profile"`` and key ``etf_profile.<field>``;
- the ``FieldValueType`` -> ``ContextValueType`` mapping routes
  ``TEXT`` => ``TEXT``, ``DECIMAL`` => ``DECIMAL``, ``DATE`` => ``DATE``;
- the pack's ``content_hash`` is stable across two calls over the
  same evidence input (the audit-digest invariant).
- an empty input (no evidence rows) yields nine explicit ``MISSING``
  canonical items rather than crashing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from invest_domain.etf_profile.models import (
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
)
from invest_domain.instruments.models import InstrumentId
from invest_domain.research.context import (
    ContextValueType,
    ResearchContextPack,
    compute_context_pack_hash,
)
from invest_domain.research.models import QualityStatus
from invest_pipeline.etf_profile_context import (
    ETF_PROFILE_CONTEXT_TYPE,
    build_etf_profile_context_pack,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _observed_at(seed: int = 0) -> datetime:
    return datetime(2026, 8, 5, 12, 0, seed, tzinfo=UTC)


def _source(
    *,
    provider_key: str = "fund_official",
    dataset_key: str = "etf_profile_snapshot",
    observed_at: datetime | None = None,
    source_batch_id: UUID | None = None,
    revision: int = 1,
) -> FieldEvidenceSource:
    return FieldEvidenceSource(
        provider_key=provider_key,
        dataset_key=dataset_key,
        observed_at=observed_at or _observed_at(),
        source_batch_id=source_batch_id or uuid4(),
        revision=revision,
    )


def _evidence(
    *,
    field_key: FieldKey,
    value: object,
    value_type: FieldValueType,
    source: FieldEvidenceSource | None = None,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    confidence_score: Decimal = Decimal("0.95"),
    instrument_id: UUID | None = None,
) -> FieldEvidence:
    return FieldEvidence(
        instrument_id=instrument_id or uuid4(),
        field_key=field_key,
        value=value,
        value_type=value_type,
        source=source or _source(),
        quality_status=quality_status,
        confidence_score=confidence_score,
    )


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


def _fully_resolved_evidence(instrument_id: UUID) -> list[FieldEvidence]:
    return [
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.MANAGER,
            value="华夏基金",
            value_type=FieldValueType.TEXT,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.BENCHMARK_INDEX,
            value="沪深300指数",
            value_type=FieldValueType.TEXT,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.CATEGORY,
            value="Equity",
            value_type=FieldValueType.TEXT,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2012, 5, 28),
            value_type=FieldValueType.DATE,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.FUND_TYPE,
            value="ETF",
            value_type=FieldValueType.TEXT,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.MANAGEMENT_FEE,
            value=Decimal("0.0015"),
            value_type=FieldValueType.DECIMAL,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.CUSTODY_FEE,
            value=Decimal("0.0002"),
            value_type=FieldValueType.DECIMAL,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.AUM,
            value=Decimal("1234567890.12"),
            value_type=FieldValueType.DECIMAL,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.SHARES,
            value=Decimal("1000000000"),
            value_type=FieldValueType.DECIMAL,
        ),
    ]


# ---------------------------------------------------------------------------
# Canonical field set
# ---------------------------------------------------------------------------


def test_canonical_pack_emits_one_item_per_canonical_field() -> None:
    """A fully-resolved snapshot yields exactly nine ``ContextItem`` rows,
    one per canonical field, with ``context_type="etf_profile"`` and
    key ``etf_profile.<field>``. The keys are sorted alphabetically by
    ``FieldKey.value`` so the pack's ``content_hash`` is deterministic
    (plan §5 — "Context Item 按 (context_type, key, item_hash) 排序")."""
    instrument_id = uuid4()
    rows = _fully_resolved_evidence(instrument_id)

    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    assert isinstance(pack, ResearchContextPack)
    assert pack.instrument_id == InstrumentId(instrument_id)
    assert len(pack.items) == len(_CANONICAL_FIELDS)
    keys = {item.key for item in pack.items}
    expected_keys = {
        f"{ETF_PROFILE_CONTEXT_TYPE}.{field.value}" for field in _CANONICAL_FIELDS
    }
    assert keys == expected_keys
    for item in pack.items:
        assert item.context_type == ETF_PROFILE_CONTEXT_TYPE
        assert item.quality_status is QualityStatus.COMPLETE


def test_field_value_type_routes_to_context_value_type() -> None:
    """The ``FieldValueType`` -> ``ContextValueType`` mapping is
    explicit: ``TEXT`` => ``TEXT``, ``DECIMAL`` => ``DECIMAL``,
    ``DATE`` => ``DATE``."""
    instrument_id = uuid4()
    rows = _fully_resolved_evidence(instrument_id)

    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    by_key = {item.key: item for item in pack.items}
    assert by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.manager"].value_type is ContextValueType.TEXT
    assert by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.category"].value_type is ContextValueType.TEXT
    assert (
        by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.inception_date"].value_type
        is ContextValueType.DATE
    )
    assert (
        by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.management_fee"].value_type
        is ContextValueType.DECIMAL
    )
    assert (
        by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.aum"].value_type is ContextValueType.DECIMAL
    )


# ---------------------------------------------------------------------------
# RESOLVED: provenance, value, evidence_refs
# ---------------------------------------------------------------------------


def test_resolved_item_carries_selected_evidence_provenance_and_hash() -> None:
    """A ``RESOLVED`` field's ``ContextItem`` carries the selected
    evidence row's value, full source provenance, and the selected
    row's ``content_hash`` as its sole ``evidence_ref``."""
    instrument_id = uuid4()
    batch_id = uuid4()
    selected_source = _source(
        provider_key="fund_official",
        dataset_key="etf_profile_snapshot",
        observed_at=_observed_at(1),
        source_batch_id=batch_id,
        revision=2,
    )
    selected = _evidence(
        instrument_id=instrument_id,
        field_key=FieldKey.MANAGER,
        value="华夏基金",
        value_type=FieldValueType.TEXT,
        source=selected_source,
        confidence_score=Decimal("0.95"),
    )

    pack = build_etf_profile_context_pack(
        [selected],
        instrument_id=instrument_id,
        observed_at=_observed_at(7),
    )

    manager_item = next(
        item for item in pack.items if item.key == f"{ETF_PROFILE_CONTEXT_TYPE}.manager"
    )
    assert manager_item.value == "华夏基金"
    assert manager_item.value_type is ContextValueType.TEXT
    assert manager_item.source_provider == "fund_official"
    assert manager_item.source_dataset == "etf_profile_snapshot"
    assert manager_item.source_batch_id == batch_id
    assert manager_item.source_revision == 2
    assert manager_item.observed_at == selected_source.observed_at
    assert manager_item.confidence_score == Decimal("0.95")
    assert manager_item.evidence_refs == (selected.content_hash,)
    assert manager_item.quality_status is QualityStatus.COMPLETE


# ---------------------------------------------------------------------------
# CONFLICT: value None, quality_status CONFLICT, hash refs from offending rows
# ---------------------------------------------------------------------------


def test_conflict_field_emits_none_value_and_conflict_status_with_hash_refs() -> None:
    """Two rows with distinct non-None values for the same field must
    collide; the emitted ``ContextItem`` carries ``value=None``,
    ``quality_status=CONFLICT``, and the ``content_hash`` of every
    conflicting row in ``evidence_refs``."""
    instrument_id = uuid4()
    batch_id_a = uuid4()
    batch_id_b = uuid4()
    row_a = _evidence(
        instrument_id=instrument_id,
        field_key=FieldKey.MANAGER,
        value="华夏基金",
        value_type=FieldValueType.TEXT,
        source=_source(
            provider_key="fund_announcement",
            dataset_key="etf_profile_snapshot",
            observed_at=_observed_at(1),
            source_batch_id=batch_id_a,
        ),
        confidence_score=Decimal("0.97"),
    )
    row_b = _evidence(
        instrument_id=instrument_id,
        field_key=FieldKey.MANAGER,
        value="华夏基金管理有限公司",
        value_type=FieldValueType.TEXT,
        source=_source(
            provider_key="fund_official",
            dataset_key="etf_profile_snapshot",
            observed_at=_observed_at(2),
            source_batch_id=batch_id_b,
        ),
        confidence_score=Decimal("0.6"),
    )

    pack = build_etf_profile_context_pack(
        [row_a, row_b],
        instrument_id=instrument_id,
        observed_at=_observed_at(7),
    )

    manager_item = next(
        item for item in pack.items if item.key == f"{ETF_PROFILE_CONTEXT_TYPE}.manager"
    )
    assert manager_item.value is None
    assert manager_item.value_type is ContextValueType.TEXT
    assert manager_item.quality_status is QualityStatus.CONFLICT
    assert manager_item.confidence_score == Decimal("0.97")
    assert sorted(manager_item.evidence_refs) == sorted(
        (row_a.content_hash, row_b.content_hash)
    )
    # No business value is fabricated; the value is exactly ``None``.
    assert manager_item.value is None
    # Provenance is anchored on the first (highest-priority) conflict
    # row so the source chain is not orphaned.
    assert manager_item.source_provider == "fund_announcement"
    assert manager_item.source_batch_id == batch_id_a


# ---------------------------------------------------------------------------
# MISSING: value None, quality_status MISSING, no fabricated business values
# ---------------------------------------------------------------------------


def test_missing_field_emits_none_value_no_business_placeholder() -> None:
    """A field whose only candidate rows carry ``None`` values must
    emit ``value=None``, ``quality_status=MISSING``,
    ``confidence_score=0``, and an empty ``evidence_refs`` tuple. The
    builder never invents a Provider identifier or a business
    placeholder value."""
    instrument_id = uuid4()
    observed = _evidence(
        instrument_id=instrument_id,
        field_key=FieldKey.CATEGORY,
        value="Equity",
        value_type=FieldValueType.TEXT,
    )
    missing = _evidence(
        instrument_id=instrument_id,
        field_key=FieldKey.MANAGER,
        value=None,
        value_type=FieldValueType.TEXT,
        quality_status=QualityStatus.MISSING,
    )

    pack = build_etf_profile_context_pack(
        [observed, missing],
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    manager_item = next(
        item for item in pack.items if item.key == f"{ETF_PROFILE_CONTEXT_TYPE}.manager"
    )
    assert manager_item.value is None
    assert manager_item.quality_status is QualityStatus.MISSING
    assert manager_item.confidence_score == Decimal("0")
    assert manager_item.evidence_refs == ()
    # The resolver-side provenance is the only stable source anchor.
    assert manager_item.source_provider == "resolver"
    assert manager_item.source_dataset == "etf_profile_resolution"
    assert manager_item.source_batch_id is None
    # No fabricated business value: ``value`` is exactly ``None``, not
    # ``""`` or ``Decimal("0")`` or any sentinel.
    assert manager_item.value is None


def test_missing_with_candidates_only_emits_missing_when_all_values_are_none() -> None:
    """A field whose only candidate rows carry ``None`` values must
    collapse to ``MISSING``; the builder never preserves a business
    value from the candidate set."""
    instrument_id = uuid4()
    rows = [
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.MISSING,
        ),
    ]

    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    aum_item = next(
        item for item in pack.items if item.key == f"{ETF_PROFILE_CONTEXT_TYPE}.aum"
    )
    assert aum_item.value is None
    assert aum_item.quality_status is QualityStatus.MISSING
    assert aum_item.confidence_score == Decimal("0")
    assert aum_item.evidence_refs == ()


# ---------------------------------------------------------------------------
# AUM distinct from MARKET_VALUE / TURNOVER_VALUE
# ---------------------------------------------------------------------------


def test_aum_does_not_alias_market_value_or_turnover_value() -> None:
    """The three keys are distinct ``FieldKey`` members. The builder
    emits one ``ContextItem`` per key with a unique name even when all
    three rows are present; an ``AUM`` ``FieldEvidence`` row never feeds
    the ``MARKET_VALUE`` or ``TURNOVER_VALUE`` slot, and vice-versa.
    """
    instrument_id = uuid4()
    rows = [
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.AUM,
            value=Decimal("1234567890.12"),
            value_type=FieldValueType.DECIMAL,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.MARKET_VALUE,
            value=Decimal("999999999.99"),
            value_type=FieldValueType.DECIMAL,
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.TURNOVER_VALUE,
            value=Decimal("555555555.55"),
            value_type=FieldValueType.DECIMAL,
        ),
    ]

    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    by_key = {item.key: item for item in pack.items}
    aum_item = by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.aum"]
    assert aum_item.value == Decimal("1234567890.12")
    # Evidence-only market and turnover values are not projected into
    # the canonical ETF Profile context, and can never populate AUM.
    assert f"{ETF_PROFILE_CONTEXT_TYPE}.market_value" not in by_key
    assert f"{ETF_PROFILE_CONTEXT_TYPE}.turnover_value" not in by_key
    assert aum_item.key == f"{ETF_PROFILE_CONTEXT_TYPE}.aum"


def test_aum_with_same_decimal_as_market_value_stays_distinct() -> None:
    """Even when the AUM and MARKET_VALUE happen to share the same
    numeric value, the resolver and the builder keep the two slots
    separate. The plan §6 boundary is independent of ``value``
    identity."""
    instrument_id = uuid4()
    shared_value = Decimal("1000000000")
    rows = [
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.AUM,
            value=shared_value,
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="fund_official"),
        ),
        _evidence(
            instrument_id=instrument_id,
            field_key=FieldKey.MARKET_VALUE,
            value=shared_value,
            value_type=FieldValueType.DECIMAL,
            source=_source(provider_key="exchange"),
        ),
    ]

    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    by_key = {item.key: item for item in pack.items}
    assert by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.aum"].value == shared_value
    # The evidence-only market-value row does not create a context item.
    assert (
        by_key[f"{ETF_PROFILE_CONTEXT_TYPE}.aum"].source_provider == "fund_official"
    )
    assert f"{ETF_PROFILE_CONTEXT_TYPE}.market_value" not in by_key


# ---------------------------------------------------------------------------
# Misc invariants
# ---------------------------------------------------------------------------


def test_pack_content_hash_is_stable_across_two_calls() -> None:
    """The pack's ``content_hash`` is stable across two calls over the
    same input; the audit-digest invariant is preserved."""
    instrument_id = uuid4()
    rows = _fully_resolved_evidence(instrument_id)

    first = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )
    second = build_etf_profile_context_pack(
        rows,
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )

    assert first.content_hash == second.content_hash
    assert first.content_hash == compute_context_pack_hash(first)


def test_empty_evidence_yields_pack_at_instrument() -> None:
    """An empty evidence input still produces a (zero-item) pack
    anchored to the supplied instrument_id; the call does not crash."""
    instrument_id = uuid4()
    pack = build_etf_profile_context_pack(
        [],
        instrument_id=instrument_id,
        observed_at=_observed_at(),
    )
    assert isinstance(pack, ResearchContextPack)
    assert pack.instrument_id == InstrumentId(instrument_id)
    assert len(pack.items) == 9
    assert all(item.quality_status is QualityStatus.MISSING for item in pack.items)
    assert len(pack.content_hash) == 64


def test_builder_accepts_instrument_id_value() -> None:
    """The builder accepts the ``InstrumentId`` value object as well as
    the raw ``UUID`` — the resolver normalises either shape."""
    instrument_id = uuid4()
    rows = _fully_resolved_evidence(instrument_id)
    pack = build_etf_profile_context_pack(
        rows,
        instrument_id=InstrumentId(instrument_id),
        observed_at=_observed_at(),
    )
    assert pack.instrument_id == InstrumentId(instrument_id)
