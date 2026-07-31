"""Read-only candidate-pool endpoint ``/api/v1/candidate-pool/latest``.

The endpoint surfaces the most recently published candidate-pool run
together with the input snapshot's ``content_hash`` so the front-end
can audit the universe the pool was calculated against. The lookup uses
the storage repositories' read-side surface only - no write path is
exposed here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from invest_domain.candidate_pool.models import CandidatePoolStatus
from invest_storage import InputSnapshotRepository
from invest_storage.repositories import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
)
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.candidate_pool import (
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


__all__ = ["router"]
