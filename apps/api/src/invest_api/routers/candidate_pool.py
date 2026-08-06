"""Read-only candidate-pool endpoints.

The router exposes ``/api/v1/candidate-pool/latest`` together with the
diff endpoints that compare the set of ``included=True`` instruments in
one published run against the most recent earlier published run. PR-01
of
``docs/plan/invest-infra-v2-next-stage-web-workbench-plan.md`` tightens
the diff to only consider included items, enriches the latest response
with run-level metadata, and joins Instrument display fields server
side so the Web never needs a follow-up ``/etf/instruments`` request.

All endpoints delegate to
:class:`invest_api.application.candidate_pool.CandidatePoolQueryService`,
which owns the ``PUBLISHED`` filter, the input-snapshot lookup, the
predecessor selection, the included-only set diff, the instrument
lookup and the :class:`sqlalchemy.exc.SQLAlchemyError` boundary. The
router only translates the small domain view dataclasses returned by
the service into the public Pydantic response shapes and converts
application exceptions into HTTP errors.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from invest_domain.candidate_pool.models import CandidatePoolItem
from invest_domain.instruments import Instrument

from invest_api.application.candidate_pool import (
    MISSING_LATEST_DETAIL,
    MISSING_RUN_DETAIL_TEMPLATE,
    CandidatePoolDiffEntryView,
    CandidatePoolDiffView,
    CandidatePoolQueryError,
    CandidatePoolQueryService,
    CandidatePoolSnapshotMissingError,
    LatestCandidatePoolView,
)
from invest_api.dependencies import get_candidate_pool_query_service
from invest_api.schemas.candidate_pool import (
    CandidatePoolDiffEntry,
    CandidatePoolDiffResponse,
    CandidatePoolItemResponse,
    CandidatePoolLatestResponse,
    ExclusionReasonResponse,
    RuleOutcomeResponse,
)

router = APIRouter(prefix="/api/v1/candidate-pool", tags=["candidate-pool"])


def _format_missing_snapshot_detail(
    *, snapshot_id: UUID, run_id: UUID
) -> str:
    return (
        f"input snapshot {snapshot_id!s} referenced by run {run_id!s} not found"
    )


def _build_item_response(
    item: CandidatePoolItem,
    instrument: Instrument | None,
) -> CandidatePoolItemResponse:
    """Translate a :class:`CandidatePoolItem` into the public response shape."""

    return CandidatePoolItemResponse(
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
        symbol=getattr(instrument, "symbol", None),
        name=getattr(instrument, "name", None),
        exchange=getattr(instrument, "exchange", None),
    )


def _build_latest_response(view: LatestCandidatePoolView) -> CandidatePoolLatestResponse:
    """Translate a :class:`LatestCandidatePoolView` into the public response shape."""

    run = view.run
    excluded_count = max(run.input_row_count - run.included_count, 0)
    return CandidatePoolLatestResponse(
        run_id=run.id,
        trade_date=run.trade_date,
        algorithm_key=run.algorithm_key,
        algorithm_version=run.algorithm_version,
        parameter_set_key=run.parameter_set_key,
        snapshot_id=run.input_snapshot_id,
        content_hash=view.snapshot.content_hash,
        row_count=run.input_row_count,
        included_count=run.included_count,
        excluded_count=excluded_count,
        published_at=run.published_at,
        items=[
            _build_item_response(item, view.instruments_by_id.get(item.instrument_id.value))
            for item in view.items
        ],
    )


def _to_diff_entry(entry: CandidatePoolDiffEntryView) -> CandidatePoolDiffEntry:
    return CandidatePoolDiffEntry(
        instrument_id=entry.instrument_id,
        symbol=entry.symbol,
        name=entry.name,
        exchange=entry.exchange,
    )


def _build_diff_response(view: CandidatePoolDiffView) -> CandidatePoolDiffResponse:
    return CandidatePoolDiffResponse(
        trade_date=view.trade_date,
        previous_trade_date=view.previous_trade_date,
        added=[_to_diff_entry(entry) for entry in view.added],
        retained=[_to_diff_entry(entry) for entry in view.retained],
        removed=[_to_diff_entry(entry) for entry in view.removed],
    )


@router.get("/latest", response_model=CandidatePoolLatestResponse)
def get_latest_candidate_pool(
    service: Annotated[
        CandidatePoolQueryService, Depends(get_candidate_pool_query_service)
    ],
) -> CandidatePoolLatestResponse:
    """Return the most recently published candidate-pool run."""

    try:
        view = service.get_latest()
    except CandidatePoolSnapshotMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_format_missing_snapshot_detail(
                snapshot_id=exc.snapshot_id, run_id=exc.run_id
            ),
        ) from exc
    except CandidatePoolQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Candidate pool query failed",
        ) from exc

    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MISSING_LATEST_DETAIL,
        )
    return _build_latest_response(view)


@router.get("/latest/diff", response_model=CandidatePoolDiffResponse)
def get_latest_candidate_pool_diff(
    service: Annotated[
        CandidatePoolQueryService, Depends(get_candidate_pool_query_service)
    ],
) -> CandidatePoolDiffResponse:
    """Diff the latest published run against the previous earlier published run."""

    try:
        view = service.get_latest_diff()
    except CandidatePoolSnapshotMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_format_missing_snapshot_detail(
                snapshot_id=exc.snapshot_id, run_id=exc.run_id
            ),
        ) from exc
    except CandidatePoolQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Candidate pool query failed",
        ) from exc

    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MISSING_LATEST_DETAIL,
        )
    return _build_diff_response(view)


@router.get("/{run_id}/diff", response_model=CandidatePoolDiffResponse)
def get_candidate_pool_diff(
    service: Annotated[
        CandidatePoolQueryService, Depends(get_candidate_pool_query_service)
    ],
    run_id: Annotated[UUID, Path()],
) -> CandidatePoolDiffResponse:
    """Diff the published run identified by ``run_id`` against its predecessor.

    Returns 404 when ``run_id`` does not exist or the run is not in the
    ``PUBLISHED`` state; the diff itself is read-only and never mutates
    storage state.
    """

    try:
        view = service.get_run_diff(run_id)
    except CandidatePoolSnapshotMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_format_missing_snapshot_detail(
                snapshot_id=exc.snapshot_id, run_id=exc.run_id
            ),
        ) from exc
    except CandidatePoolQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Candidate pool query failed",
        ) from exc

    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MISSING_RUN_DETAIL_TEMPLATE.format(run_id=run_id),
        )
    return _build_diff_response(view)


__all__ = ["router"]