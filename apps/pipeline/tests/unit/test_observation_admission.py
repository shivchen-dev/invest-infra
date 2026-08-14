from datetime import UTC, date, datetime
from uuid import uuid4

from invest_domain.integration import AdmissionStatus, AdmissionVerification, ExternalObservation
from invest_pipeline.integrations.admission import ObservationAdmissionService


class _Repo:
    def __init__(self, observation):
        self.observation = observation
        self.saved = None

    def get_by_id(self, observation_id):
        return self.observation if observation_id == self.observation.observation_id else None

    def save_admission(self, observation):
        self.saved = observation
        return observation


def test_admission_service_persists_decision_metadata():
    observation = ExternalObservation(
        observation_id=uuid4(),
        run_id=uuid4(),
        observed_at=datetime(2026, 8, 14, tzinfo=UTC),
        as_of=date(2026, 8, 14),
        source_uri="archive://candidate.json",
        producer="workbuddy",
        payload={"symbol": "510300"},
    )
    repository = _Repo(observation)
    decision = ObservationAdmissionService(repository).decide(
        observation.observation_id,
        AdmissionVerification(True, True, True, True),
    )

    assert decision.status is AdmissionStatus.ADMITTED
    assert repository.saved is not None
    assert repository.saved.metadata["admission"]["status"] == "admitted"
