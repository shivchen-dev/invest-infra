"""Read-only candidate-pool endpoints.

The router exposes ``/api/v1/candidate-pool/latest`` together with the
PR-04 diff endpoints that compare the set of ``instrument_id`` values
in one published run against the most recent earlier published run.
All endpoints are read-only and use the storage repositories' read-side
surface; no write path is exposed here.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from invest_domain.candidate_pool.models import (
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_storage import InputSnapshotRepository
from invest_storage.repositories import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
)
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.candidate_pool import (
    CandidatePoolDiffResponse,
    CandidatePoolItemResponse,
    CandidatePoolLatestResponse,
    ExclusionReasonResponse,
    RuleOutcomeResponse,
)

router = APIRouter(prefix="/api/v1/candidate-pool", tags=["candidate-pool"])


@router.get("/latest", response_model=CandidatePoolLatestResponse)
def get_latest_candidate_pool(
    session: Annotated[Session, Depends(get_db_session)],
) -> CandidatePoolLatestResponse:
    """Return the most recently published candidate-pool run."""

    run_repository = SqlAlchemyCandidatePoolRunRepository(session)
    published = run_repository.list_by_status(
        CandidatePoolStatus.PUBLISHED, limit=1, offset=0
    )
    if not published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no published candidate pool found",
        )
    latest_run = published[0]

    snapshot_repository = InputSnapshotRepository(session)
    snapshots_for_date = snapshot_repository.list_by_date(latest_run.trade_date)
    matching_snapshot = next(
        (snap for snap in snapshots_for_date if snap.id == latest_run.input_snapshot_id),
        None,
    )
    if matching_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"input snapshot {latest_run.input_snapshot_id!s} referenced by run "
                f"{latest_run.id!s} not found"
            ),
        )

    item_repository = SqlAlchemyCandidatePoolItemRepository(session)
    items = item_repository.list_by_run_id(latest_run.id)
    response_items = [
        CandidatePoolItemResponse(
            instrument_id=item.instrument_id.value,
            included=item.included,
            rank=item.rank,
            total_score=item.total_score,
            metrics={key: format(value, "f") for key, value in item.metrics.items()},
            rule_results=[
                RuleOutcomeResponse(
                    rule_key=outcome.rule_key,
                    passed=outcome.passed,
                    severity=outcome.severity.value,
                    value=outcome.value,
                    threshold=outcome.threshold,
                    message=outcome.message,
                )
                for outcome in item.rule_results
            ],
            exclusion_reasons=[
                ExclusionReasonResponse(code=reason.code, message=reason.message)
                for reason in item.exclusion_reasons
            ],
        )
        for item in items
    ]

    return CandidatePoolLatestResponse(
        snapshot_date=latest_run.trade_date,
        row_count=latest_run.input_row_count,
        content_hash=matching_snapshot.content_hash,
        items=response_items,
    )


def _instrument_id_set(
    items,  # noqa: ANN001 - parameter typed through repository contract below
) -> set[UUID]:
    """Return the set of raw UUID ``instrument_id`` values from run items."""

    return {item.instrument_id.value for item in items}


def _diff_against_previous_published_run(
    current_run: CandidatePoolRun,
    run_repository: SqlAlchemyCandidatePoolRunRepository,
    item_repository: SqlAlchemyCandidatePoolItemRepository,
) -> CandidatePoolDiffResponse:
    """Compare ``current_run`` against the most recent earlier published run.

    The lookup uses :meth:`list_by_status` (ordered by ``trade_date`` desc
    then ``id`` asc) and picks the first published run whose
    ``trade_date`` is strictly less than the current run's
    ``trade_date``. When no earlier published run exists the response
    reports every instrument in the current run as ``added`` and leaves
    ``retained`` / ``removed`` empty.
    """

    published = run_repository.list_by_status(
        CandidatePoolStatus.PUBLISHED, limit=100, offset=0
    )
    previous_run = next(
        (run for run in published if run.trade_date < current_run.trade_date),
        None,
    )

    current_items = item_repository.list_by_run_id(current_run.id)
    current_ids = _instrument_id_set(current_items)

    if previous_run is None:
        return CandidatePoolDiffResponse(
            trade_date=current_run.trade_date,
            previous_trade_date=None,
            added=sorted(current_ids),
            retained=[],
            removed=[],
        )

    previous_items = item_repository.list_by_run_id(previous_run.id)
    previous_ids = _instrument_id_set(previous_items)

    added = current_ids - previous_ids
    removed = previous_ids - current_ids
    retained = current_ids & previous_ids

    return CandidatePoolDiffResponse(
        trade_date=current_run.trade_date,
        previous_trade_date=previous_run.trade_date,
        added=sorted(added),
        retained=sorted(retained),
        removed=sorted(removed),
    )


@router.get("/latest/diff", response_model=CandidatePoolDiffResponse)
def get_latest_candidate_pool_diff(
    session: Annotated[Session, Depends(get_db_session)],
) -> CandidatePoolDiffResponse:
    """Diff the latest published run against the previous earlier published run."""

    run_repository = SqlAlchemyCandidatePoolRunRepository(session)
    published = run_repository.list_by_status(
        CandidatePoolStatus.PUBLISHED, limit=1, offset=0
    )
    if not published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no published candidate pool found",
        )
    current_run = published[0]
    item_repository = SqlAlchemyCandidatePoolItemRepository(session)
    return _diff_against_previous_published_run(
        current_run, run_repository, item_repository
    )


@router.get("/{run_id}/diff", response_model=CandidatePoolDiffResponse)
def get_candidate_pool_diff(
    run_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> CandidatePoolDiffResponse:
    """Diff the published run identified by ``run_id`` against its predecessor.

    Returns 404 when ``run_id`` does not exist or the run is not in the
    ``PUBLISHED`` state; the diff itself is read-only and never mutates
    storage state.
    """

    run_repository = SqlAlchemyCandidatePoolRunRepository(session)
    current_run = run_repository.get_by_id(run_id)
    if current_run is None or current_run.status is not CandidatePoolStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"published candidate pool run {run_id} not found",
        )
    item_repository = SqlAlchemyCandidatePoolItemRepository(session)
    return _diff_against_previous_published_run(
        current_run, run_repository, item_repository
    )


__all__ = ["router"]
