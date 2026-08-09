from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.research import ResearchQueryError, ResearchQueryService
from invest_api.dependencies import get_research_query_service
from invest_api.schemas.research import (
    EvidencePackResponse,
    ResearchCaseListResponse,
    ResearchCaseResponse,
    ResearchDashboardEvidenceStatus,
    ResearchDashboardMarketStatus,
    ResearchDashboardResearchSummary,
    ResearchDashboardResponse,
    ResearchResultResponse,
    ResearchRunListResponse,
    ResearchRunResponse,
)

router = APIRouter(prefix="/api/v1", tags=["research"])


def _query_failed(exc: ResearchQueryError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Research query failed",
    )


@router.get("/research-cases", response_model=ResearchCaseListResponse)
def list_research_cases(
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResearchCaseListResponse:
    try:
        items, total = service.list_cases(limit=limit, offset=offset)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    return ResearchCaseListResponse(
        items=[ResearchCaseResponse.from_domain(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/research-cases/{case_id}", response_model=ResearchCaseResponse)
def get_research_case(
    case_id: UUID,
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
) -> ResearchCaseResponse:
    try:
        case = service.get_case(case_id)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research case not found")
    return ResearchCaseResponse.from_domain(case)


@router.get("/research-cases/{case_id}/evidence", response_model=list[EvidencePackResponse])
def get_research_case_evidence(
    case_id: UUID,
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
) -> list[EvidencePackResponse]:
    try:
        packs = service.get_case_evidence(case_id)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    if packs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research case not found")
    return [EvidencePackResponse.from_domain(pack) for pack in packs]


@router.get("/research-runs", response_model=ResearchRunListResponse)
def list_research_runs(
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResearchRunListResponse:
    try:
        items, total = service.list_runs(limit=limit, offset=offset)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    return ResearchRunListResponse(
        items=[ResearchRunResponse.from_domain(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/research-runs/{run_id}", response_model=ResearchRunResponse)
def get_research_run(
    run_id: UUID,
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
) -> ResearchRunResponse:
    try:
        run = service.get_run(run_id)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found")
    return ResearchRunResponse.from_domain(run)


@router.get("/research-runs/{run_id}/result", response_model=ResearchResultResponse)
def get_research_run_result(
    run_id: UUID,
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
) -> ResearchResultResponse:
    try:
        result = service.get_run_result(run_id)
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research result not found",
        )
    return ResearchResultResponse.from_domain(result)


@router.get("/research-dashboard", response_model=ResearchDashboardResponse)
def get_research_dashboard(
    service: Annotated[ResearchQueryService, Depends(get_research_query_service)],
) -> ResearchDashboardResponse:
    """Return the read-only Research Cockpit dashboard aggregate.

    The dashboard derives every field from the existing PR-7
    resource-level readers (``ResearchCaseReader`` /
    ``ResearchRunReader`` / ``ResearchEvidenceReader``). The
    application service owns the orchestration, the deterministic
    ordering, the bounded ``recent_runs`` list and the
    ``SQLAlchemyError`` boundary; this router is intentionally a
    thin pass-through that stamps ``generated_at`` with a UTC
    wall-clock value so two callers hitting the service in the
    same instant still observe distinct response timestamps.

    ``market_status`` is always the explicit
    ``{"state": "unavailable", "reason": "..."}`` shape until a
    market dashboard source is registered; no market / factor
    values or investment conclusions are invented on this path.
    """

    try:
        view = service.get_dashboard()
    except ResearchQueryError as exc:
        raise _query_failed(exc) from exc

    evidence_view = view.evidence_status
    return ResearchDashboardResponse(
        schema_version=view.schema_version,
        generated_at=datetime.now(UTC),
        as_of_date=view.as_of_date,
        data_quality=view.data_quality,
        freshness=view.freshness,
        market_status=ResearchDashboardMarketStatus(
            state=view.market_status.state,
            reason=view.market_status.reason,
        ),
        research_summary=ResearchDashboardResearchSummary(
            case_count=view.research_summary.case_count,
            run_count=view.research_summary.run_count,
            latest_case=(
                ResearchCaseResponse.from_domain(view.research_summary.latest_case)
                if view.research_summary.latest_case is not None
                else None
            ),
        ),
        evidence_status=ResearchDashboardEvidenceStatus(
            state=evidence_view.state,
            case_id=evidence_view.case_id,
            pack_id=evidence_view.pack_id,
            schema_version=evidence_view.schema_version,
            factor_set_key=evidence_view.factor_set_key,
            factor_set_version=evidence_view.factor_set_version,
            quality_status=evidence_view.quality_status,
            freshness_status=evidence_view.freshness_status,
        ),
        recent_runs=[ResearchRunResponse.from_domain(run) for run in view.recent_runs],
    )
