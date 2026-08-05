from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from invest_storage.database import build_engine, session_factory
from invest_storage.repositories import SqlAlchemyPipelineRunRepository
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from invest_api.application.pipeline_runs import PipelineRunQueryService
from invest_api.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return session_factory(get_engine())


def get_db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_pipeline_run_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> PipelineRunQueryService:
    """Build the application service that backs ``/api/v1/pipeline-runs``.

    Constructs :class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`
    against the FastAPI-provided session and hands it to
    :class:`invest_api.application.pipeline_runs.PipelineRunQueryService`.
    Tests override this dependency through ``app.dependency_overrides``
    to inject a mock service without touching the storage layer.
    """

    return PipelineRunQueryService(SqlAlchemyPipelineRunRepository(session))


__all__ = [
    "get_db_session",
    "get_engine",
    "get_pipeline_run_query_service",
    "get_session_factory",
]