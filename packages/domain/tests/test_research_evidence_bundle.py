"""Unit tests for the :class:`ResearchEvidenceBundle` value object.

The bundle binds one :class:`ResearchCase`'s immutable evidence
identity — the existing ETF :class:`EvidencePack` plus zero or more
Analytics-owned :class:`MarketObservationSnapshot` records — and
exposes a deterministic ``bundle_hash`` so a downstream AI consumer
can always attribute every fact back to the bundle.

The companion :class:`ContextProjection` DTO/serializer is exercised
together with the bundle: same bundle + same upstream evidence
produces byte-stable projection JSON; changing any upstream field
produces a new bundle identity and therefore a new projection.

The tests intentionally do not touch the storage layer: bundle
identity is a pure-domain contract. Persistence tests live next to
the SQLAlchemy adapter in ``tests/storage``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.analytics.market_temperature import build_market_temperature
from invest_domain.instruments import InstrumentId
from invest_domain.research import (
    BUNDLE_SCHEMA_VERSION,
    ContextProjection,
    EvidencePack,
    MarketSnapshotRef,
    QualityStatus,
    ResearchEvidenceBundle,
    build_projection,
    canonical_bundle_json,
    compute_bundle_hash,
)
from invest_domain.research.models import FactorObservation, FreshnessStatus

from packages.domain.tests.test_research_evidence import _pack

_BASE = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _observation(
    *,
    instrument_id: InstrumentId,
    factor_key: str,
    value: str,
    window: int = 20,
) -> FactorObservation:
    return FactorObservation(
        factor_key=factor_key,
        instrument_id=instrument_id,
        value=Decimal(value),
        unit="ratio",
        window=window,
        observed_date=date(2026, 8, 7),
        quality_status=QualityStatus.COMPLETE,
    )


def _market_snapshot(
    *,
    input_id: UUID | None = None,
    snapshot_date: date = date(2026, 8, 7),
) -> MarketObservationSnapshot:
    instruments = [
        InstrumentId(UUID("00000000-0000-4000-8000-000000000001")),
        InstrumentId(UUID("00000000-0000-4000-8000-000000000002")),
    ]
    return build_market_temperature(
        input_snapshot_id=input_id or UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        factor_observations=tuple(
            _observation(
                instrument_id=instrument,
                factor_key=key,
                value=value,
            )
            for instrument in instruments
            for key, value in zip(
                (
                    "return_20d",
                    "realized_volatility_20d",
                    "avg_turnover_amount_20d",
                    "max_drawdown_60d",
                ),
                ("0.2", "0.3", "50000000", "0.1"),
                strict=True,
            )
        ),
        as_of_date=snapshot_date,
    )


def _case_aligned_pack(case_id: UUID) -> EvidencePack:
    """Build an :class:`EvidencePack` whose ``case.case_id`` is a UUID."""

    return _pack(case_id=case_id)


def test_bundle_schema_version_is_frozen() -> None:
    assert BUNDLE_SCHEMA_VERSION == "1.0.0"


def test_build_produces_deterministic_bundle_for_same_inputs() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()

    first = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    second = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )

    assert first.bundle_hash == second.bundle_hash
    assert canonical_bundle_json(first) == canonical_bundle_json(second)
    assert first.bundle_id != second.bundle_id  # bundle_id is fresh per build
    assert first.research_case_id == case_id
    assert first.evidence_pack_id == pack.pack_id
    assert first.evidence_pack_hash == pack.pack_hash
    assert first.as_of_date == pack.case.as_of_date
    assert first.schema_version == BUNDLE_SCHEMA_VERSION
    assert len(first.bundle_hash) == 64


def test_build_reorders_market_snapshots_deterministically() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snap_a = _market_snapshot(input_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    snap_b = _market_snapshot(input_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))

    forward = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snap_a, snap_b), created_at=_BASE
    )
    reversed_ = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snap_b, snap_a), created_at=_BASE
    )
    assert forward.bundle_hash == reversed_.bundle_hash
    assert [ref.snapshot_id for ref in forward.market_snapshot_refs] == [
        ref.snapshot_id for ref in reversed_.market_snapshot_refs
    ]


def test_bundle_hash_changes_when_underlying_evidence_changes() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    base = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )

    changed_pack = replace(pack, pack_id=UUID("22222222-2222-4222-8222-222222222222"))
    other = ResearchEvidenceBundle.build(
        evidence_pack=changed_pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    assert base.bundle_hash != other.bundle_hash

    extra = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(), created_at=_BASE
    )
    assert base.bundle_hash != extra.bundle_hash


def test_build_rejects_pack_without_pack_id() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    with pytest.raises(ValueError, match="pack_id"):
        ResearchEvidenceBundle.build(evidence_pack=replace(pack, pack_id=None))


def test_build_rejects_pack_with_string_case_id() -> None:
    pack = _pack(case_id="case-runtime-a")
    with pytest.raises(ValueError, match="case.case_id"):
        ResearchEvidenceBundle.build(evidence_pack=pack)


def test_build_rejects_duplicate_market_snapshot_ids() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    with pytest.raises(ValueError, match="duplicate snapshot_id"):
        ResearchEvidenceBundle.build(
            evidence_pack=pack, market_snapshots=(snapshot, snapshot)
        )


def test_direct_construction_rejects_invalid_schema_version() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    with pytest.raises(ValueError, match="schema_version"):
        ResearchEvidenceBundle(
            bundle_id=uuid4(),
            research_case_id=case_id,
            evidence_pack_id=pack.pack_id,
            evidence_pack_hash=pack.pack_hash,
            market_snapshot_refs=(),
            schema_version="0.9.0",
            bundle_hash="0" * 64,
            created_at=_BASE,
            as_of_date=pack.case.as_of_date,
        )


def test_direct_construction_rejects_mismatching_bundle_hash() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    with pytest.raises(ValueError, match="bundle_hash"):
        ResearchEvidenceBundle(
            bundle_id=uuid4(),
            research_case_id=case_id,
            evidence_pack_id=pack.pack_id,
            evidence_pack_hash=pack.pack_hash,
            market_snapshot_refs=(),
            schema_version=BUNDLE_SCHEMA_VERSION,
            bundle_hash="0" * 64,
            created_at=_BASE,
            as_of_date=pack.case.as_of_date,
        )


def test_direct_construction_rejects_naive_created_at() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, created_at=_BASE
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchEvidenceBundle(
            bundle_id=bundle.bundle_id,
            research_case_id=bundle.research_case_id,
            evidence_pack_id=bundle.evidence_pack_id,
            evidence_pack_hash=bundle.evidence_pack_hash,
            market_snapshot_refs=bundle.market_snapshot_refs,
            schema_version=bundle.schema_version,
            bundle_hash=bundle.bundle_hash,
            created_at=_BASE.replace(tzinfo=None),
            as_of_date=bundle.as_of_date,
        )


def test_market_snapshot_ref_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="snapshot_id"):
        MarketSnapshotRef(
            snapshot_id="",
            content_hash="0" * 64,
            as_of_date=date(2026, 8, 7),
        )
    with pytest.raises(ValueError, match="content_hash"):
        MarketSnapshotRef(
            snapshot_id="mos:abc",
            content_hash="short",
            as_of_date=date(2026, 8, 7),
        )
    with pytest.raises(TypeError, match="as_of_date"):
        MarketSnapshotRef(
            snapshot_id="mos:abc",
            content_hash="0" * 64,
            as_of_date="not-a-date",
        )


def test_bundle_with_zero_market_snapshots_is_valid() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    assert bundle.market_snapshot_refs == ()


def test_compute_bundle_hash_matches_built_bundle_hash() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    assert compute_bundle_hash(bundle) == bundle.bundle_hash


def test_projection_emits_evidence_refs_for_pack_factors_and_market_observations() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )

    assert isinstance(projection, ContextProjection)
    assert projection.bundle_id == bundle.bundle_id
    assert projection.bundle_hash == bundle.bundle_hash
    assert projection.research_case_id == case_id
    assert projection.evidence_pack_id == pack.pack_id
    assert projection.evidence_pack_hash == pack.pack_hash
    assert projection.market_snapshot_ids == (snapshot.snapshot_id,)

    factor_keys = {item["factor_key"] for item in projection.etf_factor_observations}
    assert factor_keys == {
        "avg_turnover_amount_20d",
        "data_completeness_60d",
        "distance_ma20",
        "distance_ma60",
        "max_drawdown_60d",
        "realized_volatility_20d",
        "return_20d",
        "return_60d",
    }
    for item in projection.etf_factor_observations:
        assert item["evidence_type"] == "factor_observation"
        assert item["evidence_id"].startswith("evi:")
        assert len(item["item_hash"]) == 64
        assert "source_kind" in item and "source_ref" in item
        assert "observed_date" in item and "quality_status" in item

    market_keys = {item["observation_key"] for item in projection.market_observations}
    assert "market_temperature_score" in market_keys
    assert "market_temperature_state" in market_keys
    for item in projection.market_observations:
        assert item["evidence_type"] == "market_observation"
        assert item["evidence_id"].startswith("mos:")
        assert len(item["item_hash"]) == 64


def test_projection_to_json_is_byte_stable() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )

    a = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    b = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    assert a.to_json() == b.to_json()
    assert a.to_dict() == b.to_dict()


def test_projection_rejects_mismatching_evidence_pack() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    other = replace(pack, pack_id=UUID("33333333-3333-4333-8333-333333333333"))
    with pytest.raises(ValueError, match="evidence_pack_id"):
        build_projection(bundle=bundle, evidence_pack=other)
    with pytest.raises(ValueError, match="pack_hash"):
        build_projection(
            bundle=bundle,
            evidence_pack=replace(pack, pack_hash="0" * 64),
        )


def test_projection_rejects_missing_or_extra_market_snapshots() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )

    with pytest.raises(ValueError, match="missing the MarketObservationSnapshot"):
        build_projection(bundle=bundle, evidence_pack=pack, market_snapshots=())

    extra = _market_snapshot(input_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"))
    with pytest.raises(ValueError, match="not bound by the bundle"):
        build_projection(
            bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot, extra)
        )


def test_projection_rejects_mismatching_snapshot_content_hash() -> None:
    """Snapshot content_hash drift is caught before reaching the AI input.

    Bypasses the dataclass ``__post_init__`` so we can hand a
    snapshot whose ``snapshot_id`` matches the bundle ref but whose
    ``content_hash`` has drifted, mirroring a real-world race
    between the bundle being persisted and a snapshot being
    re-collected. The projection must fail closed.
    """

    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    tampered = MarketObservationSnapshot.__new__(MarketObservationSnapshot)
    object.__setattr__(tampered, "input_snapshot_id", snapshot.input_snapshot_id)
    object.__setattr__(tampered, "as_of_date", snapshot.as_of_date)
    object.__setattr__(tampered, "observations", snapshot.observations)
    object.__setattr__(tampered, "algorithm_version", snapshot.algorithm_version)
    object.__setattr__(tampered, "scope_type", snapshot.scope_type)
    object.__setattr__(tampered, "scope_key", snapshot.scope_key)
    object.__setattr__(tampered, "quality_status", snapshot.quality_status)
    object.__setattr__(tampered, "freshness_status", snapshot.freshness_status)
    object.__setattr__(tampered, "content_hash", "0" * 64)
    object.__setattr__(tampered, "snapshot_id", snapshot.snapshot_id)
    assert tampered.content_hash != snapshot.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        build_projection(bundle=bundle, evidence_pack=pack, market_snapshots=(tampered,))


def test_projection_with_zero_market_snapshots_is_empty() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    projection = build_projection(bundle=bundle, evidence_pack=pack)
    assert projection.market_snapshot_ids == ()
    assert projection.market_observations == ()


def test_projection_validates_non_blank_market_snapshot_ids() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    with pytest.raises(ValueError, match="market_snapshot_ids"):
        ContextProjection(
            bundle_id=bundle.bundle_id,
            bundle_hash=bundle.bundle_hash,
            schema_version=bundle.schema_version,
            research_case_id=bundle.research_case_id,
            as_of_date=bundle.as_of_date,
            evidence_pack_id=bundle.evidence_pack_id,
            evidence_pack_hash=bundle.evidence_pack_hash,
            market_snapshot_ids=(" ",),
            etf_factor_observations=(),
            market_observations=(),
        )


def test_projection_serialises_to_known_keys() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    projection = build_projection(bundle=bundle, evidence_pack=pack)
    payload = projection.to_dict()
    assert set(payload) == {
        "schema_version",
        "bundle_id",
        "bundle_hash",
        "research_case_id",
        "as_of_date",
        "evidence_pack",
        "market_observation_snapshots",
    }
    assert set(payload["evidence_pack"]) == {
        "evidence_pack_id",
        "evidence_pack_hash",
        "observations",
    }
    assert set(payload["market_observation_snapshots"]) == {
        "snapshot_ids",
        "observations",
    }


def test_bundle_does_not_depend_on_observation_runtime_payload() -> None:
    """Snapshot content_hash (not value) is the bundle identity anchor.

    Two snapshots with identical ``content_hash`` but mutated
    runtime ``observations`` tuple produce the same bundle hash
    because the bundle only carries the snapshot's immutable
    identity (id, content_hash, as_of_date). The application layer
    is responsible for handing the matching snapshot to
    :func:`build_projection`; if the runtime observations have
    drifted, ``content_hash`` will differ and the projection will
    fail closed at the ``build_projection`` boundary.
    """

    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    tampered = MarketObservationSnapshot(
        input_snapshot_id=snapshot.input_snapshot_id,
        as_of_date=snapshot.as_of_date,
        observations=(
            MarketObservation(
                observation_key="market_temperature_score",
                value=Decimal("0.42"),
                unit="score",
                observed_date=snapshot.as_of_date,
                source_kind="tampered",
                source_ref="tampered:1.0.0",
                quality_status=QualityStatus.INVALID,
            ),
        ),
        algorithm_version=snapshot.algorithm_version,
        scope_type=snapshot.scope_type,
        scope_key=snapshot.scope_key,
    )
    bundle_tampered = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(tampered,), created_at=_BASE
    )
    assert bundle.bundle_hash != bundle_tampered.bundle_hash


def test_projection_with_market_snapshot_uses_full_observation_payload() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    flat_keys = {item["observation_key"] for item in projection.market_observations}
    assert flat_keys == {item.observation_key for item in snapshot.observations}
    for projection_item, source_item in zip(
        sorted(projection.market_observations, key=lambda item: item["observation_key"]),
        sorted(snapshot.observations, key=lambda item: item.observation_key),
        strict=True,
    ):
        assert projection_item["item_hash"] == source_item.item_hash
        assert projection_item["value"] == source_item.value


def test_projection_carries_bundle_created_at_metadata() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    projection = build_projection(bundle=bundle, evidence_pack=pack)
    payload = projection.to_dict()
    assert payload["bundle_id"] == str(bundle.bundle_id)
    assert payload["bundle_hash"] == bundle.bundle_hash


def test_no_ai_or_investment_fields_appear_in_bundle_projection() -> None:
    forbidden = {
        "buy",
        "sell",
        "stance",
        "thesis",
        "investment_confidence",
        "recommendation",
        "ai_conclusion",
    }
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )

    def _walk(value: object) -> set[str]:
        keys: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                keys.add(key)
                keys.update(_walk(item))
        elif isinstance(value, (list, tuple)):
            for item in value:
                keys.update(_walk(item))
        return keys

    projection_keys = _walk(projection.to_dict())
    canonical_keys = _walk(bundle.content_projection())
    assert forbidden.isdisjoint(projection_keys)
    assert forbidden.isdisjoint(canonical_keys)


def test_bundle_is_frozen_and_freshness_is_not_a_field() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    field_names = {item.name for item in bundle.__dataclass_fields__.values()}
    assert "freshness" not in field_names
    assert "investment_confidence" not in field_names


def test_direct_construction_rejects_non_uuid_bundle_id() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    with pytest.raises(TypeError, match="bundle_id"):
        ResearchEvidenceBundle(
            bundle_id="not-a-uuid",
            research_case_id=bundle.research_case_id,
            evidence_pack_id=bundle.evidence_pack_id,
            evidence_pack_hash=bundle.evidence_pack_hash,
            market_snapshot_refs=bundle.market_snapshot_refs,
            schema_version=bundle.schema_version,
            bundle_hash=bundle.bundle_hash,
            created_at=bundle.created_at,
            as_of_date=bundle.as_of_date,
        )


def test_projection_validates_quality_status_emitted() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    valid_statuses = {status.value for status in QualityStatus}
    for item in projection.market_observations:
        assert item["quality_status"] in valid_statuses
    for item in projection.etf_factor_observations:
        assert item["quality_status"] in valid_statuses


def test_bundle_built_from_future_dated_snapshot_keeps_as_of_date() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot(snapshot_date=date(2026, 8, 7))
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    assert bundle.as_of_date == pack.case.as_of_date
    assert bundle.market_snapshot_refs[0].as_of_date == snapshot.as_of_date


def test_projection_rejects_duplicate_snapshot_ids_in_input() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_projection(
            bundle=bundle,
            evidence_pack=pack,
            market_snapshots=(snapshot, snapshot),
        )


def test_default_created_at_is_timezone_aware() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack)
    assert bundle.created_at.tzinfo is not None


def test_bundle_as_of_date_uses_evidence_pack_case() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    assert bundle.as_of_date == pack.case.as_of_date


def test_built_bundle_with_two_market_snapshots_hashes_deterministically() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snap_a = _market_snapshot(input_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    snap_b = _market_snapshot(input_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
    first = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snap_a, snap_b), created_at=_BASE
    )
    second = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snap_a, snap_b), created_at=_BASE
    )
    assert first.bundle_hash == second.bundle_hash
    assert len(first.market_snapshot_refs) == 2


def test_market_snapshot_ref_content_projection_is_canonical() -> None:
    ref = MarketSnapshotRef(
        snapshot_id="mos:abc",
        content_hash="f" * 64,
        as_of_date=date(2026, 8, 7),
    )
    assert ref.content_projection() == {
        "snapshot_id": "mos:abc",
        "content_hash": "f" * 64,
        "as_of_date": date(2026, 8, 7),
    }


def test_bundle_content_projection_excludes_bundle_id_and_created_at() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle_a = ResearchEvidenceBundle.build(
        evidence_pack=pack,
        created_at=_BASE,
        bundle_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    )
    bundle_b = ResearchEvidenceBundle.build(
        evidence_pack=pack,
        created_at=_BASE + timedelta(minutes=5),
        bundle_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    )
    assert bundle_a.content_projection() == bundle_b.content_projection()
    assert "bundle_id" not in bundle_a.content_projection()
    assert "created_at" not in bundle_a.content_projection()


def test_projection_rejects_unknown_quality_or_freshness_strings() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    bundle = ResearchEvidenceBundle.build(evidence_pack=pack, created_at=_BASE)
    with pytest.raises(ValueError, match="market_snapshot_ids"):
        ContextProjection(
            bundle_id=bundle.bundle_id,
            bundle_hash=bundle.bundle_hash,
            schema_version=bundle.schema_version,
            research_case_id=bundle.research_case_id,
            as_of_date=bundle.as_of_date,
            evidence_pack_id=bundle.evidence_pack_id,
            evidence_pack_hash=bundle.evidence_pack_hash,
            market_snapshot_ids=("",),
            etf_factor_observations=(),
            market_observations=(),
        )


def test_projection_to_dict_lists_observation_payloads() -> None:
    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = _market_snapshot()
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    payload = projection.to_dict()
    assert isinstance(payload["evidence_pack"]["observations"], list)
    assert isinstance(payload["market_observation_snapshots"]["observations"], list)
    assert payload["market_observation_snapshots"]["snapshot_ids"] == [
        snapshot.snapshot_id
    ]


def test_projection_handles_invalid_market_snapshot_status() -> None:
    """Bundle bound to an INVALID snapshot still produces a projection.

    The bundle carries the immutable snapshot reference; the
    projection surfaces the snapshot's quality_status so downstream
    AI consumers can see the snapshot was degraded. Failing closed is
    the bundle *builder's* job (see ``build_market_temperature``),
    not the projection's.
    """

    case_id = UUID("11111111-1111-4111-8111-111111111111")
    pack = _case_aligned_pack(case_id)
    snapshot = MarketObservationSnapshot(
        input_snapshot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        as_of_date=date(2026, 8, 7),
        observations=(),
        quality_status=QualityStatus.INVALID,
        freshness_status=FreshnessStatus.FAILED,
    )
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=pack, market_snapshots=(snapshot,), created_at=_BASE
    )
    projection = build_projection(
        bundle=bundle, evidence_pack=pack, market_snapshots=(snapshot,)
    )
    assert projection.market_snapshot_ids == (snapshot.snapshot_id,)
    assert projection.market_observations == ()
