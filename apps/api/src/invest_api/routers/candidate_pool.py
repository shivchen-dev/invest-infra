"""Read-only candidate-pool endpoints.

The router exposes ``/api/v1/candidate-pool/latest`` together with the
diff endpoints that compare the set of ``included=True`` instruments in
one published run against the most recent earlier published run. PR-01
of
``docs/plan/invest-infra-v2-next-stage-web-workbench-plan.md`` tightens
the diff to only consider included items, enriches the latest response
with run-level metadata, and joins Instrument display fields server
side so the Web never needs a follow-up ``/etf/instruments`` request.
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
    SqlAlchemyInstrumentRepository,
)
from sqlalchemy.orm import Session

from invest_api.dependencies import get_db_session
from invest_api.schemas.candidate_pool import (
    CandidatePoolDiffEntry,
    CandidatePoolDiffResponse,
    CandidatePoolItemResponse,
    CandidatePoolLatestResponse,
    ExclusionReasonResponse,
    RuleOutcomeResponse,
)

router = APIRouter(prefix="/api/v1/candidate-pool", tags=["candidate-pool"])


def _included_instrument_ids(
    items,  # noqa: ANN001 - parameter typed through repository contract below
) -> set[UUID]:
    """Return the set of raw UUID ``instrument_id`` values for included items only.

    Excluded items (where ``included=False``) MUST NEVER participate in
    the diff: they reflect the input pool membership, not candidate
    pool membership, and would otherwise make "input pool unchanged"
    surfaces look like "candidate pool retained everything".
    """

    return {item.instrument_id.value for item in items if item.included}


def _build_diff_entries(
    instrument_ids: set[UUID],
    instruments_by_id: dict[UUID, object],
) -> list[CandidatePoolDiffEntry]:
    """Resolve display fields for ``instrument_ids`` and sort deterministically.

    Order is ``symbol`` ascending with ``instrument_id`` as the
    tiebreaker so the Web can rely on a stable payload. Instruments
    that are missing from the lookup degrade to ``None`` display
    fields rather than dropping the entry - the diff still records the
    membership change.
    """

    entries: list[CandidatePoolDiffEntry] = []
    for instrument_id in instrument_ids:
        instrument = instruments_by_id.get(instrument_id)
        entries.append(
            CandidatePoolDiffEntry(
                instrument_id=instrument_id,
                symbol=getattr(instrument, "symbol", None),
                name=getattr(instrument, "name", None),
                exchange=getattr(instrument, "exchange", None),
            )
        )
    entries.sort(
        key=lambda entry: (
            entry.symbol or "",
            str(entry.instrument_id),
        )
    )
    return entries


def _build_item_responses(
    items,  # noqa: ANN001
    instruments_by_id: dict[UUID, object],
) -> list[CandidatePoolItemResponse]:
    """Translate :class:`CandidatePoolItem` rows into the API response shape."""

    responses: list[CandidatePoolItemResponse] = []
    for item in items:
        instrument = instruments_by_id.get(item.instrument_id.value)
        responses.append(
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
                symbol=getattr(instrument, "symbol", None),
                name=getattr(instrument, "name", None),
                exchange=getattr(instrument, "exchange", None),
            )
        )
    return responses


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

    instrument_repository = SqlAlchemyInstrumentRepository(session)
    instruments_by_id = instrument_repository.get_many_by_ids(
        [item.instrument_id for item in items]
    )

    response_items = _build_item_responses(items, instruments_by_id)
    excluded_count = max(latest_run.input_row_count - latest_run.included_count, 0)

    return CandidatePoolLatestResponse(
        run_id=latest_run.id,
        trade_date=latest_run.trade_date,
        algorithm_key=latest_run.algorithm_key,
        algorithm_version=latest_run.algorithm_version,
        parameter_set_key=latest_run.parameter_set_key,
        snapshot_id=latest_run.input_snapshot_id,
        content_hash=matching_snapshot.content_hash,
        row_count=latest_run.input_row_count,
        included_count=latest_run.included_count,
        excluded_count=excluded_count,
        published_at=latest_run.published_at,
        items=response_items,
    )


def _diff_against_previous_published_run(
    current_run: CandidatePoolRun,
    run_repository: SqlAlchemyCandidatePoolRunRepository,
    item_repository: SqlAlchemyCandidatePoolItemRepository,
    instrument_repository: SqlAlchemyInstrumentRepository,
) -> CandidatePoolDiffResponse:
    """Compare ``current_run`` against the most recent earlier published run.

    Only items with ``included=True`` participate in the diff so the
    result reflects candidate-pool membership changes instead of input
    pool membership changes. The lookup uses
    :meth:`list_by_status` (ordered by ``trade_date`` desc then ``id``
    asc) and picks the first published run whose ``trade_date`` is
    strictly less than the current run's ``trade_date``. When no
    earlier published run exists the response reports every included
    instrument in the current run as ``added`` and leaves
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
    current_ids = _included_instrument_ids(current_items)

    if previous_run is None:
        instruments_by_id = instrument_repository.get_many_by_ids(current_ids)
        return CandidatePoolDiffResponse(
            trade_date=current_run.trade_date,
            previous_trade_date=None,
            added=_build_diff_entries(current_ids, instruments_by_id),
            retained=[],
            removed=[],
        )

    previous_items = item_repository.list_by_run_id(previous_run.id)
    previous_ids = _included_instrument_ids(previous_items)

    added_ids = current_ids - previous_ids
    removed_ids = previous_ids - current_ids
    retained_ids = current_ids & previous_ids

    instrument_ids = added_ids | removed_ids | retained_ids
    instruments_by_id = instrument_repository.get_many_by_ids(instrument_ids)

    return CandidatePoolDiffResponse(
        trade_date=current_run.trade_date,
        previous_trade_date=previous_run.trade_date,
        added=_build_diff_entries(added_ids, instruments_by_id),
        retained=_build_diff_entries(retained_ids, instruments_by_id),
        removed=_build_diff_entries(removed_ids, instruments_by_id),
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
    instrument_repository = SqlAlchemyInstrumentRepository(session)
    return _diff_against_previous_published_run(
        current_run, run_repository, item_repository, instrument_repository
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
    instrument_repository = SqlAlchemyInstrumentRepository(session)
    return _diff_against_previous_published_run(
        current_run, run_repository, item_repository, instrument_repository
    )


__all__ = ["router"]