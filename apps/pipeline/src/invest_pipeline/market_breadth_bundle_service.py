"""Pipeline application service that binds a Market Breadth snapshot to a ResearchEvidenceBundle.

Stage 4B Market Breadth -> ResearchEvidenceBundle wiring (smallest
complete vertical cut):

* Reads the immutable :class:`invest_domain.research.models.EvidencePack`
  by ``evidence_pack_id`` through the existing
  :class:`invest_storage.repositories.SqlAlchemyEvidencePackRepository`
  read path (no new table / migration);
* Looks up the latest
  :class:`invest_domain.analytics.market_observations.MarketObservationSnapshot`
  for the pinned Market Breadth scope (``scope_type="ashare_universe"``,
  ``scope_key="ashare_active_universe_v1"``) on the case's
  ``as_of_date`` so the bundle's snapshot identity is anchored to the
  case business date;
* Fails closed when the snapshot is missing, when the snapshot's
  ``as_of_date`` drifts from the case's ``as_of_date``, or when the
  snapshot is not ``quality_status=COMPLETE`` / ``freshness_status=FRESH``;
* Hands the case, the pack, and the (single) snapshot to the pure-domain
  :meth:`invest_domain.research.evidence_bundle.ResearchEvidenceBundle.build`
  factory so the bundle hash is derived from the canonical sources;
* Persists the bundle through the existing
  :class:`invest_storage.repositories.SqlAlchemyResearchEvidenceBundleRepository`
  ``add`` path inside a single Unit-of-Work transaction.

The service deliberately does not touch the provider / HTTP / AI layers:
it is a pure application-layer use case that brokers between the
already-published Market Breadth snapshot and the audit-grade bundle
identity. It is not wired into the existing
:class:`invest_pipeline.research_orchestration_service.ResearchOrchestrationService`
because that orchestrator still follows the PR-6 / Slice 3 contract and
the bundle-side wiring belongs to a separate slice (this module owns
its own service entry point so callers can opt in incrementally).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID

from invest_domain.analytics.market_observations import MarketObservationSnapshot
from invest_domain.research import EvidencePack, ResearchEvidenceBundle
from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_storage.unit_of_work import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]

MARKET_BREADTH_SCOPE_TYPE: Final[str] = "ashare_universe"
MARKET_BREADTH_SCOPE_KEY: Final[str] = "ashare_active_universe_v1"

__all__ = [
    "MARKET_BREADTH_SCOPE_KEY",
    "MARKET_BREADTH_SCOPE_TYPE",
    "MarketBreadthBundleInputError",
    "MarketBreadthBundleInvariantError",
    "MarketBreadthBundleSnapshotMissingError",
    "MarketBreadthBundleEvidencePackMissingError",
    "UnitOfWorkFactory",
    "build_and_persist_market_breadth_bundle",
]


class MarketBreadthBundleEvidencePackMissingError(ValueError):
    """Raised when the referenced :class:`EvidencePack` does not exist.

    The error carries the ``evidence_pack_id`` so the calling layer can
    surface a deterministic 4xx (or operator-visible task failure)
    without leaking storage details. The original cause is preserved
    via :keyword:`raise ... from exc` so operators can still inspect the
    storage trace.
    """

    def __init__(self, message: str, *, evidence_pack_id: UUID) -> None:
        super().__init__(message)
        self.evidence_pack_id = evidence_pack_id


class MarketBreadthBundleSnapshotMissingError(ValueError):
    """Raised when no Market Breadth snapshot exists for the requested case date.

    The error carries the case ``as_of_date`` so callers can distinguish
    a missing-snapshot failure from a quality / drift failure without
    parsing the message string.
    """

    def __init__(
        self,
        message: str,
        *,
        as_of_date,
        scope_type: str,
        scope_key: str,
    ) -> None:
        super().__init__(message)
        self.as_of_date = as_of_date
        self.scope_type = scope_type
        self.scope_key = scope_key


class MarketBreadthBundleInvariantError(ValueError):
    """Raised when the resolved Market Breadth snapshot breaks the bundle contract.

    The single failure class covers every "the snapshot exists but
    cannot be bound" reason: an ``as_of_date`` mismatch with the case,
    a non-``COMPLETE`` ``quality_status``, a non-``FRESH``
    ``freshness_status``, or a content-hash / scope drift. The structured
    attributes below let the calling layer pick a deterministic HTTP /
    Dagster response without parsing the message string, while the
    message itself stays operator-friendly.
    """

    def __init__(
        self,
        message: str,
        *,
        snapshot_id: str,
        snapshot_as_of_date,
        case_as_of_date,
        quality_status: QualityStatus | str,
        freshness_status: FreshnessStatus | str,
        reason: str,
    ) -> None:
        super().__init__(message)
        self.snapshot_id = snapshot_id
        self.snapshot_as_of_date = snapshot_as_of_date
        self.case_as_of_date = case_as_of_date
        self.quality_status = quality_status
        self.freshness_status = freshness_status
        self.reason = reason


class MarketBreadthBundleInputError(ValueError):
    """Raised when the caller's arguments are structurally invalid.

    The service rejects ``None`` / empty ``evidence_pack_id`` and a
    non-datetime ``created_at`` so the upstream caller fails loudly
    instead of producing a silently mis-stamped bundle row.
    """


def _validate_snapshot_for_bundle(
    *,
    snapshot: MarketObservationSnapshot,
    case_as_of_date,
) -> None:
    """Reject snapshots that cannot be bound to ``case_as_of_date``.

    Every branch raises :class:`MarketBreadthBundleInvariantError` so the
    service has a single failure path for "snapshot exists but cannot be
    bound", and each branch tags the structured :attr:`reason` so the
    calling layer does not have to parse the message.
    """

    snapshot_id = snapshot.snapshot_id or "<unknown>"
    if snapshot.as_of_date != case_as_of_date:
        raise MarketBreadthBundleInvariantError(
            (
                f"Market Breadth snapshot {snapshot_id!r} as_of_date "
                f"{snapshot.as_of_date.isoformat()!r} does not match the "
                f"case as_of_date {case_as_of_date.isoformat()!r}; refusing "
                "to bind a bundle whose market-snapshot identity drifts "
                "from the ResearchCase business date"
            ),
            snapshot_id=snapshot_id,
            snapshot_as_of_date=snapshot.as_of_date,
            case_as_of_date=case_as_of_date,
            quality_status=snapshot.quality_status,
            freshness_status=snapshot.freshness_status,
            reason="as_of_mismatch",
        )
    if snapshot.quality_status is not QualityStatus.COMPLETE:
        raise MarketBreadthBundleInvariantError(
            (
                f"Market Breadth snapshot {snapshot_id!r} quality_status "
                f"{snapshot.quality_status.value!r} is not COMPLETE; "
                "refusing to bind a bundle from an incomplete observation"
            ),
            snapshot_id=snapshot_id,
            snapshot_as_of_date=snapshot.as_of_date,
            case_as_of_date=case_as_of_date,
            quality_status=snapshot.quality_status,
            freshness_status=snapshot.freshness_status,
            reason="quality_not_complete",
        )
    if snapshot.freshness_status is not FreshnessStatus.FRESH:
        raise MarketBreadthBundleInvariantError(
            (
                f"Market Breadth snapshot {snapshot_id!r} freshness_status "
                f"{snapshot.freshness_status.value!r} is not FRESH; "
                "refusing to bind a bundle from a stale observation"
            ),
            snapshot_id=snapshot_id,
            snapshot_as_of_date=snapshot.as_of_date,
            case_as_of_date=case_as_of_date,
            quality_status=snapshot.quality_status,
            freshness_status=snapshot.freshness_status,
            reason="freshness_not_fresh",
        )


def _ensure_aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise MarketBreadthBundleInputError(
            f"{field_name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise MarketBreadthBundleInputError(
            f"{field_name} must be a timezone-aware datetime"
        )
    return value


def build_and_persist_market_breadth_bundle(
    *,
    uow_factory: UnitOfWorkFactory,
    evidence_pack_id: UUID,
    created_at: datetime | None = None,
) -> ResearchEvidenceBundle:
    """Bind the Market Breadth snapshot for ``evidence_pack_id`` and persist the bundle.

    Parameters
    ----------
    uow_factory:
        Callable returning a fresh :class:`UnitOfWork`. The service
        opens exactly one UoW so the bundle read + bundle write happen
        inside a single transaction; a failure on either side rolls the
        whole transaction back.
    evidence_pack_id:
        The UUID of the :class:`EvidencePack` the caller previously
        persisted. The pack is the immutable 8-factor contract; the
        service treats its identity as the bundle's upstream anchor.
    created_at:
        Optional timezone-aware ``datetime`` stamped on the bundle.
        Defaults to the current UTC time when omitted so a same-input
        re-run still produces a distinct ``bundle_id`` but a stable
        ``bundle_hash`` (the hash deliberately excludes ``created_at``;
        see :meth:`ResearchEvidenceBundle.content_projection`). Tests
        pass an explicit ``created_at`` to keep the ``bundle_id``
        deterministic.

    Returns
    -------
    ResearchEvidenceBundle
        The freshly-persisted bundle row. The repository's
        :meth:`SqlAlchemyResearchEvidenceBundleRepository.add` is
        idempotent on ``bundle_hash``, so a same-input re-run returns
        the canonical bundle instead of producing a duplicate row.

    Raises
    ------
    MarketBreadthBundleEvidencePackMissingError
        The ``evidence_pack_id`` does not exist in storage.
    MarketBreadthBundleSnapshotMissingError
        No Market Breadth snapshot exists for the case's ``as_of_date``
        on the pinned scope.
    MarketBreadthBundleInvariantError
        The resolved snapshot has a non-matching ``as_of_date`` or
        carries a non-``COMPLETE`` / non-``FRESH`` status.
    MarketBreadthBundleInputError
        ``evidence_pack_id`` is not a UUID or ``created_at`` is not a
        timezone-aware datetime.
    """

    if not isinstance(evidence_pack_id, UUID):
        raise MarketBreadthBundleInputError(
            "evidence_pack_id must be a UUID, "
            f"got {type(evidence_pack_id).__name__}"
        )
    if created_at is not None:
        _ensure_aware_utc(created_at, "created_at")

    with uow_factory() as uow:
        try:
            evidence_pack: EvidencePack | None = (
                uow.research_evidence_packs.get_by_id(evidence_pack_id)
            )
        except Exception as exc:
            raise MarketBreadthBundleEvidencePackMissingError(
                (
                    f"EvidencePack {evidence_pack_id!s} could not be loaded "
                    f"from storage: {exc}"
                ),
                evidence_pack_id=evidence_pack_id,
            ) from exc
        if evidence_pack is None:
            raise MarketBreadthBundleEvidencePackMissingError(
                f"EvidencePack {evidence_pack_id!s} was not found in storage",
                evidence_pack_id=evidence_pack_id,
            )

        case_as_of_date = evidence_pack.case.as_of_date
        try:
            snapshot: MarketObservationSnapshot | None = (
                uow.market_observation_snapshots.get_latest_for_scope(
                    MARKET_BREADTH_SCOPE_TYPE,
                    MARKET_BREADTH_SCOPE_KEY,
                    case_as_of_date,
                )
            )
        except Exception as exc:
            raise MarketBreadthBundleSnapshotMissingError(
                (
                    f"Market Breadth snapshot lookup failed for "
                    f"{MARKET_BREADTH_SCOPE_TYPE!r}/{MARKET_BREADTH_SCOPE_KEY!r} "
                    f"on as_of_date {case_as_of_date.isoformat()!r}: {exc}"
                ),
                as_of_date=case_as_of_date,
                scope_type=MARKET_BREADTH_SCOPE_TYPE,
                scope_key=MARKET_BREADTH_SCOPE_KEY,
            ) from exc
        if snapshot is None:
            raise MarketBreadthBundleSnapshotMissingError(
                (
                    f"No Market Breadth snapshot found for "
                    f"{MARKET_BREADTH_SCOPE_TYPE!r}/{MARKET_BREADTH_SCOPE_KEY!r} "
                    f"on as_of_date {case_as_of_date.isoformat()!r}"
                ),
                as_of_date=case_as_of_date,
                scope_type=MARKET_BREADTH_SCOPE_TYPE,
                scope_key=MARKET_BREADTH_SCOPE_KEY,
            )

        _validate_snapshot_for_bundle(
            snapshot=snapshot, case_as_of_date=case_as_of_date
        )

        bundle = ResearchEvidenceBundle.build(
            evidence_pack=evidence_pack,
            market_snapshots=(snapshot,),
            created_at=created_at,
        )
        persisted = uow.research_evidence_bundles.add(bundle)
        uow.commit()
    return persisted
