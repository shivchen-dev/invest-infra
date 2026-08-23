"""Focused tests for WorkBuddy shared-directory claiming."""

import json

from invest_pipeline.integrations.workbuddy_shared_directory import (
    SharedDirectoryWorkBuddyGateway,
)


class _Repo:
    def __init__(self):
        self.items = {}

    def add(self, item):
        key = next(
            getattr(item, name)
            for name in ("observation_id", "artifact_id", "run_id")
            if hasattr(item, name)
        )
        self.items[key] = item
        return item

    def get_by_id(self, key):
        return self.items.get(key)

    def list_by_run(self, run_id, *, limit=100, offset=0):
        items = [item for item in self.items.values() if item.run_id == run_id]
        return items[offset : offset + limit]


class _Uow:
    def __init__(self):
        self.external_workflow_runs = _Repo()
        self.external_artifacts = _Repo()
        self.external_observations = _Repo()


def _payload():
    return {
        "workflow_run_id": "ready-run-001",
        "trade_date": "2026-08-14",
        "strategy_id": "screen-v1",
        "status": "succeeded",
        "candidates": [{"symbol": "510300", "reason": "liquid"}],
    }


def test_gateway_claims_ready_package_and_archives_after_import(tmp_path):
    package = tmp_path / "candidate" / "results" / "message-001.ready"
    package.mkdir(parents=True)
    (package / "candidates.json").write_text(json.dumps(_payload()), encoding="utf-8")
    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)

    outcomes = gateway.process_once(uow=_Uow())

    assert len(outcomes) == 1
    assert outcomes[0].error is None
    assert outcomes[0].result is not None
    assert not package.exists()
    assert (tmp_path / "candidate" / "archive" / "message-001").is_dir()
    assert not (tmp_path / "candidate" / "processing" / "message-001").exists()


def test_gateway_moves_invalid_package_to_failed(tmp_path):
    package = tmp_path / "candidate" / "results" / "message-002.ready"
    package.mkdir(parents=True)
    (package / "candidates.json").write_text("not-json", encoding="utf-8")
    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)

    outcomes = gateway.process_once(uow=_Uow())

    assert outcomes[0].result is None
    assert outcomes[0].error
    assert (tmp_path / "candidate" / "failed" / "message-002").is_dir()


def test_gateway_normalizes_legacy_result_json(tmp_path):
    package = tmp_path / "candidate" / "results" / "message-003.ready"
    package.mkdir(parents=True)
    legacy = {
        "workflow_run_id": "legacy-run-003",
        "trade_date": "2026-08-14",
        "strategy_version": "legacy-v1",
        "candidates": [{"symbol": "510050", "reason": "legacy"}],
    }
    (package / "result.json").write_text(json.dumps(legacy), encoding="utf-8")

    outcomes = SharedDirectoryWorkBuddyGateway(tmp_path).process_once(uow=_Uow())

    assert outcomes[0].error is None
    assert outcomes[0].result is not None
    assert outcomes[0].result.run.metadata["strategy_id"] == "legacy-v1"


def test_gateway_ignores_tmp_files_and_recovers_processing_package(tmp_path):
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_ignored.json.tmp").write_text("{}")
    processing = tmp_path / "candidate" / "processing" / "message-004"
    processing.mkdir(parents=True)
    (processing / "candidates.json").write_text(json.dumps(_payload()))
    (tmp_path / "candidate" / "processing" / "message-005.tmp").write_text("{}")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path, source)
    assert gateway.discover_candidates() == ()
    assert [path.name for path in gateway.discover_processing()] == ["message-004"]
    outcomes = gateway.recover_once(uow=_Uow())

    assert len(outcomes) == 1
    assert outcomes[0].error is None
    assert (tmp_path / "candidate" / "archive" / "message-004").is_dir()
