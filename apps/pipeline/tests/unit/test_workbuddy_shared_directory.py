"""Behavioral tests for WorkBuddy shared-directory candidate intake."""

import json
from pathlib import Path

from invest_pipeline.integrations.workbuddy_shared_directory import (
    ArchiveConflictError,
    SharedDirectoryImport,
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


def _payload(
    workflow_run_id: str,
    *,
    schema_version: str = "2.0.0",
    candidates: list[dict] | None = None,
    status: str = "succeeded",
) -> dict:
    return {
        "schema_version": schema_version,
        "workflow_run_id": workflow_run_id,
        "trade_date": "2026-08-14",
        "strategy_id": "sector-v1",
        "status": status,
        "candidates": candidates
        if candidates is not None
        else [{"symbol": "600000", "reason": "sector strength"}],
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


def test_gateway_exposes_diagnostics_on_success(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    (source / "candidates_diag.json").write_text(
        json.dumps(
            _payload(
                "diag-001",
                candidates=[
                    {"symbol": "510300", "reason": "liquid"},
                    {"symbol": "159915", "reason": "growth"},
                ],
            )
        ),
        encoding="utf-8",
    )

    outcomes = SharedDirectoryWorkBuddyGateway(tmp_path).process_once(
        uow=_Uow(),
        resolver=lambda symbol: "510300" if symbol == "510300" else None,
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert isinstance(outcome, SharedDirectoryImport)
    assert outcome.error is None
    assert outcome.result is not None
    assert outcome.archive_uri == "archive://runs/2026-08-14/diag-001"
    assert outcome.accepted_count == 2
    assert outcome.rejected_count == 0
    assert outcome.needs_symbol_resolution_count == 1
    assert outcome.archive_idempotent is False
    assert outcome.import_idempotent is False
    assert outcome.conflict is False
    assert outcome.findings
    statuses = {
        observation.metadata["candidate_status"] for observation in outcome.result.observations
    }
    assert statuses == {"pending_validation", "needs_symbol_resolution"}


def test_gateway_routes_archive_conflict_to_conflict_bucket(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    base_payload = _payload(
        "conflict-001",
        candidates=[{"symbol": "510300", "reason": "liquid"}],
    )
    (source / "candidates_a.json").write_text(json.dumps(base_payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    first = gateway.process_once(uow=_Uow())
    assert len(first) == 1
    assert first[0].error is None
    assert first[0].conflict is False

    # Different bytes, same workflow_run_id+trade_date: archive_candidates will
    # detect a divergent hash and the gateway must route to conflict/.
    tampered = dict(base_payload, status="cancelled")
    (source / "candidates_b.json").write_text(json.dumps(tampered), encoding="utf-8")

    second = gateway.process_once(uow=_Uow())
    assert len(second) == 1
    conflict_outcome = second[0]
    assert isinstance(conflict_outcome, SharedDirectoryImport)
    assert conflict_outcome.error is not None
    assert conflict_outcome.result is None
    assert conflict_outcome.conflict is True
    assert conflict_outcome.archive_uri == "archive://runs/2026-08-14/conflict-001"
    assert conflict_outcome.archive_idempotent is False
    assert conflict_outcome.import_idempotent is None
    assert conflict_outcome.accepted_count == 1
    assert conflict_outcome.rejected_count == 0

    assert (tmp_path / "workbuddy" / "archive" / "candidates_a.json").is_file()
    assert (tmp_path / "workbuddy" / "conflict" / "candidates_b.json").is_file()
    assert not (tmp_path / "workbuddy" / "failed" / "candidates_b.json").exists()
    assert not (tmp_path / "workbuddy" / "archive" / "candidates_b.json").exists()


def test_gateway_routes_ready_package_conflict_to_conflict_bucket(tmp_path: Path) -> None:
    ready_dir = tmp_path / "workbuddy" / "results"
    ready_dir.mkdir(parents=True)
    package = ready_dir / "ready-conflict-001.ready"
    package.mkdir()
    base_payload = _payload("ready-conflict-001")
    (package / "candidates.json").write_text(json.dumps(base_payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    first = gateway.process_once(uow=_Uow())
    assert first[0].error is None
    assert first[0].conflict is False

    tampered = ready_dir / "ready-conflict-002.ready"
    tampered.mkdir()
    (tampered / "candidates.json").write_text(
        json.dumps(dict(base_payload, status="cancelled")), encoding="utf-8"
    )

    second = gateway.process_once(uow=_Uow())
    assert second[0].conflict is True
    assert second[0].error is not None
    assert isinstance(second[0].error, str)

    assert (tmp_path / "workbuddy" / "archive" / "ready-conflict-001").is_dir()
    assert (tmp_path / "workbuddy" / "conflict" / "ready-conflict-002").is_dir()
    assert not (tmp_path / "workbuddy" / "failed" / "ready-conflict-002").exists()


def test_archive_conflict_error_carries_identity_fields() -> None:
    exc = ArchiveConflictError(
        workflow_run_id="run-7",
        trade_date="2026-08-14",
        archive_uri="archive://runs/2026-08-14/run-7",
    )

    assert exc.workflow_run_id == "run-7"
    assert exc.trade_date == "2026-08-14"
    assert exc.archive_uri == "archive://runs/2026-08-14/run-7"
    assert "run-7" in str(exc)


def test_gateway_idempotent_rerun_reports_both_layers_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    payload = _payload("idem-001")
    (source / "candidates_idem_first.json").write_text(json.dumps(payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    uow = _Uow()
    first = gateway.process_once(uow=uow)
    assert len(first) == 1
    assert first[0].error is None
    assert first[0].archive_idempotent is False
    assert first[0].import_idempotent is False

    # Re-stage the same payload under a different filename so the workbuddy
    # archive destination does not collide. archive_candidates still sees the
    # existing run_dir and the bridge must reuse the existing run/artifact.
    (source / "candidates_idem_second.json").write_text(json.dumps(payload), encoding="utf-8")
    second = gateway.process_once(uow=uow)
    assert len(second) == 1
    rerun = second[0]
    assert rerun.error is None
    assert rerun.archive_idempotent is True
    assert rerun.import_idempotent is True
    assert rerun.conflict is False
    assert rerun.accepted_count == 1
    assert rerun.rejected_count == 0
    assert rerun.needs_symbol_resolution_count == 0
    assert (tmp_path / "workbuddy" / "archive" / "candidates_idem_first.json").is_file()
    assert (tmp_path / "workbuddy" / "archive" / "candidates_idem_second.json").is_file()


def test_gateway_other_exceptions_remain_under_failed_bucket(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    (source / "candidates_bad.json").write_text("definitely not json", encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    outcomes = gateway.process_once(uow=_Uow())

    assert len(outcomes) == 1
    assert outcomes[0].error is not None
    assert outcomes[0].result is None
    assert outcomes[0].conflict is None
    assert outcomes[0].archive_idempotent is None
    assert outcomes[0].import_idempotent is None
    assert (tmp_path / "workbuddy" / "failed" / "candidates_bad.json").is_file()
    assert not (tmp_path / "workbuddy" / "conflict" / "candidates_bad.json").exists()
