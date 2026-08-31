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
    lineage: dict | None = None,
) -> dict:
    payload = {
        "schema_version": schema_version,
        "workflow_run_id": workflow_run_id,
        "trade_date": "2026-08-14",
        "strategy_id": "sector-v1",
        "status": status,
        "candidates": candidates
        if candidates is not None
        else [{"symbol": "600000", "reason": "sector strength"}],
    }
    if lineage is not None:
        payload["lineage"] = lineage
    return payload


def test_gateway_imports_flat_candidates_files_and_ignores_legacy_audit_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
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
    assert {path.name for path in (tmp_path / "candidate" / "archive").iterdir()} == {
        "candidates_sector.json",
        "candidates_v2.json",
    }
    assert not tuple((tmp_path / "candidate" / "processing").iterdir())
    assert (source / "result_sector.json").exists()
    assert (source / "report.json").exists()
    assert (tmp_path / "invest-infra" / "archive" / "runs" / "2026-08-14" / "flat-v1").is_dir()
    assert (tmp_path / "invest-infra" / "archive" / "runs" / "2026-08-14" / "flat-v2").is_dir()


def test_gateway_emits_structured_lifecycle_events(tmp_path: Path, caplog) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_event.json").write_text(
        json.dumps(_payload("event-run")), encoding="utf-8"
    )

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path, source)
    with caplog.at_level("INFO"):
        outcomes = gateway.process_once(uow=_Uow())

    assert outcomes[0].error is None
    events = [record for record in caplog.records if record.name.endswith("shared_directory")]
    assert [record.event for record in events] == ["scan_started", "package_finished"]
    assert events[0].mode == "normal"
    assert events[1].package == "candidates_event.json"
    assert events[1].status == "success"


def test_gateway_claims_invalid_flat_candidate_to_failed(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    input_path = source / "candidates_broken.json"
    input_path.write_text("not-json", encoding="utf-8")

    outcomes = SharedDirectoryWorkBuddyGateway(tmp_path).process_once(uow=_Uow())

    assert outcomes[0].package == input_path.name
    assert outcomes[0].result is None
    assert outcomes[0].error
    assert (tmp_path / "candidate" / "failed" / input_path.name).is_file()
    assert not input_path.exists()


def test_gateway_exposes_diagnostics_on_success(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
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
    # Legacy payloads without lineage must NOT add lineage keys anywhere.
    assert "lineage" not in outcome.result.run.metadata
    for observation in outcome.result.observations:
        for key in _LINEAGE_REFERENCE_KEYS:
            assert key not in observation.metadata, (
                f"legacy payload must not stamp {key!r} on observation metadata"
            )


def test_gateway_routes_archive_conflict_to_conflict_bucket(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
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

    assert (tmp_path / "candidate" / "archive" / "candidates_a.json").is_file()
    assert (tmp_path / "candidate" / "conflict" / "candidates_b.json").is_file()
    assert not (tmp_path / "candidate" / "failed" / "candidates_b.json").exists()
    assert not (tmp_path / "candidate" / "archive" / "candidates_b.json").exists()


def test_gateway_routes_ready_package_conflict_to_conflict_bucket(tmp_path: Path) -> None:
    ready_dir = tmp_path / "candidate" / "results"
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

    assert (tmp_path / "candidate" / "archive" / "ready-conflict-001").is_dir()
    assert (tmp_path / "candidate" / "conflict" / "ready-conflict-002").is_dir()
    assert not (tmp_path / "candidate" / "failed" / "ready-conflict-002").exists()


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
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    payload = _payload("idem-001")
    (source / "candidates_idem_first.json").write_text(json.dumps(payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    uow = _Uow()
    first = gateway.process_once(uow=uow)
    assert len(first) == 1
    assert first[0].error is None
    assert first[0].archive_idempotent is False
    assert first[0].import_idempotent is False

    # Re-stage the same payload under a different filename. archive_candidates
    # still sees the existing run_dir by workflow_run_id+trade_date and the
    # bridge must reuse the existing run/artifact. The new filename keeps the
    # lifecycle destination distinct so _finish must perform a real move.
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
    assert (tmp_path / "candidate" / "archive" / "candidates_idem_first.json").is_file()
    assert (tmp_path / "candidate" / "archive" / "candidates_idem_second.json").is_file()


def test_gateway_idempotent_finish_when_same_flat_file_is_resubmitted(
    tmp_path: Path,
) -> None:
    """Re-submitting byte-identical flat candidate file under the same name.

    archive_candidates and import_archived_candidate_run both report
    idempotent, so the lifecycle must finish cleanly: the existing archive
    destination stays untouched and the duplicate is discarded instead of
    raising ``FileExistsError`` or landing in ``failed/``.
    """
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    payload = _payload("idem-flat-001")
    file_name = "candidates_idem_flat.json"
    (source / file_name).write_text(json.dumps(payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    uow = _Uow()
    first = gateway.process_once(uow=uow)
    assert len(first) == 1
    assert first[0].error is None
    assert first[0].archive_idempotent is False
    assert first[0].import_idempotent is False

    archive_destination = tmp_path / "candidate" / "archive" / file_name
    assert archive_destination.is_file()
    first_bytes = archive_destination.read_bytes()

    # Re-stage the same filename with the same payload bytes — must finish
    # idempotently without raising or routing to failed/.
    (source / file_name).write_text(json.dumps(payload), encoding="utf-8")
    second = gateway.process_once(uow=uow)
    assert len(second) == 1
    rerun = second[0]
    assert rerun.error is None
    assert rerun.archive_idempotent is True
    assert rerun.import_idempotent is True
    assert rerun.conflict is False
    assert rerun.accepted_count == 1
    assert rerun.rejected_count == 0

    # Existing destination must remain untouched (no overwrite) and no
    # failed/ or conflict/ copy may appear.
    assert archive_destination.is_file()
    assert archive_destination.read_bytes() == first_bytes
    assert not (tmp_path / "candidate" / "failed" / file_name).exists()
    assert not (tmp_path / "candidate" / "conflict" / file_name).exists()
    assert not (tmp_path / "candidate" / "processing" / file_name).exists()


def test_gateway_different_content_collision_routes_claimed_to_failed(
    tmp_path: Path,
) -> None:
    """A destination that already exists with different bytes forces a failure.

    ``_finish`` must keep raising ``FileExistsError`` so the existing failure
    routing (``failed/``) preserves the claimed package instead of silently
    overwriting or silently discarding the new submission.
    """
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    file_name = "candidates_collision.json"

    # Pre-populate the archive destination with bytes that do NOT match the
    # payload that will be submitted. This simulates a stale archive slot.
    archive_destination = tmp_path / "candidate" / "archive" / file_name
    archive_destination.parent.mkdir(parents=True, exist_ok=True)
    stale_bytes = b'{"legacy": "different bytes"}'
    archive_destination.write_bytes(stale_bytes)

    payload = _payload("collision-001")
    (source / file_name).write_text(json.dumps(payload), encoding="utf-8")

    outcomes = SharedDirectoryWorkBuddyGateway(tmp_path).process_once(uow=_Uow())

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.error is not None
    assert outcome.result is None
    assert outcome.conflict is None
    assert outcome.archive_idempotent is None
    assert outcome.import_idempotent is None

    # The pre-existing archive target must remain byte-for-byte intact and the
    # claimed duplicate must be routed to failed/ for operator inspection.
    assert archive_destination.is_file()
    assert archive_destination.read_bytes() == stale_bytes
    failed_destination = tmp_path / "candidate" / "failed" / file_name
    assert failed_destination.is_file()
    assert failed_destination.read_bytes() == json.dumps(payload).encode("utf-8")
    assert not (tmp_path / "candidate" / "conflict" / file_name).exists()
    assert not (tmp_path / "candidate" / "processing" / file_name).exists()


def test_gateway_other_exceptions_remain_under_failed_bucket(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_bad.json").write_text("definitely not json", encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    outcomes = gateway.process_once(uow=_Uow())

    assert len(outcomes) == 1
    assert outcomes[0].error is not None
    assert outcomes[0].result is None
    assert outcomes[0].conflict is None
    assert outcomes[0].archive_idempotent is None
    assert outcomes[0].import_idempotent is None
    assert (tmp_path / "candidate" / "failed" / "candidates_bad.json").is_file()
    assert not (tmp_path / "candidate" / "conflict" / "candidates_bad.json").exists()


def test_gateway_paths_are_under_candidate_phase_no_obsolete_workbuddy_segment(
    tmp_path: Path,
) -> None:
    """Focused assertion that the candidate intake stays under ``candidate/``.

    The formal WorkBuddy bridge root already is the workbuddy root, so no
    nested ``workbuddy/`` segment may appear in the lifecycle paths. This
    guards against silently re-introducing the obsolete ``<root>/workbuddy/*``
    layout or a legacy single-level source directory.
    """
    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    lifecycle_paths = (
        gateway.source,
        gateway.inbox,
        gateway.processing,
        gateway.archive,
        gateway.failed,
        gateway.conflict,
    )
    for path in lifecycle_paths:
        assert path.parent.name == "candidate", (
            f"lifecycle path {path} must live under <bridge_root>/candidate/"
        )
        assert "workbuddy" not in path.parts, (
            f"lifecycle path {path} must not nest a workbuddy segment"
        )

    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_phase.json").write_text(
        json.dumps(_payload("phase-001")), encoding="utf-8"
    )

    SharedDirectoryWorkBuddyGateway(tmp_path).process_once(uow=_Uow())

    assert not (tmp_path / "workbuddy").exists(), (
        "obsolete <bridge_root>/workbuddy/ candidate-intake directory must not be created"
    )
    assert (tmp_path / "candidate" / "archive" / "candidates_phase.json").is_file()


# ---------------------------------------------------------------------------
# Lineage persistence — Bridge carries the parser lineage into Integration
# metadata when the payload carries the two-stage ``candidate-lineage/1.0``
# object, and otherwise leaves the run/observation metadata untouched.
# ---------------------------------------------------------------------------


_LINEAGE_REFERENCE_KEYS = (
    "terminal_stage_result_id",
    "terminal_stage_result_sha256",
    "upstream_stage_result_id",
    "upstream_stage_result_sha256",
)


_LINEAGE = {
    "schema_version": "candidate-lineage/1.0",
    "stages": [
        {
            "stage_key": "sector_selection",
            "stage_result_id": "sector-result-1",
            "stage_result_sha256": "a" * 64,
            "strategy_key": "sector-strength-v1",
            "strategy_version": "1.0.0",
            "strategy_artifact_hash": "b" * 64,
            "as_of": "2026-08-14",
            "constituent_snapshot_sha256": "c" * 64,
        },
        {
            "stage_key": "stock_screening",
            "stage_result_id": "stock-result-1",
            "stage_result_sha256": "d" * 64,
            "strategy_key": "stock-screen-v1",
            "strategy_version": "1.0.0",
            "strategy_artifact_hash": "e" * 64,
            "as_of": "2026-08-14",
            "upstream_stage_result_id": "sector-result-1",
            "upstream_stage_result_sha256": "a" * 64,
        },
    ],
}


def test_gateway_persists_lineage_and_keeps_it_idempotent(tmp_path: Path) -> None:
    """Lineage payload → normalized run metadata + four observation refs;
    byte-identical re-import preserves the lineage metadata unchanged."""
    stock_stage = _LINEAGE["stages"][1]
    payload = _payload(
        "lineage-001",
        candidates=[
            {
                "symbol": "600000",
                "reason": "板块强度共振",
                "terminal_stage_result_id": stock_stage["stage_result_id"],
                "terminal_stage_result_sha256": stock_stage["stage_result_sha256"],
            }
        ],
        lineage=_LINEAGE,
    )
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_lineage.json").write_text(json.dumps(payload), encoding="utf-8")

    gateway = SharedDirectoryWorkBuddyGateway(tmp_path)
    uow = _Uow()
    first = gateway.process_once(uow=uow)
    outcome = first[0]
    assert outcome.error is None
    run_metadata = dict(outcome.result.run.metadata)
    assert "lineage" in run_metadata
    lineage = run_metadata["lineage"]
    assert lineage["schema_version"] == "candidate-lineage/1.0"
    sector, stock = lineage["stages"]
    assert [s["stage_key"] for s in lineage["stages"]] == ["sector_selection", "stock_screening"]
    assert "upstream_stage_result_id" not in sector
    assert "constituent_snapshot_sha256" not in stock

    expected_refs = {
        "terminal_stage_result_id": stock["stage_result_id"],
        "terminal_stage_result_sha256": stock["stage_result_sha256"],
        "upstream_stage_result_id": stock["upstream_stage_result_id"],
        "upstream_stage_result_sha256": stock["upstream_stage_result_sha256"],
    }
    first_obs_by_id = {obs.observation_id: obs for obs in outcome.result.observations}
    for observation in first_obs_by_id.values():
        for key, value in expected_refs.items():
            assert observation.metadata[key] == value
        assert "lineage" not in observation.metadata

    # Byte-identical re-import must return the persisted metadata unchanged.
    (source / "candidates_lineage.json").write_text(json.dumps(payload), encoding="utf-8")
    rerun = gateway.process_once(uow=uow)[0]
    assert rerun.error is None
    assert rerun.import_idempotent is True
    assert rerun.archive_idempotent is True
    assert dict(rerun.result.run.metadata) == run_metadata
    assert len(rerun.result.observations) == len(first_obs_by_id)
    for obs in rerun.result.observations:
        assert obs.metadata == first_obs_by_id[obs.observation_id].metadata
