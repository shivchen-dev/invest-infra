from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from invest_storage import InputSnapshotRepository
from invest_storage.database import build_engine, session_factory
from invest_storage.repositories import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyDailyBarRepository,
    SqlAlchemyDataFreshnessReader,
    SqlAlchemyEvidencePackRepository,
    SqlAlchemyExternalArtifactRepository,
    SqlAlchemyExternalObservationRepository,
    SqlAlchemyExternalWorkflowRunRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyMarketObservationSnapshotRepository,
    SqlAlchemyPipelineRunRepository,
    SqlAlchemyResearchCaseRepository,
    SqlAlchemyResearchExternalEvidenceRepository,
    SqlAlchemyResearchResultRepository,
    SqlAlchemyResearchRunRepository,
)
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from invest_api.application.admission import ObservationAdmissionCommandService
from invest_api.application.candidate_pool import CandidatePoolQueryService
from invest_api.application.data_freshness import DataFreshnessQueryService
from invest_api.application.etf import EtfQueryService
from invest_api.application.external_workflows import ExternalWorkflowQueryService
from invest_api.application.market_breadth import MarketBreadthQueryService
from invest_api.application.market_temperature import MarketTemperatureQueryService
from invest_api.application.pipeline_runs import PipelineRunQueryService
from invest_api.application.research import ResearchQueryService
from invest_api.application.research_external_evidence import ResearchExternalEvidenceService
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


def get_external_workflow_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ExternalWorkflowQueryService:
    return ExternalWorkflowQueryService(
        run_repository=SqlAlchemyExternalWorkflowRunRepository(session),
        artifact_repository=SqlAlchemyExternalArtifactRepository(session),
        observation_repository=SqlAlchemyExternalObservationRepository(session),
    )


def get_observation_admission_command_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ObservationAdmissionCommandService:
    return ObservationAdmissionCommandService(SqlAlchemyExternalObservationRepository(session))


def get_research_external_evidence_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ResearchExternalEvidenceService:
    return ResearchExternalEvidenceService(
        case_reader=SqlAlchemyResearchCaseRepository(session),
        observation_reader=SqlAlchemyExternalObservationRepository(session),
        artifact_reader=SqlAlchemyExternalArtifactRepository(session),
        evidence_writer=SqlAlchemyResearchExternalEvidenceRepository(session),
    )


def get_candidate_pool_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> CandidatePoolQueryService:
    """Build the application service that backs ``/api/v1/candidate-pool``.

    Constructs the four narrow read-side repositories against the
    FastAPI-provided session and hands them to
    :class:`invest_api.application.candidate_pool.CandidatePoolQueryService`.
    Tests override this dependency through ``app.dependency_overrides``
    to inject a mock service without touching the storage layer.
    """

    return CandidatePoolQueryService(
        run_repository=SqlAlchemyCandidatePoolRunRepository(session),
        item_repository=SqlAlchemyCandidatePoolItemRepository(session),
        snapshot_repository=InputSnapshotRepository(session),
        instrument_repository=SqlAlchemyInstrumentRepository(session),
    )


def get_etf_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> EtfQueryService:
    """Build the application service that backs the ETF read-only endpoints.

    Constructs :class:`invest_storage.repositories.SqlAlchemyInstrumentRepository`
    and :class:`invest_storage.repositories.SqlAlchemyDailyBarRepository`
    against the FastAPI-provided session and hands them to
    :class:`invest_api.application.etf.EtfQueryService`. Tests override
    this dependency through ``app.dependency_overrides`` to inject a
    mock service without touching the storage layer.
    """

    return EtfQueryService(
        instrument_repository=SqlAlchemyInstrumentRepository(session),
        daily_bar_repository=SqlAlchemyDailyBarRepository(session),
    )


def get_data_freshness_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> DataFreshnessQueryService:
    """Build the application service that backs ``/api/v1/data-freshness``.

    Constructs :class:`invest_storage.repositories.SqlAlchemyDataFreshnessReader`
    against the FastAPI-provided session and hands it to
    :class:`invest_api.application.data_freshness.DataFreshnessQueryService`.
    The reader encapsulates the same raw ``text()`` lookups the previous
    router did; tests override this dependency through
    ``app.dependency_overrides`` to inject a mock service without
    touching the storage layer.
    """

    return DataFreshnessQueryService(SqlAlchemyDataFreshnessReader(session))


def get_research_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> ResearchQueryService:
    return ResearchQueryService(
        case_repository=SqlAlchemyResearchCaseRepository(session),
        evidence_repository=SqlAlchemyEvidencePackRepository(session),
        run_repository=SqlAlchemyResearchRunRepository(session),
        result_repository=SqlAlchemyResearchResultRepository(session),
    )


def get_market_temperature_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> MarketTemperatureQueryService:
    return MarketTemperatureQueryService(
        SqlAlchemyMarketObservationSnapshotRepository(session)
    )


def get_market_breadth_query_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> MarketBreadthQueryService:
    """Build the application service that backs ``/api/v1/market-breadth``.

    Constructs :class:`invest_storage.repositories.SqlAlchemyMarketObservationSnapshotRepository`
    against the FastAPI-provided session and hands it to
    :class:`invest_api.application.market_breadth.MarketBreadthQueryService`.
    Tests override this dependency through ``app.dependency_overrides``
    to inject a mock service without touching the storage layer.
    """

    return MarketBreadthQueryService(
        SqlAlchemyMarketObservationSnapshotRepository(session)
    )


__all__ = [
    "get_candidate_pool_query_service",
    "get_data_freshness_query_service",
    "get_db_session",
    "get_etf_query_service",
    "get_engine",
    "get_external_workflow_query_service",
    "get_observation_admission_command_service",
    "get_market_breadth_query_service",
    "get_pipeline_run_query_service",
    "get_research_query_service",
    "get_session_factory",
]
