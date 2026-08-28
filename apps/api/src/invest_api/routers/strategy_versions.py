"""Read-only active StrategyVersion endpoint exposed to LAN clients (Slice 1A).

Returns the verified public envelope for the unique active version of
the requested ``strategy_key``. Error mapping is fixed and sanitised:

- :class:`StrategyVersionNotFoundError` -> 404
- :class:`StrategyVersionArtifactReadError` -> 503
- :class:`StrategyVersionArtifactHashMismatchError` /
  :class:`StrategyVersionArtifactDecodeError` -> 409

The complete authored strategy JSON is returned to the caller without
field rewriting or allow-list filtering of the ``strategy`` body. No
strategy fields or values are removed. The "forbidden host paths"
contract applies exclusively to the public envelope and the error
mappings: ``artifact_ref`` and other storage-envelope fields stay on the
server, and exception messages, ``__cause__`` payloads, OS error reprs
and credential strings never leak into the response. Path-like strings
deliberately authored inside the strategy JSON are not subject to that
filter and are returned verbatim because they are strategy content,
not infrastructure detail.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from invest_api.application.strategy_versions import (
    StrategyVersionArtifactDecodeError,
    StrategyVersionArtifactHashMismatchError,
    StrategyVersionArtifactReadError,
    StrategyVersionNotFoundError,
    StrategyVersionQueryService,
)
from invest_api.dependencies import get_strategy_version_query_service
from invest_api.schemas.strategy_versions import StrategyVersionResponse

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

_NOT_FOUND = "Strategy version not found"
_UNAVAILABLE = "Strategy artifact unavailable"
_INVALID = "Strategy artifact failed integrity validation"


@router.get(
    "/{strategy_key}/active",
    response_model=StrategyVersionResponse,
    responses={
        404: {"description": _NOT_FOUND},
        409: {"description": _INVALID},
        503: {"description": _UNAVAILABLE},
    },
)
def get_active_strategy_version(
    strategy_key: str,
    service: Annotated[
        StrategyVersionQueryService, Depends(get_strategy_version_query_service)
    ],
) -> StrategyVersionResponse:
    try:
        view = service.get_active(strategy_key)
    except StrategyVersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND) from exc
    except StrategyVersionArtifactReadError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    except (
        StrategyVersionArtifactHashMismatchError,
        StrategyVersionArtifactDecodeError,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _INVALID) from exc
    return StrategyVersionResponse.from_view(view)


__all__ = ["router"]
