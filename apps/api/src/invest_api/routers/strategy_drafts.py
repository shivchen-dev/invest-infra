"""Read-only StrategyDraft endpoint used by RAA audit clients."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.strategy_drafts import (
    StrategyDraftArtifactDecodeError,
    StrategyDraftArtifactHashMismatchError,
    StrategyDraftArtifactReadError,
    StrategyDraftNotFoundError,
    StrategyDraftQueryService,
)
from invest_api.dependencies import get_strategy_draft_query_service
from invest_api.schemas.strategy_drafts import StrategyDraftResponse

router = APIRouter(prefix="/api/v1/strategy-drafts", tags=["strategy-drafts"])

_NOT_FOUND = "Strategy draft not found"
_UNAVAILABLE = "Strategy artifact unavailable"
_INVALID = "Strategy artifact failed integrity validation"


@router.get("/{draft_id}", response_model=StrategyDraftResponse)
def get_strategy_draft(
    draft_id: UUID,
    service: Annotated[
        StrategyDraftQueryService, Depends(get_strategy_draft_query_service)
    ],
) -> StrategyDraftResponse:
    try:
        view = service.get_draft(draft_id)
    except StrategyDraftNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from exc
    except StrategyDraftArtifactReadError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    except (
        StrategyDraftArtifactHashMismatchError,
        StrategyDraftArtifactDecodeError,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _INVALID) from exc
    return StrategyDraftResponse.from_view(view)


__all__ = ["router"]
