import copy
import json
from types import MappingProxyType, SimpleNamespace
from uuid import uuid4

import pytest
from invest_api.application.external_workflows import (
    ExternalWorkflowQueryService,
    project_candidate_lineage,
)

# AdmissionStatus name mirror so tests stay decoupled from the domain package.
_ADMISSION_PENDING = "pending"
_ADMISSION_CORROBORATED = "corroborated"
_ADMISSION_CONFLICT = "conflict"


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


# ---------------------------------------------------------------------------
# get_candidate_lineage_states — P0-B5 four-state Application slice.
# ---------------------------------------------------------------------------

_ADMISSION_OBSERVATION_KEYS = {"observation_id", "admission_status"}


class _Observation:
    """Stand-in observation exposing only the fields the new query reads."""

    def __init__(self, observation_id, observed_at, as_of, admission_status):
        self.observation_id = observation_id
        self.observed_at = observed_at
        self.as_of = as_of
        # Use a value-holding object so `.value` access mirrors the real enum.
        self.admission_status = SimpleNamespace(value=admission_status)


class _ObservationRepo:
    def __init__(self, observations):
        self.observations = list(observations)
        self.list_calls = []

    def list_by_run(self, run_id, *, limit, offset):
        self.list_calls.append((run_id, limit, offset))
        return list(self.observations)

    def list_recent(self, *, status, limit, offset):
        return []


def _build_states_service(run, observations):
    observation_repo = _ObservationRepo(observations)
    service = ExternalWorkflowQueryService(
        run_repository=_Runs(run),
        artifact_repository=_Children([]),
        observation_repository=observation_repo,
    )
    return service, observation_repo


def test_get_candidate_lineage_states_missing_short_circuit_no_observation_read():
    requested_id = uuid4()
    run = SimpleNamespace(
        run_id=uuid4(),
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata={"lineage": _valid_lineage()},
    )
    service, observation_repo = _build_states_service(run, [])

    assert service.get_candidate_lineage_states(requested_id) is None
    assert observation_repo.list_calls == []


def test_get_candidate_lineage_states_empty_state_shape_and_archive_finished_at_none():
    run_id = uuid4()
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="2026-08-14T00:00:00Z",
        finished_at=None,
        metadata={"lineage": _valid_lineage()},
    )
    service, _ = _build_states_service(run, [])

    result = service.get_candidate_lineage_states(run_id)

    assert set(result.keys()) == {"run_id", "lineage", "states"}
    assert result["run_id"] is run_id
    assert result["lineage"] == project_candidate_lineage(run.metadata)
    states = result["states"]
    assert set(states.keys()) == {"archive", "intake", "admission", "research"}
    assert states["archive"] == {
        "availability": "available",
        "producer_status": "succeeded",
        "intake_status": "accepted",
        "started_at": "2026-08-14T00:00:00Z",
        "finished_at": None,
    }
    assert states["intake"]["availability"] == "unavailable"
    assert states["intake"]["count"] == 0
    assert states["intake"]["items"] == []
    assert states["admission"]["availability"] == "unavailable"
    assert states["admission"]["count"] == 0
    assert states["admission"]["items"] == []
    assert states["admission"]["decided_at"] is None
    assert states["research"] == {"availability": "unavailable"}


@pytest.mark.parametrize(
    "observations,expected_availability",
    [
        ([], "unavailable"),
        ([_Observation(uuid4(), "oa", "ao", _ADMISSION_PENDING)], "available"),
        (
            [
                _Observation(uuid4(), "oa1", "ao1", _ADMISSION_PENDING),
                _Observation(uuid4(), "oa2", "ao2", _ADMISSION_CORROBORATED),
            ],
            "partial",
        ),
        (
            [
                _Observation(uuid4(), "oa1", "ao1", _ADMISSION_PENDING),
                _Observation(uuid4(), "oa2", "ao2", _ADMISSION_CONFLICT),
            ],
            "conflict",
        ),
        (
            [
                _Observation(uuid4(), "oa1", "ao1", _ADMISSION_PENDING),
                _Observation(uuid4(), "oa2", "ao2", _ADMISSION_PENDING),
            ],
            "available",
        ),
    ],
)
def test_get_candidate_lineage_states_admission_availability_matrix(
    observations, expected_availability
):
    run_id = uuid4()
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata={"lineage": _valid_lineage()},
    )
    service, _ = _build_states_service(run, observations)

    result = service.get_candidate_lineage_states(run_id)

    admission = result["states"]["admission"]
    assert admission["availability"] == expected_availability
    assert admission["count"] == len(observations)
    assert admission["decided_at"] is None
    for item in admission["items"]:
        assert set(item.keys()) == _ADMISSION_OBSERVATION_KEYS


def test_get_candidate_lineage_states_preserves_observation_order_in_intake_and_admission():
    run_id = uuid4()
    first = _Observation(uuid4(), "obs1", "as1", _ADMISSION_PENDING)
    second = _Observation(uuid4(), "obs2", "as2", _ADMISSION_CORROBORATED)
    third = _Observation(uuid4(), "obs3", "as3", _ADMISSION_PENDING)
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata={"lineage": _valid_lineage()},
    )
    service, observation_repo = _build_states_service(run, [third, first, second])

    result = service.get_candidate_lineage_states(run_id)

    intake_items = result["states"]["intake"]["items"]
    admission_items = result["states"]["admission"]["items"]
    assert [item["observation_id"] for item in intake_items] == [
        third.observation_id,
        first.observation_id,
        second.observation_id,
    ]
    assert [item["observation_id"] for item in admission_items] == [
        third.observation_id,
        first.observation_id,
        second.observation_id,
    ]
    assert observation_repo.list_calls == [(run_id, 100, 0)]


@pytest.mark.parametrize(
    "metadata",
    [
        {"lineage": _valid_lineage()},
        {"lineage": None},
        {"lineage": "not-a-dict"},
        None,
        "metadata",
    ],
)
def test_get_candidate_lineage_states_lineage_present_and_legacy_none(metadata):
    run_id = uuid4()
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata=metadata,
    )
    service, _ = _build_states_service(run, [])

    result = service.get_candidate_lineage_states(run_id)

    assert result["lineage"] == project_candidate_lineage(metadata)


@pytest.mark.parametrize(
    "state_key,expected_keys",
    [
        (
            "archive",
            {
                "availability",
                "producer_status",
                "intake_status",
                "started_at",
                "finished_at",
            },
        ),
        ("intake", {"availability", "count", "items"}),
        ("admission", {"availability", "count", "decided_at", "items"}),
        ("research", {"availability"}),
        ("states", {"archive", "intake", "admission", "research"}),
    ],
)
def test_get_candidate_lineage_states_exact_whitelist_keys(state_key, expected_keys):
    run_id = uuid4()
    obs = _Observation(uuid4(), "oa", "ao", _ADMISSION_PENDING)
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata={"lineage": _valid_lineage()},
    )
    service, _ = _build_states_service(run, [obs])

    result = service.get_candidate_lineage_states(run_id)

    if state_key == "states":
        assert set(result["states"].keys()) == expected_keys
    else:
        assert set(result["states"][state_key].keys()) == expected_keys


def test_get_candidate_lineage_states_admission_decided_at_never_substitutes_observed_at():
    run_id = uuid4()
    obs = _Observation(uuid4(), "observed-at-value", "as-of-value", _ADMISSION_PENDING)
    run = SimpleNamespace(
        run_id=run_id,
        producer_status=SimpleNamespace(value="succeeded"),
        intake_status=SimpleNamespace(value="accepted"),
        started_at="started",
        finished_at="finished",
        metadata={"lineage": _valid_lineage()},
    )
    service, _ = _build_states_service(run, [obs])

    result = service.get_candidate_lineage_states(run_id)

    admission = result["states"]["admission"]
    assert admission["decided_at"] is None
    item = admission["items"][0]
    assert "observed_at" not in item
    assert "decided_at" not in item
    assert item == {
        "observation_id": obs.observation_id,
        "admission_status": _ADMISSION_PENDING,
    }
