"""Gated command endpoint for external observation admission."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from invest_domain.integration import AdmissionVerification

from invest_api.application.admission import ObservationAdmissionCommandService
from invest_api.config import get_settings
from invest_api.dependencies import get_observation_admission_command_service
from invest_api.schemas.admission import AdmissionDecisionRequest, AdmissionDecisionResponse

router = APIRouter(prefix="/api/v1/external-observations", tags=["external-observations"])


@router.post("/{observation_id}/admission-decisions", response_model=AdmissionDecisionResponse)
def decide_admission(
    observation_id: UUID,
    request: AdmissionDecisionRequest,
    service: Annotated[
        ObservationAdmissionCommandService,
        Depends(get_observation_admission_command_service),
    ],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdmissionDecisionResponse:
    settings = get_settings()
    if not settings.stage4d_admission_commands_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="admission commands are disabled",
        )
    if idempotency_header is not None and idempotency_header != request.idempotency_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency-Key mismatch")
    try:
        result = service.decide(
            observation_id,
            AdmissionVerification(
                identity_ok=request.identity_ok,
                freshness_ok=request.freshness_ok,
                unit_ok=request.unit_ok,
                internal_cross_check_ok=request.internal_cross_check_ok,
                conflict_detected=request.conflict_detected,
                rules_version=request.rules_version,
                decided_by=request.decided_by,
                reason=request.reason,
            ),
            idempotency_key=request.idempotency_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    admission = result.observation.metadata.get("admission", {})
    return AdmissionDecisionResponse(
        observation_id=result.observation.observation_id,
        admission_status=result.observation.admission_status.value,
        reason=str(admission.get("reason", "")),
        idempotent=result.idempotent,
    )


__all__ = ["router"]
