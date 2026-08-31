import copy
import json
from types import MappingProxyType, SimpleNamespace
from uuid import uuid4

import pytest
from invest_api.application.external_workflows import (
    ExternalWorkflowQueryService,
    project_candidate_lineage,
)


class _Runs:
    def __init__(self, run):
        self.run = run

    def list_recent(self, *, limit, offset):
        return [self.run][offset : offset + limit]

    def get_by_id(self, run_id):
        return self.run if run_id == self.run.run_id else None


class _Children:
    def __init__(self, items):
        self.items = items

    def list_by_run(self, run_id, *, limit, offset):
        return self.items[offset : offset + limit]

    def list_recent(self, *, status, limit, offset):
        return self.items[offset : offset + limit]

    def get_by_id(self, artifact_id):
        if self.items and artifact_id == getattr(self.items[0], "artifact_id", None):
            return self.items[0]
        return None


def test_external_workflow_query_service_delegates_read_contract():
    run_id = uuid4()
    run = SimpleNamespace(run_id=run_id)
    artifact = SimpleNamespace(run_id=run_id)
    observation = SimpleNamespace(run_id=run_id)
    service = ExternalWorkflowQueryService(
        run_repository=_Runs(run),
        artifact_repository=_Children([artifact]),
        observation_repository=_Children([observation]),
    )

    assert service.list_runs(limit=10, offset=0) == [run]
    assert service.get_run(run_id) is run
    assert service.list_artifacts(run_id, limit=10, offset=0) == [artifact]
    assert service.list_observations(run_id, limit=10, offset=0) == [observation]
    assert service.list_radar(status=None, limit=10, offset=0) == [observation]
    assert service.get_artifact(uuid4()) is None


_SECTOR_STAGE = {
    "stage_key": "sector_selection",
    "stage_result_id": "sector-result-1",
    "stage_result_sha256": "a" * 64,
    "strategy_key": "sector-strength-v1",
    "strategy_version": "1.0.0",
    "strategy_artifact_hash": "b" * 64,
    "as_of": "2026-08-14",
    "constituent_snapshot_sha256": "c" * 64,
}

_STOCK_STAGE = {
    "stage_key": "stock_screening",
    "stage_result_id": "stock-result-1",
    "stage_result_sha256": "d" * 64,
    "strategy_key": "stock-screen-v1",
    "strategy_version": "1.0.0",
    "strategy_artifact_hash": "e" * 64,
    "as_of": "2026-08-14",
    "upstream_stage_result_id": "sector-result-1",
    "upstream_stage_result_sha256": "a" * 64,
}


def _valid_lineage():
    return {
        "schema_version": "candidate-lineage/1.0",
        "stages": [copy.deepcopy(_SECTOR_STAGE), copy.deepcopy(_STOCK_STAGE)],
    }


def test_project_candidate_lineage_returns_whitelisted_dict_and_drops_sensitive_keys():
    metadata = {"lineage": _valid_lineage(), "uri": "s3://bucket/run.json"}
    for stage in metadata["lineage"]["stages"]:
        stage["uri"] = "s3://bucket/x.json"
        stage["path"] = "/tmp/x.json"
        stage["raw_payload"] = {"secret": "value"}
        stage["exception"] = "boom"
        stage["traceback"] = "stack\nframe"
        stage["metadata"] = {"leaky": "yes"}
    metadata["lineage"]["extra_top_level"] = "leak"

    result = project_candidate_lineage(metadata)

    assert result == {
        "schema_version": "candidate-lineage/1.0",
        "stages": [copy.deepcopy(_SECTOR_STAGE), copy.deepcopy(_STOCK_STAGE)],
    }
    assert json.dumps(result)


def test_project_candidate_lineage_does_not_mutate_input():
    metadata = {"lineage": _valid_lineage(), "top": "level"}
    metadata["lineage"]["stages"][0]["extra"] = {"a": 1}
    snapshot = copy.deepcopy(metadata)

    project_candidate_lineage(metadata)

    assert metadata == snapshot


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        "metadata",
        [],
        42,
        {},
        {"lineage": None},
        {"lineage": "not-a-dict"},
        {"lineage": {"schema_version": "candidate-lineage/0.9", "stages": []}},
        {"lineage": {"schema_version": "candidate-lineage/1.0", "stages": []}},
        {"lineage": {"schema_version": "candidate-lineage/1.0", "stages": [_SECTOR_STAGE]}},
        {
            "lineage": {
                "schema_version": "candidate-lineage/1.0",
                "stages": [_SECTOR_STAGE, _SECTOR_STAGE, _STOCK_STAGE],
            }
        },
        {
            "lineage": {
                "schema_version": "candidate-lineage/1.0",
                "stages": [_STOCK_STAGE, _SECTOR_STAGE],
            }
        },
        {
            "lineage": {
                "schema_version": "candidate-lineage/1.0",
                "stages": ["not-a-dict", _SECTOR_STAGE],
            }
        },
        {
            "lineage": {
                "schema_version": "candidate-lineage/1.0",
                "stages": [_SECTOR_STAGE, "not-a-dict"],
            }
        },
    ],
)
def test_project_candidate_lineage_returns_none_for_malformed_structure(metadata):
    assert project_candidate_lineage(metadata) is None


def test_project_candidate_lineage_returns_none_when_required_string_invalid():
    mutations = [
        lambda stages: stages[0].pop("constituent_snapshot_sha256"),
        lambda stages: stages[0].update({"stage_result_id": ""}),
        lambda stages: stages[1].update({"upstream_stage_result_sha256": 12345}),
        lambda stages: stages[1].update({"strategy_artifact_hash": None}),
        lambda stages: stages[0].update({"stage_key": "stock_screening"}),
    ]
    for mutate in mutations:
        lineage = _valid_lineage()
        mutate(lineage["stages"])
        assert project_candidate_lineage({"lineage": lineage}) is None


def test_project_candidate_lineage_accepts_mapping_and_sequence_abstractions():
    sector = MappingProxyType(copy.deepcopy(_SECTOR_STAGE))
    stock = MappingProxyType(copy.deepcopy(_STOCK_STAGE))
    lineage = MappingProxyType({
        "schema_version": "candidate-lineage/1.0",
        "stages": (sector, stock),
    })
    metadata = MappingProxyType({"lineage": lineage})

    result = project_candidate_lineage(metadata)

    assert result == {
        "schema_version": "candidate-lineage/1.0",
        "stages": [copy.deepcopy(_SECTOR_STAGE), copy.deepcopy(_STOCK_STAGE)],
    }
    for bad_stages in ("two", b"two"):
        bad_lineage = copy.deepcopy(_valid_lineage())
        bad_lineage["stages"] = bad_stages
        assert project_candidate_lineage({"lineage": bad_lineage}) is None


def _build_service(runs_repo):
    return ExternalWorkflowQueryService(
        run_repository=runs_repo,
        artifact_repository=_Children([]),
        observation_repository=_Children([]),
    )


def test_get_candidate_lineage_delegates_and_projects():
    run_id = uuid4()
    metadata = {"lineage": _valid_lineage()}
    run = SimpleNamespace(run_id=run_id, metadata=metadata)
    service = _build_service(_Runs(run))

    assert service.get_candidate_lineage(run_id) == project_candidate_lineage(metadata)


def test_get_candidate_lineage_returns_none_when_run_missing():
    requested_id = uuid4()
    run = SimpleNamespace(run_id=uuid4(), metadata={"lineage": _valid_lineage()})
    service = _build_service(_Runs(run))

    assert service.get_candidate_lineage(requested_id) is None


def test_get_candidate_lineage_returns_none_when_metadata_attribute_missing():
    run_id = uuid4()
    run = SimpleNamespace(run_id=run_id)
    service = _build_service(_Runs(run))

    assert service.get_candidate_lineage(run_id) is None


def test_get_candidate_lineage_returns_none_when_metadata_is_none():
    run_id = uuid4()
    run = SimpleNamespace(run_id=run_id, metadata=None)
    service = _build_service(_Runs(run))

    assert service.get_candidate_lineage(run_id) is None


def test_get_candidate_lineage_calls_repository_get_by_id_once_with_requested_id():
    run_id = uuid4()
    run = SimpleNamespace(run_id=run_id, metadata={"lineage": _valid_lineage()})
    runs = _Runs(run)
    calls = []
    original_get_by_id = runs.get_by_id

    def _counting_get_by_id(requested_run_id):
        calls.append(requested_run_id)
        return original_get_by_id(requested_run_id)

    runs.get_by_id = _counting_get_by_id
    service = _build_service(runs)

    service.get_candidate_lineage(run_id)

    assert calls == [run_id]
