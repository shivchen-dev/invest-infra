"""Stage 4B Phase 3 context-projection loader for ResearchEvidenceBundle.

The helper :func:`load_context_projection` is the application-layer
gateway between the persistence layer (ResearchEvidenceBundle rows +
MarketObservationSnapshot rows) and the pure-domain
:func:`invest_domain.research.evidence_bundle.build_projection`
factory.

The function is intentionally read-only: it never opens its own UoW
transaction and never commits. Callers enter a UoW (read-only or
otherwise), pre-load the ``case`` / ``run`` / ``evidence_pack`` trio
through the orchestration service's Tx1 path, and then hand the
already-opened UoW plus the trio to this helper to rebuild the
:class:`ContextProjection` deterministically.

Failures fail closed:

- A ``run`` with no ``evidence_bundle_id`` cannot silently downgrade
  to a no-op projection; the helper raises a :class:`ValueError`
  instructing the caller to opt out explicitly (i.e. by checking the
  field before invoking).
- A missing bundle row, missing snapshot row, or any mismatch on
  bundle id / case id / pack id / pack hash / as-of date / snapshot
  id / snapshot content hash / snapshot as-of date / snapshot
  quality / snapshot freshness raises a :class:`ValueError`. The
  domain :func:`build_projection` then re-validates the supplied
  upstream evidence so a stale snapshot cannot leak into the AI
  input even if the storage read lies.
"""

from __future__ import annotations

from uuid import UUID

from invest_domain.analytics.market_observations import (
    MarketObservationSnapshot,
)
from invest_domain.research.evidence_bundle import (
    ContextProjection,
    ResearchEvidenceBundle,
    build_projection,
)
from invest_domain.research.models import (
    EvidencePack,
    FreshnessStatus,
    QualityStatus,
)
from invest_domain.research.research_case import ResearchCase
from invest_domain.research.research_run import ResearchRun
from invest_storage.unit_of_work import UnitOfWork

__all__ = [
    "ContextProjectionLoadError",
    "load_context_projection",
]


class ContextProjectionLoadError(ValueError):
    """Raised when a :class:`ContextProjection` cannot be rebuilt safely.

    All failure modes that cross the storage / domain boundary —
    missing bundle row, missing snapshot row, id / hash / date /
    quality drift — surface as this single exception type so the
    calling Dagster asset / API can fail closed with one handler.
    """


def _fail(message: str) -> None:
    """Raise :class:`ContextProjectionLoadError` with a deterministic prefix."""

    raise ContextProjectionLoadError(message)


def load_context_projection(
    uow: UnitOfWork,
    *,
    case: ResearchCase,
    run: ResearchRun,
    evidence_pack: EvidencePack,
) -> ContextProjection:
    """Rebuild the :class:`ContextProjection` for ``run`` from storage.

    The helper takes an already-opened :class:`UnitOfWork` plus the
    ``case`` / ``run`` / ``evidence_pack`` trio loaded by the
    orchestrator's Tx1 path. It does not open its own transaction
    and does not call ``commit`` / ``rollback``; the caller owns
    the transaction boundary.

    Returns the deterministic :class:`ContextProjection` produced
    by :func:`invest_domain.research.evidence_bundle.build_projection`
    so a downstream AI consumer can attribute every claim back to
    the bundle.

    Raises :class:`ContextProjectionLoadError` (a :class:`ValueError`)
    when:

    - ``run.evidence_bundle_id`` is ``None`` (caller must opt out
      explicitly before invoking this helper);
    - the bundle row referenced by ``run.evidence_bundle_id`` is
      not found in storage;
    - the loaded bundle's ``bundle_id`` does not equal
      ``run.evidence_bundle_id``;
    - the bundle's ``research_case_id`` does not equal
      ``case.case_id``;
    - the bundle's ``evidence_pack_id`` / ``evidence_pack_hash`` do
      not equal ``evidence_pack.pack_id`` / ``evidence_pack.pack_hash``;
    - the bundle's ``as_of_date`` does not equal
      ``case.as_of_date`` (which must itself equal
      ``evidence_pack.case.as_of_date``);
    - any :class:`invest_domain.analytics.market_observations.MarketObservationSnapshot`
      referenced by ``bundle.market_snapshot_refs`` is not found by
      ``content_hash`` in storage;
    - the loaded snapshot's ``snapshot_id`` /
      ``content_hash`` / ``as_of_date`` / ``quality_status`` /
      ``freshness_status`` drift from the bundle's
      ``MarketSnapshotRef`` or from the required ``COMPLETE`` /
      ``FRESH`` status pair.
    """

    if run.evidence_bundle_id is None:
        _fail(
            "load_context_projection refuses to load a projection when "
            "ResearchRun.evidence_bundle_id is None; callers must opt "
            "out explicitly (check the field before invoking this helper) "
            f"for run {run.run_id!s} / case {case.case_id!s}"
        )

    bundle_id: UUID = run.evidence_bundle_id
    bundle = uow.research_evidence_bundles.get_by_id(bundle_id)
    if bundle is None:
        _fail(
            f"load_context_projection did not find ResearchEvidenceBundle "
            f"{bundle_id!s} referenced by ResearchRun {run.run_id!s}"
        )
    if not isinstance(bundle, ResearchEvidenceBundle):
        _fail(
            "load_context_projection expected a ResearchEvidenceBundle from "
            "uow.research_evidence_bundles.get_by_id, got "
            f"{type(bundle).__name__}"
        )

    if bundle.bundle_id != bundle_id:
        _fail(
            "load_context_projection bundle.bundle_id does not match "
            f"ResearchRun.evidence_bundle_id ({bundle.bundle_id!s} != "
            f"{bundle_id!s})"
        )
    if bundle.research_case_id != case.case_id:
        _fail(
            "load_context_projection bundle.research_case_id does not match "
            f"ResearchCase.case_id ({bundle.research_case_id!s} != "
            f"{case.case_id!s})"
        )
    if bundle.evidence_pack_id != evidence_pack.pack_id:
        _fail(
            "load_context_projection bundle.evidence_pack_id does not match "
            f"EvidencePack.pack_id ({bundle.evidence_pack_id!s} != "
            f"{evidence_pack.pack_id!s})"
        )
    if bundle.evidence_pack_hash != evidence_pack.pack_hash:
        _fail(
            "load_context_projection bundle.evidence_pack_hash does not match "
            "EvidencePack.pack_hash"
        )
    if bundle.as_of_date != case.as_of_date:
        _fail(
            "load_context_projection bundle.as_of_date does not match "
            f"ResearchCase.as_of_date ({bundle.as_of_date} != "
            f"{case.as_of_date})"
        )
    if evidence_pack.case.as_of_date != case.as_of_date:
        _fail(
            "load_context_projection EvidencePack.case.as_of_date does not "
            f"match ResearchCase.as_of_date ({evidence_pack.case.as_of_date} "
            f"!= {case.as_of_date})"
        )

    loaded_snapshots: list[MarketObservationSnapshot] = []
    for ref in bundle.market_snapshot_refs:
        snapshot = uow.market_observation_snapshots.get_by_content_hash(
            ref.content_hash
        )
        if snapshot is None:
            _fail(
                "load_context_projection did not find "
                f"MarketObservationSnapshot with content_hash "
                f"{ref.content_hash!s} referenced by bundle "
                f"{bundle.bundle_id!s} ref {ref.snapshot_id!r}"
            )
        if not isinstance(snapshot, MarketObservationSnapshot):
            _fail(
                "load_context_projection expected a MarketObservationSnapshot "
                "from uow.market_observation_snapshots.get_by_content_hash, "
                f"got {type(snapshot).__name__}"
            )
        if snapshot.snapshot_id != ref.snapshot_id:
            _fail(
                "load_context_projection MarketObservationSnapshot.snapshot_id "
                f"{snapshot.snapshot_id!r} does not match "
                f"bundle.market_snapshot_refs {ref.snapshot_id!r} for "
                f"bundle {bundle.bundle_id!s}"
            )
        if snapshot.content_hash != ref.content_hash:
            _fail(
                "load_context_projection MarketObservationSnapshot.content_hash "
                f"{snapshot.content_hash!s} does not match bundle reference "
                f"{ref.content_hash!s} for snapshot_id "
                f"{snapshot.snapshot_id!r}"
            )
        if snapshot.as_of_date != ref.as_of_date:
            _fail(
                "load_context_projection MarketObservationSnapshot.as_of_date "
                f"{snapshot.as_of_date} does not match bundle reference "
                f"{ref.as_of_date} for snapshot_id {snapshot.snapshot_id!r}"
            )
        if snapshot.as_of_date != bundle.as_of_date:
            _fail(
                "load_context_projection MarketObservationSnapshot.as_of_date "
                f"{snapshot.as_of_date} does not match bundle.as_of_date "
                f"{bundle.as_of_date} for snapshot_id "
                f"{snapshot.snapshot_id!r}"
            )
        if snapshot.quality_status is not QualityStatus.COMPLETE:
            _fail(
                "load_context_projection MarketObservationSnapshot.quality_status "
                f"{snapshot.quality_status.value!r} must be "
                f"{QualityStatus.COMPLETE.value!r} for snapshot_id "
                f"{snapshot.snapshot_id!r}"
            )
        if snapshot.freshness_status is not FreshnessStatus.FRESH:
            _fail(
                "load_context_projection MarketObservationSnapshot.freshness_status "
                f"{snapshot.freshness_status.value!r} must be "
                f"{FreshnessStatus.FRESH.value!r} for snapshot_id "
                f"{snapshot.snapshot_id!r}"
            )
        loaded_snapshots.append(snapshot)

    return build_projection(
        bundle=bundle,
        evidence_pack=evidence_pack,
        market_snapshots=tuple(loaded_snapshots),
    )