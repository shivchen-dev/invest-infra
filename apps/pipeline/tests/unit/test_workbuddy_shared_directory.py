"""Behavioral tests for WorkBuddy shared-directory candidate intake."""

import json
from pathlib import Path

from invest_pipeline.integrations.workbuddy_shared_directory import (
    SharedDirectoryWorkBuddyGateway,
)


class _Repo:
    def __init__(self) -> None:
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
    def __init__(self) -> None:
        self.external_workflow_runs = _Repo()
        self.external_artifacts = _Repo()
        self.external_observations = _Repo()


def _payload(workflow_run_id: str, *, schema_version: str) -> dict:
    return {
        "schema_version": schema_version,
        "workflow_run_id": workflow_run_id,
        "trade_date": "2026-08-14",
        "strategy_id": "sector-v1",
        "status": "succeeded",
        "candidates": [{"symbol": "600000", "reason": "sector strength"}],
    }


def test_gateway_imports_flat_candidates_files_and_ignores_legacy_audit_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    (source / "candidates_v2.json").write_text(
        json.dumps(_payload("flat-v2", schema_version="2.0.0")), encoding="utf-8"
    )
    (source / "candidates_sector.json").write_text(
        json.dumps(_payload("flat-v1", schema_version="1.0")), encoding="utf-8"
    )
    (source / "result_sector.json").write_text("not an intake", encoding="utf-8")
    (source / "report.json").write_text("not an intake", encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    outcomes = gateway.process_once(uow=_Uow())

    assert {outcome.package for outcome in outcomes} == {
        "candidates_sector.json",
        "candidates_v2.json",
    }
    assert all(outcome.error is None for outcome in outcomes)
    assert {path.name for path in (tmp_path / "workbuddy" / "archive").iterdir()} == {
        "candidates_sector.json",
        "candidates_v2.json",
    }
    assert not tuple((tmp_path / "workbuddy" / "processing").iterdir())
    assert (source / "result_sector.json").exists()
    assert (source / "report.json").exists()
    assert (tmp_path / "invest-infra" / "archive" / "runs" / "2026-08-14" / "flat-v1").is_dir()
    assert (tmp_path / "invest-infra" / "archive" / "runs" / "2026-08-14" / "flat-v2").is_dir()


def test_gateway_claims_invalid_flat_candidate_to_failed(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    input_path = source / "candidates_broken.json"
    input_path.write_text("not-json", encoding="utf-8")

    outcomes = SharedDirectoryWorkBuddyGateway(tmp_path).process_once(uow=_Uow())

    assert outcomes[0].package == input_path.name
    assert outcomes[0].result is None
    assert outcomes[0].error
    assert (tmp_path / "workbuddy" / "failed" / input_path.name).is_file()
    assert not input_path.exists()
