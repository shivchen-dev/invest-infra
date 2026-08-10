"""Pure domain model for the Research Evidence Bundle (Stage 4B Phase 3).

The :class:`ResearchEvidenceBundle` value object binds one Research
Case's immutable evidence identity to:

- the existing :class:`invest_domain.research.models.EvidencePack`
  (8-factor ETF contract preserved unchanged), referenced by
  ``evidence_pack_id`` and ``pack_hash``;
- zero or more Analytics-owned
  :class:`invest_domain.analytics.market_observations.MarketObservationSnapshot`
  records, referenced by ``market_snapshot_ids`` plus the snapshot
  ``content_hash`` values;
- the bundle ``schema_version`` so historical bundles remain
  interpretable after the projection rule changes;
- a deterministic ``bundle_hash`` that binds the Research Case
  identity, the as-of date, the upstream evidence identity and the
  schema version together.

The :class:`ContextProjection` DTO/serializer rebuilds a flat,
AI-consumable projection of the bundle plus the supplied immutable
evidence values. Per Stage 4B §2.5 the projection is read-only,
rebuildable, and emits every fact's ``evidence_id`` / source /
observed date / quality / hash so a downstream AI consumer can
attribute every claim back to the bundle. No business fact is owned
by the projection: changing any upstream field produces a new bundle
identity, and a corresponding new projection.

The domain layer remains infrastructure-free: no SQLAlchemy, no
Alembic, no FastAPI, no Dagster. Persistence is wired in
``packages/storage``; this module owns the contract only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from invest_domain.research.models import EvidencePack
from invest_domain.shared.canonical import canonical_json, canonical_sha256

if TYPE_CHECKING:
    from invest_domain.analytics.market_observations import (
        MarketObservation,
        MarketObservationSnapshot,
    )

BUNDLE_SCHEMA_VERSION: str = "1.0.0"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _load_market_observation_classes() -> tuple[type, type]:
    """Lazy-load the Analytics-owned observation value objects.

    Loading ``invest_domain.analytics.market_observations`` at module
    import time re-enters :mod:`invest_domain.analytics.__init__`,
    which transitively pulls :mod:`invest_domain.research.__init__`
    (for the ``FreshnessStatus`` / ``QualityStatus`` enum re-exports)
    and creates a circular import. The Analytics package only depends
    on this module via the ``evidence_bundle`` import, so deferring
    the symbol load to first use keeps both packages importable while
    the ``invest_domain`` top-level package is still initialising.
    """

    from invest_domain.analytics.market_observations import (
        MarketObservation,
        MarketObservationSnapshot,
    )

    return MarketObservation, MarketObservationSnapshot


@dataclass(frozen=True, slots=True)
class MarketSnapshotRef:
    """One entry of :attr:`ResearchEvidenceBundle.market_snapshot_ids`.

    The bundle does not own the snapshot's child observations; the
    caller (application layer) must hand the full
    :class:`MarketObservationSnapshot` to :meth:`ResearchEvidenceBundle
    .build_projection` so the projection can include the observation
    detail. The bundle only carries the immutable identifiers and the
    snapshot's deterministic ``content_hash`` so two bundles cannot
    silently disagree on which observation they bind.
    """

    snapshot_id: str
    content_hash: str
    as_of_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id.strip():
            raise ValueError(
                "MarketSnapshotRef.snapshot_id must be a non-empty string"
            )
        if not isinstance(self.content_hash, str) or len(self.content_hash) != 64:
            raise ValueError(
                "MarketSnapshotRef.content_hash must be a 64-character hash string"
            )
        if not isinstance(self.as_of_date, date):
            raise TypeError(
                "MarketSnapshotRef.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )

    def content_projection(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "content_hash": self.content_hash,
            "as_of_date": self.as_of_date,
        }


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundle:
    """Immutable binding of one Research Case's evidence identity.

    The bundle deliberately does **not** carry the EvidencePack
    payload or the MarketObservation snapshots themselves; it only
    carries the immutable identifiers and content hashes that pin the
    bundle's evidence identity. The application layer re-reads the
    upstream evidence on demand and feeds it to
    :meth:`build_projection` so the projection can be regenerated
    from the canonical sources.

    Construction invariants:

    - ``bundle_id`` is a :class:`UUID`.
    - ``research_case_id`` is a :class:`UUID` and equals
      ``evidence_pack.case.case_id`` (which must itself be a UUID).
    - ``evidence_pack_id`` is a :class:`UUID` and equals
      ``evidence_pack.pack_id`` (which must not be ``None``).
    - ``evidence_pack_hash`` equals ``evidence_pack.pack_hash``.
    - ``market_snapshot_refs`` is a tuple of :class:`MarketSnapshotRef`
      in deterministic order (sorted by ``snapshot_id``).
    - ``schema_version`` equals :data:`BUNDLE_SCHEMA_VERSION` (the
      first contract version freezes at ``"1.0.0"``).
    - ``bundle_hash`` is a 64-character hex digest derived from the
      canonical projection; supplying a mismatching hash fails closed.
    - ``created_at`` is a timezone-aware :class:`datetime``.
    """

    bundle_id: UUID
    research_case_id: UUID
    evidence_pack_id: UUID
    evidence_pack_hash: str
    market_snapshot_refs: tuple[MarketSnapshotRef, ...]
    schema_version: str
    bundle_hash: str
    created_at: datetime
    as_of_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_id, UUID):
            raise TypeError(
                "ResearchEvidenceBundle.bundle_id must be a UUID, "
                f"got {type(self.bundle_id).__name__}"
            )
        if not isinstance(self.research_case_id, UUID):
            raise TypeError(
                "ResearchEvidenceBundle.research_case_id must be a UUID, "
                f"got {type(self.research_case_id).__name__}"
            )
        if not isinstance(self.evidence_pack_id, UUID):
            raise TypeError(
                "ResearchEvidenceBundle.evidence_pack_id must be a UUID, "
                f"got {type(self.evidence_pack_id).__name__}"
            )
        if (
            not isinstance(self.evidence_pack_hash, str)
            or len(self.evidence_pack_hash) != 64
        ):
            raise ValueError(
                "ResearchEvidenceBundle.evidence_pack_hash must be a "
                "64-character hash string"
            )
        if self.schema_version != BUNDLE_SCHEMA_VERSION:
            raise ValueError(
                f"ResearchEvidenceBundle.schema_version must be "
                f"{BUNDLE_SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        if not isinstance(self.bundle_hash, str):
            raise TypeError(
                "ResearchEvidenceBundle.bundle_hash must be a string, "
                f"got {type(self.bundle_hash).__name__}"
            )
        if self.bundle_hash and len(self.bundle_hash) != 64:
            raise ValueError(
                "ResearchEvidenceBundle.bundle_hash must be a 64-character "
                "hash string"
            )
        if not isinstance(self.market_snapshot_refs, tuple):
            raise ValueError(
                "ResearchEvidenceBundle.market_snapshot_refs must be a tuple "
                "of MarketSnapshotRef instances"
            )
        for entry in self.market_snapshot_refs:
            if not isinstance(entry, MarketSnapshotRef):
                raise TypeError(
                    "ResearchEvidenceBundle.market_snapshot_refs must contain "
                    "only MarketSnapshotRef instances, "
                    f"got {type(entry).__name__}"
                )
        if not isinstance(self.as_of_date, date):
            raise TypeError(
                "ResearchEvidenceBundle.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )
        _require_aware(self.created_at, "ResearchEvidenceBundle.created_at")
        if self.bundle_hash:
            computed = compute_bundle_hash(self)
            if self.bundle_hash != computed:
                raise ValueError(
                    "ResearchEvidenceBundle.bundle_hash does not match its "
                    "canonical content"
                )
            object.__setattr__(self, "bundle_hash", computed)

    @classmethod
    def build(
        cls,
        *,
        evidence_pack: EvidencePack,
        market_snapshots: tuple[MarketObservationSnapshot, ...] = (),
        bundle_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> ResearchEvidenceBundle:
        """Build a fresh :class:`ResearchEvidenceBundle`.

        The factory derives every identifier and hash from the supplied
        upstream evidence so the storage layer never has to recompute
        the canonical digest. ``created_at`` defaults to ``None``,
        which forces the factory to stamp the current UTC time; tests
        pass an explicit timezone-aware ``created_at`` to keep the
        bundle hash deterministic.

        Raises ``ValueError`` if the ``EvidencePack`` has no
        ``pack_id``, the pack's ``case.case_id`` is not a UUID, or any
        market snapshot's ``content_hash`` is missing.
        """

        _, MarketObservationSnapshot = _load_market_observation_classes()
        if evidence_pack.pack_id is None:
            raise ValueError(
                "ResearchEvidenceBundle.build requires an EvidencePack with "
                "a non-null pack_id"
            )
        pack_case_id = evidence_pack.case.case_id
        if not isinstance(pack_case_id, UUID):
            raise ValueError(
                "ResearchEvidenceBundle.build requires EvidencePack.case."
                "case_id to be a UUID"
            )
        ordered_refs: list[MarketSnapshotRef] = []
        seen_snapshot_ids: set[str] = set()
        for snapshot in market_snapshots:
            if not isinstance(snapshot, MarketObservationSnapshot):
                raise TypeError(
                    "ResearchEvidenceBundle.build market_snapshots must "
                    "contain MarketObservationSnapshot instances, "
                    f"got {type(snapshot).__name__}"
                )
            if snapshot.snapshot_id in seen_snapshot_ids:
                raise ValueError(
                    "ResearchEvidenceBundle.build received duplicate "
                    f"snapshot_id {snapshot.snapshot_id!r}"
                )
            seen_snapshot_ids.add(snapshot.snapshot_id)
            ordered_refs.append(
                MarketSnapshotRef(
                    snapshot_id=snapshot.snapshot_id,
                    content_hash=snapshot.content_hash,
                    as_of_date=snapshot.as_of_date,
                )
            )
        ordered_refs.sort(key=lambda item: item.snapshot_id)
        if created_at is None:
            from datetime import UTC

            created_at = datetime.now(UTC)
        else:
            _require_aware(created_at, "created_at")
        bundle = cls(
            bundle_id=bundle_id or uuid4(),
            research_case_id=pack_case_id,
            evidence_pack_id=evidence_pack.pack_id,
            evidence_pack_hash=evidence_pack.pack_hash,
            market_snapshot_refs=tuple(ordered_refs),
            schema_version=BUNDLE_SCHEMA_VERSION,
            bundle_hash="",
            created_at=created_at,
            as_of_date=evidence_pack.case.as_of_date,
        )
        computed_hash = compute_bundle_hash(bundle)
        object.__setattr__(bundle, "bundle_hash", computed_hash)
        return bundle

    def content_projection(self) -> dict[str, Any]:
        """Return the canonical projection used to compute ``bundle_hash``.

        The projection deliberately excludes ``bundle_id`` and
        ``created_at`` so two bundles built from the same upstream
        evidence at different times still hash identically. The
        identity is owned by the storage row, not the content.
        """

        return {
            "schema_version": self.schema_version,
            "research_case_id": str(self.research_case_id),
            "as_of_date": self.as_of_date,
            "evidence_pack_id": str(self.evidence_pack_id),
            "evidence_pack_hash": self.evidence_pack_hash,
            "market_snapshot_refs": [
                item.content_projection() for item in self.market_snapshot_refs
            ],
        }


def compute_bundle_hash(bundle: ResearchEvidenceBundle) -> str:
    """Return the lowercase hex SHA-256 digest of ``bundle``."""

    return canonical_sha256(bundle.content_projection())


def canonical_bundle_json(bundle: ResearchEvidenceBundle) -> str:
    """Return the deterministic JSON serialization of ``bundle``."""

    return canonical_json(bundle.content_projection())


def _factor_evidence_projection(pack: EvidencePack) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item.evidence_id,
            "evidence_key": item.evidence_key,
            "evidence_type": "factor_observation",
            "factor_key": item.factor_key,
            "observed_date": item.observed_date,
            "quality_status": item.quality_status.value,
            "source_kind": item.source_kind,
            "source_ref": item.source_ref,
            "item_hash": item.item_hash,
            "value": item.value,
            "unit": item.unit,
            "window": item.window,
        }
        for item in sorted(pack.factors, key=lambda factor: factor.factor_key)
    ]


def _market_observation_projection(
    observation: MarketObservation,
) -> dict[str, Any]:
    return {
        "evidence_id": f"mos:{observation.item_hash[:12]}:{observation.observation_key}",
        "evidence_key": f"market_observation.{observation.observation_key}",
        "evidence_type": "market_observation",
        "observation_key": observation.observation_key,
        "observed_date": observation.observed_date,
        "quality_status": observation.quality_status.value,
        "source_kind": observation.source_kind,
        "source_ref": observation.source_ref,
        "item_hash": observation.item_hash,
        "value": observation.value,
        "unit": observation.unit,
    }


def _market_snapshot_projection(
    snapshot: MarketObservationSnapshot,
) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "content_hash": snapshot.content_hash,
        "as_of_date": snapshot.as_of_date,
        "scope_type": snapshot.scope_type,
        "scope_key": snapshot.scope_key,
        "algorithm_version": snapshot.algorithm_version,
        "quality_status": snapshot.quality_status.value,
        "freshness_status": snapshot.freshness_status.value,
        "observations": [
            _market_observation_projection(item)
            for item in sorted(
                snapshot.observations, key=lambda item: item.observation_key
            )
        ],
    }


@dataclass(frozen=True, slots=True)
class ContextProjection:
    """Read-only, rebuildable view of a :class:`ResearchEvidenceBundle`.

    The projection is the AI-consumable shape defined by Stage 4B
    §2.5: it emits every fact's ``evidence_id`` / source / observed
    date / quality / hash so downstream agents can attribute each
    claim back to the bundle. The projection does not own any
    business fact — changing any upstream field produces a new bundle
    identity and therefore a new projection.
    """

    bundle_id: UUID
    bundle_hash: str
    schema_version: str
    research_case_id: UUID
    as_of_date: date
    evidence_pack_id: UUID
    evidence_pack_hash: str
    market_snapshot_ids: tuple[str, ...]
    etf_factor_observations: tuple[dict[str, Any], ...]
    market_observations: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_id, UUID):
            raise TypeError(
                "ContextProjection.bundle_id must be a UUID, "
                f"got {type(self.bundle_id).__name__}"
            )
        if (
            not isinstance(self.bundle_hash, str)
            or len(self.bundle_hash) != 64
        ):
            raise ValueError(
                "ContextProjection.bundle_hash must be a 64-character hash string"
            )
        if self.schema_version != BUNDLE_SCHEMA_VERSION:
            raise ValueError(
                f"ContextProjection.schema_version must be "
                f"{BUNDLE_SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        if not isinstance(self.research_case_id, UUID):
            raise TypeError(
                "ContextProjection.research_case_id must be a UUID, "
                f"got {type(self.research_case_id).__name__}"
            )
        if not isinstance(self.as_of_date, date):
            raise TypeError(
                "ContextProjection.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )
        if not isinstance(self.evidence_pack_id, UUID):
            raise TypeError(
                "ContextProjection.evidence_pack_id must be a UUID, "
                f"got {type(self.evidence_pack_id).__name__}"
            )
        if (
            not isinstance(self.evidence_pack_hash, str)
            or len(self.evidence_pack_hash) != 64
        ):
            raise ValueError(
                "ContextProjection.evidence_pack_hash must be a 64-character "
                "hash string"
            )
        if not isinstance(self.market_snapshot_ids, tuple):
            raise ValueError(
                "ContextProjection.market_snapshot_ids must be a tuple of "
                "non-empty strings"
            )
        for entry in self.market_snapshot_ids:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(
                    "ContextProjection.market_snapshot_ids must contain only "
                    "non-empty strings"
                )
        for entry in self.etf_factor_observations:
            if not isinstance(entry, dict):
                raise ValueError(
                    "ContextProjection.etf_factor_observations must contain "
                    "only dict entries"
                )
        for entry in self.market_observations:
            if not isinstance(entry, dict):
                raise ValueError(
                    "ContextProjection.market_observations must contain only "
                    "dict entries"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": str(self.bundle_id),
            "bundle_hash": self.bundle_hash,
            "research_case_id": str(self.research_case_id),
            "as_of_date": self.as_of_date,
            "evidence_pack": {
                "evidence_pack_id": str(self.evidence_pack_id),
                "evidence_pack_hash": self.evidence_pack_hash,
                "observations": list(self.etf_factor_observations),
            },
            "market_observation_snapshots": {
                "snapshot_ids": list(self.market_snapshot_ids),
                "observations": list(self.market_observations),
            },
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def build_projection(
    *,
    bundle: ResearchEvidenceBundle,
    evidence_pack: EvidencePack,
    market_snapshots: tuple[MarketObservationSnapshot, ...] = (),
) -> ContextProjection:
    """Rebuild a :class:`ContextProjection` from the bundle + evidence.

    The projection is deterministic — same bundle + same upstream
    evidence produces the same :class:`ContextProjection.to_json`
    bytes. The validation guards catch every common upstream drift:

    - the supplied ``evidence_pack`` must be the bundle's bound pack
      (``pack_id`` and ``pack_hash`` must match);
    - every market snapshot referenced by ``bundle.market_snapshot_refs``
      must appear in ``market_snapshots`` with a matching ``content_hash``;
    - snapshots provided in ``market_snapshots`` but not referenced by
      the bundle are rejected so a stale snapshot cannot silently leak
      into the AI input.
    """

    _, MarketObservationSnapshot = _load_market_observation_classes()
    if evidence_pack.pack_id != bundle.evidence_pack_id:
        raise ValueError(
            "build_projection evidence_pack.pack_id does not match "
            f"bundle.evidence_pack_id ({evidence_pack.pack_id!s} != "
            f"{bundle.evidence_pack_id!s})"
        )
    if evidence_pack.pack_hash != bundle.evidence_pack_hash:
        raise ValueError(
            "build_projection evidence_pack.pack_hash does not match "
            "bundle.evidence_pack_hash"
        )
    provided: dict[str, MarketObservationSnapshot] = {}
    for snapshot in market_snapshots:
        if not isinstance(snapshot, MarketObservationSnapshot):
            raise TypeError(
                "build_projection market_snapshots must contain "
                "MarketObservationSnapshot instances, "
                f"got {type(snapshot).__name__}"
            )
        if snapshot.snapshot_id in provided:
            raise ValueError(
                "build_projection market_snapshots contains a duplicate "
                f"snapshot_id {snapshot.snapshot_id!r}"
            )
        provided[snapshot.snapshot_id] = snapshot
    ordered_snapshots: list[MarketObservationSnapshot] = []
    observation_projections: list[dict[str, Any]] = []
    for ref in bundle.market_snapshot_refs:
        snapshot = provided.get(ref.snapshot_id)
        if snapshot is None:
            raise ValueError(
                "build_projection is missing the MarketObservationSnapshot "
                f"with snapshot_id {ref.snapshot_id!r}"
            )
        if snapshot.content_hash != ref.content_hash:
            raise ValueError(
                "build_projection MarketObservationSnapshot.content_hash "
                f"for snapshot_id {snapshot.snapshot_id!r} does not match "
                "bundle.market_snapshot_refs"
            )
        if snapshot.as_of_date != ref.as_of_date:
            raise ValueError(
                "build_projection MarketObservationSnapshot.as_of_date "
                f"for snapshot_id {snapshot.snapshot_id!r} does not match "
                "bundle.market_snapshot_refs"
            )
        ordered_snapshots.append(snapshot)
        observation_projections.append(_market_snapshot_projection(snapshot))
    extra = set(provided) - {ref.snapshot_id for ref in bundle.market_snapshot_refs}
    if extra:
        raise ValueError(
            "build_projection received MarketObservationSnapshot ids not "
            f"bound by the bundle: {sorted(extra)}"
        )
    market_observations_flat: tuple[dict[str, Any], ...] = tuple(
        observation
        for snapshot in ordered_snapshots
        for observation in _market_snapshot_projection(snapshot)["observations"]
    )
    return ContextProjection(
        bundle_id=bundle.bundle_id,
        bundle_hash=bundle.bundle_hash,
        schema_version=bundle.schema_version,
        research_case_id=bundle.research_case_id,
        as_of_date=bundle.as_of_date,
        evidence_pack_id=bundle.evidence_pack_id,
        evidence_pack_hash=bundle.evidence_pack_hash,
        market_snapshot_ids=tuple(ref.snapshot_id for ref in bundle.market_snapshot_refs),
        etf_factor_observations=tuple(_factor_evidence_projection(evidence_pack)),
        market_observations=market_observations_flat,
    )


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "ContextProjection",
    "MarketSnapshotRef",
    "ResearchEvidenceBundle",
    "build_projection",
    "canonical_bundle_json",
    "compute_bundle_hash",
]
