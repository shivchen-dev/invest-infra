from datetime import UTC, date, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest
from invest_domain import (
    AdmissionStatus,
    AdmissionVerification,
    ExternalArtifact,
    ExternalEvidenceItem,
    ExternalObservation,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
    evaluate_admission,
    observation_to_evidence_item,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)
HASH = "a" * 64


def test_workflow_run_keeps_three_statuses_and_immutable_metadata() -> None:
    run = ExternalWorkflowRun(uuid4(), "workbuddy", "2.0.0", ProducerStatus.SUCCEEDED,
                               IntakeStatus.PENDING, NOW, metadata={"x": 1})
    assert run.producer_status is ProducerStatus.SUCCEEDED
    assert run.intake_status is IntakeStatus.PENDING
    assert isinstance(run.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        run.metadata["x"] = 2


def test_artifact_validates_hash_size_and_clock() -> None:
    artifact = ExternalArtifact(uuid4(), uuid4(), "artifact://run/a.json", HASH,
                                "application/json", 0, NOW)
    assert artifact.content_hash == HASH
    with pytest.raises(ValueError):
        ExternalArtifact(uuid4(), uuid4(), "artifact://run/a.json", "bad", "text/plain", 1, NOW)
    with pytest.raises(ValueError):
        ExternalArtifact(uuid4(), uuid4(), "artifact://run/a.json", HASH, "text/plain", -1, NOW)


def test_observation_is_not_evidence_and_rejects_datetime_as_of() -> None:
    observation = ExternalObservation(uuid4(), uuid4(), NOW, date(2026, 8, 14),
                                      "https://example.test", "workbuddy", {"score": 1})
    assert observation.admission_status is AdmissionStatus.PENDING
    assert not hasattr(observation, "evidence_id")
    with pytest.raises(TypeError):
        ExternalObservation(uuid4(), uuid4(), NOW, NOW, "https://example.test", "workbuddy", {})


def test_invalid_finished_time_and_naive_clock_are_rejected() -> None:
    with pytest.raises(ValueError):
        ExternalWorkflowRun(uuid4(), "workbuddy", "2.0.0", ProducerStatus.FAILED,
                            IntakeStatus.REJECTED, NOW, NOW.replace(hour=9))
    with pytest.raises(ValueError):
        ExternalWorkflowRun(uuid4(), "workbuddy", "2.0.0", ProducerStatus.SUCCEEDED,
                            IntakeStatus.ACCEPTED, datetime(2026, 8, 14))


def test_admission_requires_all_checks_before_admitted() -> None:
    observation = ExternalObservation(uuid4(), uuid4(), NOW, date(2026, 8, 14),
                                      "https://example.test", "workbuddy", {})
    decision = evaluate_admission(
        observation,
        AdmissionVerification(True, True, True, True, decided_by="raa"),
    )

    assert decision.status is AdmissionStatus.ADMITTED
    updated = observation.apply_admission(decision)
    assert updated.admission_status is AdmissionStatus.ADMITTED
    assert updated.metadata["admission"]["decided_by"] == "raa"


def test_admission_conflict_and_pending_cross_check_are_distinct() -> None:
    observation = ExternalObservation(uuid4(), uuid4(), NOW, date(2026, 8, 14),
                                      "https://example.test", "workbuddy", {})
    corroborated = evaluate_admission(
        observation,
        AdmissionVerification(True, True, True, None),
    )
    conflict = evaluate_admission(
        observation,
        AdmissionVerification(True, True, True, True, conflict_detected=True),
    )

    assert corroborated.status is AdmissionStatus.CORROBORATED
    assert conflict.status is AdmissionStatus.CONFLICT


def test_only_admitted_observation_becomes_provenance_bound_evidence() -> None:
    run_id = uuid4()
    artifact = ExternalArtifact(uuid4(), run_id, "archive://run/a.json", HASH,
                                "application/json", 12, NOW)
    observation = ExternalObservation(
        uuid4(), run_id, NOW, date(2026, 8, 14), artifact.logical_uri, "workbuddy",
        {"symbol": "510300", "score": 0.8}, artifact_id=artifact.artifact_id,
    )
    decision = evaluate_admission(
        observation, AdmissionVerification(True, True, True, True, decided_by="raa")
    )
    admitted = observation.apply_admission(decision)
    item = observation_to_evidence_item(admitted, artifact)

    assert isinstance(item, ExternalEvidenceItem)
    assert item.evidence_id.startswith(f"ext-evi:{observation.observation_id}:")
    assert item.artifact_content_hash == HASH
    assert item.admission["decided_by"] == "raa"
    with pytest.raises(ValueError, match="only admitted"):
        observation_to_evidence_item(observation, artifact)
    with pytest.raises(ValueError, match="artifact is required"):
        observation_to_evidence_item(admitted)


def test_evidence_conversion_rejects_wrong_artifact() -> None:
    observation = ExternalObservation(uuid4(), uuid4(), NOW, date(2026, 8, 14),
                                      "archive://run/a.json", "workbuddy", {})
    admitted = observation.apply_admission(
        evaluate_admission(observation, AdmissionVerification(True, True, True, True))
    )
    wrong_artifact = ExternalArtifact(uuid4(), admitted.run_id, "archive://run/b.json", HASH,
                                     "application/json", 1, NOW)
    with pytest.raises(ValueError, match="does not belong"):
        observation_to_evidence_item(admitted, wrong_artifact)
