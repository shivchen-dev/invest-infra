"""Mock-level contract tests for Stage 4D integration repositories."""

from datetime import UTC, date, datetime
from uuid import uuid4

from invest_domain.integration import (
    AdmissionStatus,
    ExternalArtifact,
    ExternalObservation,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)
from invest_storage.repositories import (
    SqlAlchemyExternalArtifactRepository,
    SqlAlchemyExternalObservationRepository,
    SqlAlchemyExternalWorkflowRunRepository,
)
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork


class FakeSession:
    def __init__(self) -> None:
        self.rows = {}
        self.added = []
        self.flush_count = 0

    def add(self, row) -> None:
        self.added.append(row)
        self.rows[(type(row), row.__mapper__.primary_key[0].key)] = row

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def get(self, row_type, key):
        for row in self.added:
            primary_key = row_type.__mapper__.primary_key[0].key
            if isinstance(row, row_type) and getattr(row, primary_key) == key:
                return row
        return None


def _fixtures():
    now = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
    run_id = uuid4()
    artifact_id = uuid4()
    observation_id = uuid4()
    run = ExternalWorkflowRun(
        run_id=run_id,
        producer="workbuddy",
        schema_version="2.0.0",
        producer_status=ProducerStatus.SUCCEEDED,
        intake_status=IntakeStatus.ACCEPTED,
        started_at=now,
        finished_at=now,
        metadata={"source": "test"},
    )
    artifact = ExternalArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        logical_uri="archive://workbuddy/run/candidates.json",
        content_hash="a" * 64,
        media_type="application/json",
        size_bytes=12,
        created_at=now,
        metadata={"immutable": True},
    )
    observation = ExternalObservation(
        observation_id=observation_id,
        run_id=run_id,
        artifact_id=artifact_id,
        observed_at=now,
        as_of=date(2026, 8, 14),
        source_uri="archive://workbuddy/run/candidates.json",
        producer="workbuddy",
        payload={"symbol": "510300"},
        symbol="510300",
        admission_status=AdmissionStatus.PENDING,
        metadata={"candidate_index": 0},
    )
    return run, artifact, observation


def test_external_repositories_round_trip_domain_contracts():
    session = FakeSession()
    run, artifact, observation = _fixtures()

    stored_run = SqlAlchemyExternalWorkflowRunRepository(session).add(run)
    stored_artifact = SqlAlchemyExternalArtifactRepository(session).add(artifact)
    stored_observation = SqlAlchemyExternalObservationRepository(session).add(observation)

    assert stored_run == run
    assert stored_artifact == artifact
    assert stored_observation == observation
    assert SqlAlchemyExternalWorkflowRunRepository(session).get_by_id(run.run_id) == run
    assert SqlAlchemyExternalArtifactRepository(session).get_by_id(artifact.artifact_id) == artifact
    assert (
        SqlAlchemyExternalObservationRepository(session).get_by_id(observation.observation_id)
        == observation
    )
    assert session.flush_count == 3


def test_uow_exposes_cached_external_repositories():
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(lambda: session)

    with uow as entered:
        assert entered.external_workflow_runs is entered.external_workflow_runs
        assert entered.external_artifacts is entered.external_artifacts
        assert entered.external_observations is entered.external_observations

    assert uow.closed
