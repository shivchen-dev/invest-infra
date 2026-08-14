from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from invest_api.application.research_external_evidence import (
    ExternalEvidenceLinkError,
    ResearchExternalEvidenceService,
)
from invest_domain.instruments import InstrumentId
from invest_domain.integration import (
    AdmissionVerification,
    ExternalArtifact,
    ExternalObservation,
    evaluate_admission,
)
from invest_domain.research import ResearchCase

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)
HASH = "a" * 64


def test_link_admitted_observation_to_matching_case_is_idempotent() -> None:
    instrument_id = InstrumentId(uuid4())
    run_id = uuid4()
    artifact = ExternalArtifact(uuid4(), run_id, "archive://run/a.json", HASH,
                                "application/json", 1, NOW)
    observation = ExternalObservation(
        uuid4(), run_id, NOW, date(2026, 8, 14), artifact.logical_uri, "workbuddy", {},
        artifact_id=artifact.artifact_id, instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=instrument_id, as_of_date=observation.as_of,
        question="test", horizon="20d", created_at=NOW,
    )
    saved = []
    class Cases:
        def get(self, _case_id):
            return case
    class Observations:
        def get_by_id(self, _observation_id):
            return observation
    class Artifacts:
        def get_by_id(self, _artifact_id):
            return artifact
    class Writer:
        def add(self, _case_id, item):
            saved.append(item)
            return item
    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    item = service.link(case_id=case.case_id, observation_id=observation.observation_id)
    assert item.artifact_content_hash == HASH
    assert saved[0] is item


def test_link_rejects_instrument_mismatch() -> None:
    observation = ExternalObservation(uuid4(), uuid4(), NOW, date(2026, 8, 14),
                                      "archive://run/a.json", "workbuddy", {},
                                      instrument_id=uuid4())
    case = ResearchCase.create(
        instrument_id=InstrumentId(uuid4()), as_of_date=observation.as_of,
        question="test", horizon="20d", created_at=NOW,
    )
    class Cases:
        def get(self, _case_id):
            return case
    class Observations:
        def get_by_id(self, _observation_id):
            return observation
    class Artifacts:
        def get_by_id(self, _artifact_id):
            return None
    class Writer:
        def add(self, _case_id, _item):
            return None
    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())
    with pytest.raises(ExternalEvidenceLinkError, match="instrument"):
        service.link(case_id=case.case_id, observation_id=observation.observation_id)


def test_create_case_from_admitted_observation_is_idempotent() -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(), uuid4(), NOW, date(2026, 8, 14), "archive://run/a.json", "workbuddy", {},
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    cases = {}
    evidence = {}

    class Cases:
        def get(self, case_id):
            return cases.get(case_id)
        def add(self, case):
            cases[case.case_id] = case
            return case
    class Observations:
        def get_by_id(self, _observation_id):
            return observation
    class Artifacts:
        def get_by_id(self, _artifact_id):
            return None
    class Writer:
        def get_by_observation(self, observation_id):
            return evidence.get(observation_id)
        def add(self, case_id, item):
            evidence[item.observation_id] = (case_id, item)
            return item

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())
    first = service.create_case_and_link(
        observation_id=observation.observation_id, question="test"
    )
    second = service.create_case_and_link(
        observation_id=observation.observation_id, question="changed"
    )
    assert first.created_case is True
    assert second.created_case is False
    assert first.case.case_id == second.case.case_id
