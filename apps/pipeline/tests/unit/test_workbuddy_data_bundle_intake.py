from __future__ import annotations

import copy
import dataclasses
import json
import traceback
from pathlib import Path
from uuid import UUID

import pytest
from invest_domain.integration import (
    ExternalArtifact,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)
from invest_domain.strategy import DataRequest
from invest_pipeline.integrations.workbuddy_data_bundle_archive import (
    DataBundleArchiveOutcome,
)
from invest_pipeline.integrations.workbuddy_data_bundle_codec import (
    DataBundleDecodeError,
)
from invest_pipeline.integrations.workbuddy_data_bundle_intake import (
    DATA_BUNDLE_ARTIFACT_ID_NAME_PREFIX,
    DATA_BUNDLE_METADATA_KIND,
    DATA_BUNDLE_METADATA_SCHEMA,
    DATA_BUNDLE_RUN_ID_NAME_PREFIX,
    DataBundleIntakeConflictError,
    DataBundleIntakeOutcome,
    DataBundlePersistenceError,
    ingest_data_bundle,
)

RUN_ID = UUID("9931e5a0-6bb3-5073-902c-bad147a7cd08")
ARTIFACT_ID = UUID("88d4b9a5-6e88-527b-9297-9c3da70068b4")


def _request_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "archive-001",
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "as_of": "2026-09-02",
        "max_delivery_lag_days": 2,
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "required_fields": ["sector_code", "change_percent"],
                "allowed_connectors": ["tdx-connector"],
            }
        ],
        "output_contract": "workbuddy-data-bundle/1.0",
    }


def _bundle_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": "archive-001",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "attempts": [
                    {
                        "connector": "tdx-connector",
                        "tool": "get_sector_ranking",
                        "parameters": {"opaque_input": "PARAMETER-BODY"},
                        "status": "succeeded",
                        "error_code": None,
                    }
                ],
                "as_of": "2026-09-02",
                "pagination": {"complete": True, "producer_cursor": "CURSOR-BODY"},
                "sample_count": 1,
                "fields": ["sector_code", "change_percent"],
                "units": {"change_percent": "percent"},
                "records": [{"sector_code": "RECORD-BODY", "change_percent": 2.5}],
                "producer_extension": "DATASET-EXTENSION-BODY",
            }
        ],
        "warnings": [{"message": "WARNING-BODY"}],
        "errors": [],
        "producer_extension": "BUNDLE-EXTENSION-BODY",
    }


def _request() -> DataRequest:
    return DataRequest.from_mapping(_request_payload())


def _raw() -> bytes:
    return json.dumps(_bundle_payload(), indent=2).encode()


class _Repo:
    def __init__(self, state: dict, key: str, owner: _Uow) -> None:
        self.state = state
        self.key = key
        self.owner = owner
        self.add_calls: list[object] = []

    def get_by_id(self, object_id):
        if self.owner.fail == f"get-{self.key}":
            raise RuntimeError(
                "database path=/private hash=deadbeef id=secret request_id=archive-001"
            )
        return self.state[self.key].get(object_id)

    def add(self, value):
        self.add_calls.append(value)
        if self.owner.fail == f"add-{self.key}":
            raise RuntimeError(
                "database path=/private hash=deadbeef id=secret request_id=archive-001"
            )
        object_id = value.run_id if self.key == "runs" else value.artifact_id
        self.owner.pending.append((self.key, object_id, value))
        return value


class _Uow:
    def __init__(self, state: dict | None = None, *, fail: str | None = None) -> None:
        self.state = state or {"runs": {}, "artifacts": {}}
        self.fail = fail
        self.enter_count = 0
        self.exit_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.pending: list[tuple[str, UUID, object]] = []
        self.external_workflow_runs = _Repo(self.state, "runs", self)
        self.external_artifacts = _Repo(self.state, "artifacts", self)

    def __enter__(self):
        self.enter_count += 1
        if self.fail == "enter":
            raise RuntimeError(
                "database path=/private hash=deadbeef id=secret request_id=archive-001"
            )
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit_count += 1
        if exc_type is not None:
            self.rollback_count += 1
            self.pending.clear()
            return None
        try:
            self.commit_count += 1
            if self.fail == "commit":
                raise RuntimeError(
                    "database path=/private hash=deadbeef id=secret request_id=archive-001"
                )
            for key, object_id, value in self.pending:
                self.state[key][object_id] = value
            self.pending.clear()
        except Exception:
            self.rollback_count += 1
            self.pending.clear()
            raise
        return None


def _seed_expected(tmp_path: Path) -> tuple[dict, DataBundleIntakeOutcome]:
    state = {"runs": {}, "artifacts": {}}
    outcome = ingest_data_bundle(_request(), _raw(), tmp_path, _Uow(state))
    return state, outcome


def test_first_intake_commits_exact_deterministic_domain_objects(tmp_path: Path) -> None:
    uow = _Uow()

    outcome = ingest_data_bundle(_request(), _raw(), tmp_path, uow)

    assert isinstance(outcome, DataBundleIntakeOutcome)
    assert isinstance(outcome.archive, DataBundleArchiveOutcome)
    assert dataclasses.fields(DataBundleIntakeOutcome)[0].name == "archive"
    assert outcome.idempotent is False
    assert outcome.archive.idempotent is False
    assert DATA_BUNDLE_RUN_ID_NAME_PREFIX == "invest-infra:data-bundle-intake:run:v1:"
    assert DATA_BUNDLE_ARTIFACT_ID_NAME_PREFIX == "invest-infra:data-bundle-intake:artifact:v1:"
    assert outcome.run.run_id == RUN_ID
    assert outcome.artifact.artifact_id == ARTIFACT_ID
    assert outcome.run == ExternalWorkflowRun(
        run_id=RUN_ID,
        producer="workbuddy",
        schema_version="workbuddy-data-bundle/1.0",
        producer_status=ProducerStatus.SUCCEEDED,
        intake_status=IntakeStatus.ACCEPTED,
        started_at=outcome.archive.validated_bundle.bundle.generated_at,
        finished_at=outcome.archive.validated_bundle.bundle.generated_at,
        metadata=outcome.run.metadata,
    )
    assert outcome.artifact == ExternalArtifact(
        artifact_id=ARTIFACT_ID,
        run_id=RUN_ID,
        logical_uri="archive://runs/archive-001/data-bundle.json",
        content_hash=outcome.archive.validated_bundle.raw_sha256,
        media_type="application/json",
        size_bytes=len(_raw()),
        created_at=outcome.archive.validated_bundle.bundle.generated_at,
        metadata=outcome.artifact.metadata,
    )
    assert uow.enter_count == uow.exit_count == uow.commit_count == 1
    assert uow.rollback_count == 0
    assert uow.external_workflow_runs.add_calls == [outcome.run]
    assert uow.external_artifacts.add_calls == [outcome.artifact]


def test_fully_matching_retry_is_database_idempotent_without_adds(tmp_path: Path) -> None:
    state, first = _seed_expected(tmp_path)
    retry_uow = _Uow(state)

    second = ingest_data_bundle(_request(), _raw(), tmp_path, retry_uow)

    assert second.archive.idempotent is True
    assert second.idempotent is True
    assert second.run == first.run
    assert second.artifact == first.artifact
    assert retry_uow.external_workflow_runs.add_calls == []
    assert retry_uow.external_artifacts.add_calls == []
    assert retry_uow.commit_count == 1


def test_equivalent_retry_uses_first_archived_raw_hash_and_size(tmp_path: Path) -> None:
    state, first = _seed_expected(tmp_path)
    equivalent_raw = json.dumps(_bundle_payload(), separators=(",", ":")).encode()

    second = ingest_data_bundle(_request(), equivalent_raw, tmp_path, _Uow(state))

    assert equivalent_raw != _raw()
    assert second.archive.idempotent is True
    assert second.idempotent is True
    assert second.artifact.content_hash == first.artifact.content_hash
    assert second.artifact.size_bytes == len(_raw())


def test_matching_run_only_state_safely_adds_artifact(tmp_path: Path) -> None:
    state, expected = _seed_expected(tmp_path)
    state["artifacts"].clear()
    uow = _Uow(state)

    outcome = ingest_data_bundle(_request(), _raw(), tmp_path, uow)

    assert outcome.idempotent is False
    assert uow.external_workflow_runs.add_calls == []
    assert uow.external_artifacts.add_calls == [expected.artifact]
    assert state["artifacts"] == {ARTIFACT_ID: expected.artifact}


@pytest.mark.parametrize(
    "variant", ["artifact-only", "run-differs", "artifact-differs", "both-differ"]
)
def test_conflicts_roll_back_without_adds(tmp_path: Path, variant: str) -> None:
    state, expected = _seed_expected(tmp_path)
    if variant == "artifact-only":
        state["runs"].clear()
    if variant in {"run-differs", "both-differ"}:
        state["runs"][RUN_ID] = dataclasses.replace(expected.run, producer="other")
    if variant in {"artifact-differs", "both-differ"}:
        state["artifacts"][ARTIFACT_ID] = dataclasses.replace(
            expected.artifact, logical_uri="archive://different/data-bundle.json"
        )
    uow = _Uow(state)

    with pytest.raises(DataBundleIntakeConflictError) as exc_info:
        ingest_data_bundle(_request(), _raw(), tmp_path, uow)

    assert exc_info.value.code == "data_bundle_intake_conflict"
    assert exc_info.value.message == ("Data bundle intake conflicts with existing immutable state.")
    assert uow.external_workflow_runs.add_calls == []
    assert uow.external_artifacts.add_calls == []
    assert uow.rollback_count == 1


def test_archive_failure_never_enters_uow(tmp_path: Path) -> None:
    uow = _Uow()

    with pytest.raises(DataBundleDecodeError):
        ingest_data_bundle(_request(), b"not-json", tmp_path, uow)

    assert uow.enter_count == 0
    assert uow.state == {"runs": {}, "artifacts": {}}


@pytest.mark.parametrize(
    "failure", ["enter", "get-runs", "get-artifacts", "add-runs", "add-artifacts", "commit"]
)
def test_persistence_failures_are_sanitized_and_do_not_commit(tmp_path: Path, failure: str) -> None:
    uow = _Uow(fail=failure)

    with pytest.raises(DataBundlePersistenceError) as exc_info:
        ingest_data_bundle(_request(), _raw(), tmp_path, uow)

    assert exc_info.value.code == "data_bundle_persistence_failure"
    assert exc_info.value.message == "Data bundle intake could not be persisted safely."
    assert str(exc_info.value) == exc_info.value.message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    formatted_traceback = "".join(
        traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb)
    )
    for secret in ("/private", "deadbeef", "secret", "archive-001", "database"):
        assert secret not in formatted_traceback
    assert uow.state == {"runs": {}, "artifacts": {}}
    if failure != "enter":
        assert uow.rollback_count == 1


def test_retry_after_commit_failure_uses_preserved_archive_and_succeeds(
    tmp_path: Path,
) -> None:
    state = {"runs": {}, "artifacts": {}}
    with pytest.raises(DataBundlePersistenceError):
        ingest_data_bundle(_request(), _raw(), tmp_path, _Uow(state, fail="commit"))

    retry = ingest_data_bundle(_request(), _raw(), tmp_path, _Uow(state))

    assert retry.archive.idempotent is True
    assert retry.idempotent is False
    assert state["runs"] == {RUN_ID: retry.run}
    assert state["artifacts"] == {ARTIFACT_ID: retry.artifact}


def test_metadata_is_safe_and_inputs_are_not_mutated(tmp_path: Path) -> None:
    request = _request()
    raw = _raw()
    original_request = copy.deepcopy(request)
    original_raw = bytes(raw)

    outcome = ingest_data_bundle(request, raw, tmp_path, _Uow())

    assert request == original_request
    assert raw == original_raw
    expected_metadata = {
        "request_id": "archive-001",
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "archive_uri": "archive://runs/archive-001",
        "canonical_sha256": outcome.archive.validated_bundle.canonical_sha256,
        "kind": DATA_BUNDLE_METADATA_KIND,
        "metadata_schema": DATA_BUNDLE_METADATA_SCHEMA,
    }
    assert outcome.run.metadata == expected_metadata
    assert outcome.artifact.metadata == expected_metadata
    metadata_text = repr((outcome.run.metadata, outcome.artifact.metadata))
    for forbidden in (
        "RECORD-BODY",
        "PARAMETER-BODY",
        "WARNING-BODY",
        "CURSOR-BODY",
        "DATASET-EXTENSION-BODY",
        "BUNDLE-EXTENSION-BODY",
        str(tmp_path),
    ):
        assert forbidden not in metadata_text
    assert "raw_bytes" not in metadata_text
    assert all(not isinstance(value, (dict, list)) for value in outcome.run.metadata.values())
    assert all(
        not isinstance(value, (dict, list)) for value in outcome.artifact.metadata.values()
    )
