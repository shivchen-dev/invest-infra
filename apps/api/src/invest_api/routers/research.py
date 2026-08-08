from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from invest_api.application.research import ResearchQueryError, ResearchQueryService
from invest_api.dependencies import get_research_query_service
from invest_api.schemas.research import (
    EvidencePackResponse,
    ResearchCaseListResponse,
    ResearchCaseResponse,
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
