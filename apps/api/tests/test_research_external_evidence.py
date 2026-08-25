from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from invest_api.application.research_external_evidence import (
    ExternalEvidenceLinkError,
    ResearchExternalEvidenceService,
)
from invest_domain.instruments import InstrumentId
from invest_domain.integration import (
    AdmissionStatus,
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
    artifact = ExternalArtifact(
        uuid4(), run_id, "archive://run/a.json", HASH, "application/json", 1, NOW
    )
    observation = ExternalObservation(
        uuid4(),
        run_id,
        NOW,
        date(2026, 8, 14),
        artifact.logical_uri,
        "workbuddy",
        {},
        artifact_id=artifact.artifact_id,
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
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
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        instrument_id=uuid4(),
    )
    case = ResearchCase.create(
        instrument_id=InstrumentId(uuid4()),
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
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


def test_link_rejects_admitted_observation_without_instrument_id() -> None:
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        instrument_id=None,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=InstrumentId(uuid4()),
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
    )

    class Cases:
        def get(self, _case_id):
            return case

    class Observations:
        def get_by_id(self, _observation_id):
            return observation

    class Artifacts:
        def get_by_id(self, artifact_id):
            raise AssertionError(
                "artifact reader should not be called when instrument_id is missing"
            )

    class Writer:
        def add(self, _case_id, _item):
            raise AssertionError("writer.add should not be called when instrument_id is missing")

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="required"):
        service.link(case_id=case.case_id, observation_id=observation.observation_id)


def test_create_case_from_admitted_observation_is_idempotent() -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
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
    first = service.create_case_and_link(observation_id=observation.observation_id, question="test")
    second = service.create_case_and_link(
        observation_id=observation.observation_id, question="changed"
    )
    assert first.created_case is True
    assert second.created_case is False
    assert first.case.case_id == second.case.case_id


@pytest.mark.parametrize(
    "status",
    [
        AdmissionStatus.PENDING,
        AdmissionStatus.CORROBORATED,
        AdmissionStatus.REJECTED,
        AdmissionStatus.CONFLICT,
    ],
)
def test_link_rejects_non_admitted_observation(status: AdmissionStatus) -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        artifact_id=uuid4(),
        instrument_id=instrument_id.value,
        admission_status=status,
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
    )

    class Cases:
        def get(self, _case_id):
            return case

    class Observations:
        def get_by_id(self, _observation_id):
            return observation

    class Artifacts:
        def get_by_id(self, artifact_id):
            raise AssertionError(
                "artifact reader should not be called for non-admitted observation"
            )

    class Writer:
        def add(self, _case_id, _item):
            raise AssertionError("writer.add should not be called for non-admitted observation")

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="must be admitted"):
        service.link(case_id=case.case_id, observation_id=observation.observation_id)


def test_admission_gate_runs_before_artifact_lookup_for_missing_artifact() -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        artifact_id=uuid4(),
        instrument_id=instrument_id.value,
        admission_status=AdmissionStatus.PENDING,
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
    )
    artifact_calls: list[UUID] = []

    class Cases:
        def get(self, _case_id):
            return case

    class Observations:
        def get_by_id(self, _observation_id):
            return observation

    class Artifacts:
        def get_by_id(self, artifact_id):
            artifact_calls.append(artifact_id)
            return None

    class Writer:
        def add(self, _case_id, _item):
            raise AssertionError("writer.add should not be called when admission fails first")

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="must be admitted") as excinfo:
        service.link(case_id=case.case_id, observation_id=observation.observation_id)
    assert "Artifact" not in str(excinfo.value)
    assert artifact_calls == []


@pytest.mark.parametrize(
    "status",
    [
        AdmissionStatus.PENDING,
        AdmissionStatus.CORROBORATED,
        AdmissionStatus.REJECTED,
        AdmissionStatus.CONFLICT,
    ],
)
def test_create_case_rejects_non_admitted_observation(status: AdmissionStatus) -> None:
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        instrument_id=uuid4(),
        admission_status=status,
    )

    class Observations:
        def get_by_id(self, _observation_id):
            return observation

    class Artifacts:
        def get_by_id(self, artifact_id):
            raise AssertionError(
                "artifact reader should not be called for non-admitted observation"
            )

    class Writer:
        def get_by_observation(self, _observation_id):
            return None

        def add(self, _case_id, _item):
            raise AssertionError("writer.add should not be called for non-admitted observation")

    class Cases:
        def get(self, _case_id):
            return None

        def add(self, _case):
            raise AssertionError(
                "case_reader.add should not be called for non-admitted observation"
            )

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="must be admitted"):
        service.create_case_and_link(observation_id=observation.observation_id, question="test")


def test_link_with_no_artifact_skips_artifact_reader() -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
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
            raise AssertionError("artifact reader should not be called when artifact_id is None")

    class Writer:
        def add(self, _case_id, item):
            saved.append(item)
            return item

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    item = service.link(case_id=case.case_id, observation_id=observation.observation_id)
    assert item.artifact_content_hash is None
    assert saved[0] is item


def test_link_maps_writer_content_hash_conflict_to_link_error() -> None:
    instrument_id = InstrumentId(uuid4())
    run_id = uuid4()
    artifact = ExternalArtifact(
        uuid4(), run_id, "archive://run/a.json", HASH, "application/json", 1, NOW
    )
    observation = ExternalObservation(
        uuid4(),
        run_id,
        NOW,
        date(2026, 8, 14),
        artifact.logical_uri,
        "workbuddy",
        {},
        artifact_id=artifact.artifact_id,
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
    )

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
        def add(self, _case_id, _item):
            raise ValueError("existing Research Case evidence content differs")

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="content differs"):
        service.link(case_id=case.case_id, observation_id=observation.observation_id)


def test_create_case_maps_writer_content_hash_conflict_to_link_error() -> None:
    instrument_id = InstrumentId(uuid4())
    observation = ExternalObservation(
        uuid4(),
        uuid4(),
        NOW,
        date(2026, 8, 14),
        "archive://run/a.json",
        "workbuddy",
        {},
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    cases: dict = {}
    evidence: dict = {}

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
            raise ValueError("existing Research Case evidence content differs")

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())

    with pytest.raises(ExternalEvidenceLinkError, match="content differs"):
        service.create_case_and_link(observation_id=observation.observation_id, question="test")


def test_link_same_content_returns_existing_evidence_without_raising() -> None:
    instrument_id = InstrumentId(uuid4())
    run_id = uuid4()
    artifact = ExternalArtifact(
        uuid4(), run_id, "archive://run/a.json", HASH, "application/json", 1, NOW
    )
    observation = ExternalObservation(
        uuid4(),
        run_id,
        NOW,
        date(2026, 8, 14),
        artifact.logical_uri,
        "workbuddy",
        {},
        artifact_id=artifact.artifact_id,
        instrument_id=instrument_id.value,
    )
    observation = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    case = ResearchCase.create(
        instrument_id=instrument_id,
        as_of_date=observation.as_of,
        question="test",
        horizon="20d",
        created_at=NOW,
    )
    store: dict = {}
    add_calls: list = []

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
        def add(self, case_id, item):
            add_calls.append(item)
            existing = store.get(item.observation_id)
            if existing is not None:
                if existing.content_hash != item.content_hash:
                    raise ValueError("existing Research Case evidence content differs")
                return existing
            store[item.observation_id] = item
            return item

    service = ResearchExternalEvidenceService(Cases(), Observations(), Artifacts(), Writer())
    first = service.link(case_id=case.case_id, observation_id=observation.observation_id)
    second = service.link(case_id=case.case_id, observation_id=observation.observation_id)
    assert first.evidence_id == second.evidence_id
    assert first.content_hash == second.content_hash
    assert first.artifact_content_hash == second.artifact_content_hash
    assert len(add_calls) == 2
