"""Combined ``task``+``result`` lifecycle tests for the strategy stage."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from invest_pipeline.integrations.workbuddy_strategy_archive import (
    MANIFEST_SCHEMA_VERSION,
    StrategyCombinedArchive,
    StrategyPackageOutcome,
)


def _make_worker(tmp_path: Path) -> StrategyCombinedArchive:
    return StrategyCombinedArchive(tmp_path)


def _write_task(
    path: Path,
    *,
    task_id: str = "task-001",
    payload: dict[str, object] | None = None,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    payload_dict = payload if payload is not None else {
        "task_id": task_id,
        "type": "phase_a",
    }
    (path / "task.json").write_text(json.dumps(payload_dict))
    return path


def _write_result(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.json").write_text("{}")
    return path


def _seed_pair(
    tmp_path: Path,
    task_id: str = "task-001",
    *,
    task_payload: dict[str, object] | None = None,
    skip_inbox: bool = False,
    skip_results: bool = False,
) -> StrategyCombinedArchive:
    worker = _make_worker(tmp_path)
    if not skip_inbox:
        _write_task(
            worker.inbox / f"{task_id}.ready",
            task_id=task_id,
            payload=task_payload,
        )
    if not skip_results:
        _write_result(worker.results / f"{task_id}.ready")
    return worker


def test_success_archives_combined_package(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001")
    seen: list[Path] = []

    def handler(processing: Path) -> None:
        seen.append(processing)

    outcomes = worker.process_once(handler)
    assert outcomes[0].status == "success"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is None
    assert isinstance(outcomes[0], StrategyPackageOutcome)
    assert seen == [worker.processing / "task-001"]
    assert (worker.archive / "task-001" / "task" / "task.json").is_file()
    assert (worker.archive / "task-001" / "result" / "result.json").is_file()
    assert not (worker.inbox / "task-001.ready").exists()
    assert not (worker.results / "task-001.ready").exists()
    assert not (worker.processing / "task-001").exists()


def test_missing_inbox_returns_missing_task_and_preserves_result(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001", skip_inbox=True)
    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "missing_task"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is None
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_identity_mismatch_moves_processing_to_failed(tmp_path: Path) -> None:
    worker = _seed_pair(
        tmp_path,
        "task-001",
        task_payload={"task_id": "wrong-id", "type": "phase_a"},
    )
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "identity_mismatch"
    assert "wrong-id" in (outcomes[0].error or "")
    assert (worker.failed / "task-001" / "task" / "task.json").is_file()
    assert (worker.failed / "task-001" / "result" / "result.json").is_file()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.archive / "task-001").exists()


def test_inbox_symlink_is_rejected_as_unsafe_input(tmp_path: Path) -> None:
    worker = _make_worker(tmp_path)
    _write_task(worker.inbox / "inbox-target", task_id="task-001")
    _write_result(worker.results / "task-001.ready")
    (worker.inbox / "task-001.ready").symlink_to(
        worker.inbox / "inbox-target", target_is_directory=True
    )
    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "unsafe_input"
    assert outcomes[0].task_id == "task-001"
    assert "inbox" in (outcomes[0].error or "").lower()
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.archive / "task-001").exists()


def test_result_symlink_is_filtered_from_discovery(tmp_path: Path) -> None:
    worker = _make_worker(tmp_path)
    _write_result(worker.results / "real.ready")
    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "result.json").write_text("{}")
    (worker.results / "link.ready").symlink_to(
        outside, target_is_directory=True
    )
    discovered = worker.discover_ready()
    assert [path.name for path in discovered] == ["real.ready"]


def test_claim_conflict_preserves_existing_processing_and_sources(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001")
    processing = worker.processing / "task-001"
    processing.mkdir(parents=True)
    (processing / "keep").write_text("preserve")
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "claim_conflict"
    assert (processing / "keep").is_file()
    assert (worker.results / "task-001.ready").is_dir()
    assert (worker.inbox / "task-001.ready").is_dir()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_handler_exception_moves_package_to_failed(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001")

    def boom(_processing: Path) -> None:
        raise RuntimeError("validator exploded")

    outcomes = worker.process_once(boom)
    assert outcomes[0].status == "failed"
    assert outcomes[0].error == "validator exploded"
    assert (worker.failed / "task-001" / "task" / "task.json").is_file()
    assert (worker.failed / "task-001" / "result" / "result.json").is_file()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.processing / "task-001").exists()


def test_handler_failure_with_existing_failed_does_not_overwrite(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001")
    (worker.failed / "task-001").mkdir(parents=True)
    (worker.failed / "task-001" / "keep").write_text("preserve")

    def boom(_processing: Path) -> None:
        raise RuntimeError("validator exploded")

    outcomes = worker.process_once(boom)
    assert outcomes[0].status == "failed"
    assert "finish failed" in (outcomes[0].error or "")
    assert (worker.failed / "task-001" / "keep").is_file()
    assert (worker.processing / "task-001" / "task" / "task.json").is_file()


def test_finish_conflict_preserves_processing_when_archive_exists(tmp_path: Path) -> None:
    worker = _seed_pair(tmp_path, "task-001")
    (worker.archive / "task-001").mkdir(parents=True)
    (worker.archive / "task-001" / "keep").write_text("do-not-overwrite")
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "archive_conflict"
    assert (worker.archive / "task-001" / "keep").is_file()
    assert (worker.inbox / "task-001.ready").is_dir()
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()


def test_process_once_returns_empty_tuple_when_no_results(tmp_path: Path) -> None:
    worker = _make_worker(tmp_path)
    assert worker.process_once(lambda _p: None) == ()


# ---------------------------------------------------------------------------
# Slice B: validator routing + manifest/evidence
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[4]
_SCRIPT_A = _REPO / "scripts" / "validate_strategy_delivery.py"
_SCRIPT_B = _REPO / "scripts" / "validate_strategy_proposal.py"

_PHASE_A_TASK_ID = "strategy-capability-archive-001"
_PHASE_A_SOURCE_DOC_ID = "source-doc-archive-001"
_PHASE_A_DATA_MATRIX = "data-matrix-archive-001"
_PHASE_A_AS_OF = "2026-08-15T10:00:00+08:00"
_PHASE_A_ASSESSMENT_ID = "assessment-archive-001"
_PHASE_A_SOURCE_SHA = "0" * 64

_PHASE_B_TASK_ID = "strategy-engineering-archive-001"
_PHASE_B_SOURCE_DOC_ID = "source-doc-archive-001"
_PHASE_B_ASSESSMENT_ID = "assessment-archive-001"
_PHASE_B_AS_OF = "2026-08-15T12:45:00+08:00"
_PHASE_B_PROPOSAL_ID = "strategy-proposal-archive-001"
_PHASE_B_VALIDATION_ID = "strategy-validation-archive-001"
_PHASE_B_SOURCE_SHA = "0" * 64
_PHASE_B_ASSESSMENT_SHA = "1" * 64


def _make_validated_worker(
    tmp_path: Path,
    *,
    phase_a_validator: str | Path = _SCRIPT_A,
    phase_b_validator: str | Path = _SCRIPT_B,
    runner=None,
    timeout: float = 30.0,
    repository_root: str | Path = _REPO,
) -> StrategyCombinedArchive:
    return StrategyCombinedArchive(
        tmp_path,
        repository_root=repository_root,
        phase_a_validator=phase_a_validator,
        phase_b_validator=phase_b_validator,
        runner=runner,
        timeout=timeout,
    )


def _sha256_lower(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_phase_a_payload(
    *,
    task_id: str = _PHASE_A_TASK_ID,
    schema_version: str = "strategy-capability-assessment-task/1.0",
    task_type: str = "capability_assessment",
    status_value: str = "ready",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "stage": "strategy",
        "task_type": task_type,
        "source_document": {
            "source_document_id": _PHASE_A_SOURCE_DOC_ID,
            "revision": 1,
            "content_sha256": _PHASE_A_SOURCE_SHA,
        },
        "data_matrix_version": _PHASE_A_DATA_MATRIX,
        "as_of": _PHASE_A_AS_OF,
        "required_outputs": [
            "capability-assessment.json",
            "capability-assessment.md",
            "capability-probes.json",
        ],
    }


def _write_phase_a_result(
    result_dir: Path,
    *,
    status_value: str = "ready",
    task_id: str = _PHASE_A_TASK_ID,
) -> Path:
    result_dir.mkdir(parents=True, exist_ok=True)
    md_path = result_dir / "capability-assessment.md"
    md_path.write_text("# Capability Assessment\n", encoding="utf-8")
    probes_path = result_dir / "capability-probes.json"
    probes_payload = {
        "schema_version": "strategy-capability-probes/1.0",
        "task_id": task_id,
        "assessed_at": _PHASE_A_AS_OF,
        "probes": [],
    }
    _write_json(probes_path, probes_payload)
    assessment_path = result_dir / "capability-assessment.json"
    assessment_payload = {
        "schema_version": "strategy-capability-assessment/1.0",
        "assessment_id": _PHASE_A_ASSESSMENT_ID,
        "task_id": task_id,
        "source_document": {
            "source_document_id": _PHASE_A_SOURCE_DOC_ID,
            "revision": 1,
            "content_sha256": _PHASE_A_SOURCE_SHA,
        },
        "data_matrix_version": _PHASE_A_DATA_MATRIX,
        "as_of": _PHASE_A_AS_OF,
        "status": status_value,
        "capabilities": [
            {
                "requirement_id": "daily-bars",
                "description": "Adjusted daily bars for the required market range",
                "required": True,
                "status": "available",
                "primary_source": "tdx-connector",
                "fallback_sources": ["westock-mcp"],
                "limitations": [],
            }
        ],
        "findings": {"warnings": [], "reviews": [], "blockers": []},
        "artifacts": [
            {"name": "capability-assessment.md", "sha256": _sha256_lower(md_path)},
            {"name": "capability-probes.json", "sha256": _sha256_lower(probes_path)},
        ],
    }
    _write_json(assessment_path, assessment_payload)
    return result_dir


def _build_phase_b_payload(
    *,
    task_id: str = _PHASE_B_TASK_ID,
    schema_version: str = "strategy-engineering-task/1.0",
    task_type: str = "strategy_engineering",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "stage": "strategy",
        "task_type": task_type,
        "source_document": {
            "source_document_id": _PHASE_B_SOURCE_DOC_ID,
            "revision": 1,
            "content_sha256": _PHASE_B_SOURCE_SHA,
        },
        "capability_assessment": {
            "assessment_id": _PHASE_B_ASSESSMENT_ID,
            "task_id": _PHASE_A_TASK_ID,
            "artifact_sha256": _PHASE_B_ASSESSMENT_SHA,
        },
        "as_of": _PHASE_B_AS_OF,
        "required_outputs": [
            "strategy.json",
            "strategy.md",
            "validation.json",
        ],
    }


def _write_phase_b_result(
    result_dir: Path,
    *,
    task_id: str = _PHASE_B_TASK_ID,
) -> Path:
    result_dir.mkdir(parents=True, exist_ok=True)
    md_path = result_dir / "strategy.md"
    md_path.write_text("# Strategy Proposal\n", encoding="utf-8")
    validation_path = result_dir / "validation.json"
    validation_payload = {
        "schema_version": "strategy-proposal-validation/1.0",
        "validation_id": _PHASE_B_VALIDATION_ID,
        "task_id": task_id,
        "proposal_id": _PHASE_B_PROPOSAL_ID,
        "proposal_revision": 1,
        "validated_at": _PHASE_B_AS_OF,
        "status": "passed",
        "checks": [],
        "warnings": [],
        "reviews": [],
        "errors": [],
    }
    _write_json(validation_path, validation_payload)
    proposal_payload = {
        "schema_version": "strategy-proposal/1.0",
        "proposal_id": _PHASE_B_PROPOSAL_ID,
        "revision": 1,
        "task_id": task_id,
        "source_document": {
            "source_document_id": _PHASE_B_SOURCE_DOC_ID,
            "revision": 1,
            "content_sha256": _PHASE_B_SOURCE_SHA,
        },
        "capability_assessment": {
            "assessment_id": _PHASE_B_ASSESSMENT_ID,
            "task_id": _PHASE_A_TASK_ID,
            "artifact_sha256": _PHASE_B_ASSESSMENT_SHA,
        },
        "generated_at": _PHASE_B_AS_OF,
        "status": "ready_for_review",
        "name": "Archive test proposal",
        "purpose": "Validate the strategy archive wiring",
        "definition": {"stage_role": "example"},
        "artifacts": [
            {"name": "strategy.md", "sha256": _sha256_lower(md_path)},
            {"name": "validation.json", "sha256": _sha256_lower(validation_path)},
        ],
    }
    _write_json(result_dir / "strategy.json", proposal_payload)
    return result_dir


def _seed_phase_a(
    tmp_path: Path,
    *,
    task_id: str = _PHASE_A_TASK_ID,
    task_payload: dict[str, object] | None = None,
    status_value: str = "ready",
    runner=None,
    phase_a_validator: str | Path = _SCRIPT_A,
) -> StrategyCombinedArchive:
    worker = _make_validated_worker(tmp_path, runner=runner, phase_a_validator=phase_a_validator)
    payload = task_payload if task_payload is not None else _build_phase_a_payload(
        task_id=task_id, status_value=status_value
    )
    _write_task(worker.inbox / f"{task_id}.ready", task_id=task_id, payload=payload)
    result_dir = worker.results / f"{task_id}.ready"
    _write_phase_a_result(result_dir, status_value=status_value, task_id=task_id)
    return worker


def _seed_phase_b(
    tmp_path: Path,
    *,
    task_id: str = _PHASE_B_TASK_ID,
    task_payload: dict[str, object] | None = None,
    runner=None,
    phase_b_validator: str | Path = _SCRIPT_B,
) -> StrategyCombinedArchive:
    worker = _make_validated_worker(tmp_path, runner=runner, phase_b_validator=phase_b_validator)
    payload = task_payload if task_payload is not None else _build_phase_b_payload(task_id=task_id)
    _write_task(worker.inbox / f"{task_id}.ready", task_id=task_id, payload=payload)
    _write_phase_b_result(worker.results / f"{task_id}.ready", task_id=task_id)
    return worker


def test_phase_a_success_archives_with_manifest_and_record(tmp_path: Path) -> None:
    if not _SCRIPT_A.exists():
        pytest.skip(f"Phase A validator missing: {_SCRIPT_A}")
    worker = _seed_phase_a(tmp_path)
    outcomes = worker.process_once()
    assert len(outcomes) == 1
    assert outcomes[0].status == "validated"
    assert outcomes[0].task_id == _PHASE_A_TASK_ID
    assert outcomes[0].error is None

    package = worker.archive / _PHASE_A_TASK_ID
    assert package.is_dir()
    assert not (worker.processing / _PHASE_A_TASK_ID).exists()
    assert not (worker.failed / _PHASE_A_TASK_ID).exists()

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "strategy-archive-manifest/1.0"
    assert manifest["task_id"] == _PHASE_A_TASK_ID
    assert manifest["task_type"] == "capability_assessment"
    assert manifest["validator_identity"] == "scripts/validate_strategy_delivery.py"
    assert isinstance(manifest["processed_at"], str) and manifest["processed_at"]
    paths = sorted(entry["path"] for entry in manifest["entries"])
    assert paths == sorted(
        [
            "result/capability-assessment.json",
            "result/capability-assessment.md",
            "result/capability-probes.json",
            "task/task.json",
        ]
    )
    for entry in manifest["entries"]:
        assert isinstance(entry["size"], int) and entry["size"] >= 0
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None

    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["schema_version"] == "strategy-archive-record/1.0"
    assert record["authority"] == "file-level validated archive"
    assert record["task_id"] == _PHASE_A_TASK_ID
    assert record["task_type"] == "capability_assessment"
    assert record["status"] == "validated"
    assert record["validator_exit_code"] == 0
    assert record["validator_report"] == "validation-report.json"
    assert record["validator_stdout"] is None or record["validator_stdout"].endswith(".txt")
    assert record["validator_stderr"] is None or record["validator_stderr"].endswith(".txt")
    assert record["processing_outcome"] == {"task_id": _PHASE_A_TASK_ID, "kind": "archive"}

    serialized = json.dumps(record)
    for forbidden in ("ingestion", "approval", "activation", "CIA", "RAA"):
        assert forbidden not in serialized

    assert (package / "validation-report.json").is_file()
    assert (package / "result" / "validation-report.json").exists() is False


def test_phase_b_success_archives_with_manifest_and_record(tmp_path: Path) -> None:
    if not _SCRIPT_B.exists():
        pytest.skip(f"Phase B validator missing: {_SCRIPT_B}")
    worker = _seed_phase_b(tmp_path)
    outcomes = worker.process_once()
    assert len(outcomes) == 1
    assert outcomes[0].status == "validated"
    assert outcomes[0].task_id == _PHASE_B_TASK_ID

    package = worker.archive / _PHASE_B_TASK_ID
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_type"] == "strategy_engineering"
    assert manifest["validator_identity"] == "scripts/validate_strategy_proposal.py"
    paths = sorted(entry["path"] for entry in manifest["entries"])
    assert paths == sorted(
        [
            "result/strategy.json",
            "result/strategy.md",
            "result/validation.json",
            "task/task.json",
        ]
    )

    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["status"] == "validated"
    assert record["validator_report"] == "proposal-preflight-report.json"
    assert record["processing_outcome"] == {"task_id": _PHASE_B_TASK_ID, "kind": "archive"}
    assert (package / "proposal-preflight-report.json").is_file()
    assert not (package / "result" / "proposal-preflight-report.json").exists()


def _stub_runner(returncode: int, stdout: str, stderr: str = ""):
    def _runner(args: list[str], cwd: Path, timeout: float):
        from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult
        return ValidatorResult(
            returncode=returncode, stdout=stdout, stderr=stderr,
            timed_out=False, missing_script=False, error=None,
        )
    return _runner


def test_validator_rejection_moves_to_failed_with_record(tmp_path: Path) -> None:
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    fake_stdout = json.dumps({"ready": False, "errors": [{"code": "x"}]})

    def _runner(args: list[str], cwd: Path, timeout: float):
        result_dir = Path(args[args.index("--result-dir") + 1])
        (result_dir / "validation-report.json").write_text(fake_stdout, encoding="utf-8")
        return ValidatorResult(
            returncode=1, stdout=fake_stdout, stderr="",
            timed_out=False, missing_script=False, error=None,
        )

    worker = _seed_phase_a(tmp_path, status_value="blocked", runner=_runner)
    outcomes = worker.process_once()
    assert outcomes[0].status == "validation_failed"
    package = worker.failed / _PHASE_A_TASK_ID
    assert package.is_dir()
    assert not (worker.archive / _PHASE_A_TASK_ID).exists()
    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["status"] == "validation_failed"
    assert record["validator_exit_code"] == 1
    assert record["validator_report"] == "validation-report.json"
    assert record["errors"] == [{"code": "x"}]
    assert record["validator_stdout"] == "validator.stdout.txt"
    stdout_text = (package / "validator.stdout.txt").read_text(encoding="utf-8")
    assert fake_stdout in stdout_text


def test_validator_error_redacts_both_roots_from_outcome_record_and_evidence(
    tmp_path: Path,
) -> None:
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    bridge_root = tmp_path
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    unsafe_text = (
        f"bridge={bridge_root}/task/result.json; "
        f"repository={repository_root}/scripts/result.py"
    )

    def _runner(args: list[str], cwd: Path, timeout: float):
        return ValidatorResult(
            returncode=-1,
            stdout=unsafe_text,
            stderr=unsafe_text,
            timed_out=False,
            missing_script=False,
            error=unsafe_text,
        )

    worker = _make_validated_worker(
        tmp_path,
        repository_root=repository_root,
        runner=_runner,
    )
    _write_task(
        worker.inbox / f"{_PHASE_A_TASK_ID}.ready",
        task_id=_PHASE_A_TASK_ID,
        payload=_build_phase_a_payload(),
    )
    _write_phase_a_result(
        worker.results / f"{_PHASE_A_TASK_ID}.ready",
        task_id=_PHASE_A_TASK_ID,
    )
    outcomes = worker.process_once()

    assert len(outcomes) == 1
    assert outcomes[0].status == "validator_error"
    assert outcomes[0].error is not None
    assert str(bridge_root) not in outcomes[0].error
    assert str(repository_root) not in outcomes[0].error
    assert "<bridge-root>/task/result.json" in outcomes[0].error
    assert "<repository-root>/scripts/result.py" in outcomes[0].error

    package = worker.failed / _PHASE_A_TASK_ID
    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    serialized = json.dumps(record)
    assert str(bridge_root) not in serialized
    assert str(repository_root) not in serialized
    assert "<bridge-root>/task/result.json" in serialized
    assert "<repository-root>/scripts/result.py" in serialized

    evidence = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in ("validator.stdout.txt", "validator.stderr.txt")
    )
    assert str(bridge_root) not in evidence
    assert str(repository_root) not in evidence
    assert "<bridge-root>/task/result.json" in evidence
    assert "<repository-root>/scripts/result.py" in evidence


def test_report_findings_redact_both_roots_from_record_and_evidence(
    tmp_path: Path,
) -> None:
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    bridge_root = tmp_path
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    unsafe_text = (
        f"bridge={bridge_root}/result/result.json; "
        f"repository={repository_root}/scripts/result.py"
    )
    report = {
        "ready": False,
        "errors": [
            {
                "code": f"unsafe_{bridge_root.name}",
                "message": unsafe_text,
                "context": {
                    f"{repository_root}/field": unsafe_text,
                    "paths": [unsafe_text],
                },
            }
        ],
        "warnings": [{"code": "root_warning", "message": unsafe_text}],
        "reviews": [
            {
                "code": "root_review",
                "message": unsafe_text,
                "paths": [str(repository_root) + "/docs/review.md"],
            }
        ],
    }

    def _runner(args: list[str], cwd: Path, timeout: float):
        result_dir = Path(args[args.index("--result-dir") + 1])
        (result_dir / "validation-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return ValidatorResult(
            returncode=1,
            stdout=unsafe_text,
            stderr=unsafe_text,
            timed_out=False,
            missing_script=False,
            error=None,
        )

    worker = _make_validated_worker(
        tmp_path,
        repository_root=repository_root,
        runner=_runner,
    )
    _write_task(
        worker.inbox / f"{_PHASE_A_TASK_ID}.ready",
        task_id=_PHASE_A_TASK_ID,
        payload=_build_phase_a_payload(),
    )
    _write_phase_a_result(
        worker.results / f"{_PHASE_A_TASK_ID}.ready",
        task_id=_PHASE_A_TASK_ID,
    )
    outcomes = worker.process_once()

    assert len(outcomes) == 1
    assert outcomes[0].status == "validation_failed"
    package = worker.failed / _PHASE_A_TASK_ID
    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    findings = record["errors"] + record["warnings"] + record["reviews"]
    serialized = json.dumps(findings)
    assert str(bridge_root) not in serialized
    assert str(repository_root) not in serialized
    assert "<bridge-root>/result/result.json" in serialized
    assert "<repository-root>/scripts/result.py" in serialized
    assert "<repository-root>/docs/review.md" in serialized
    assert "<repository-root>/field" in serialized

    evidence = "\n".join(
        (package / name).read_text(encoding="utf-8")
        for name in ("validator.stdout.txt", "validator.stderr.txt")
    )
    assert str(bridge_root) not in evidence
    assert str(repository_root) not in evidence
    assert "<bridge-root>/result/result.json" in evidence
    assert "<repository-root>/scripts/result.py" in evidence


def test_malformed_report_moves_to_failed(tmp_path: Path) -> None:
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    def _runner(args: list[str], cwd: Path, timeout: float):
        result_dir = Path(args[args.index("--result-dir") + 1])
        (result_dir / "validation-report.json").write_text("{not valid json", encoding="utf-8")
        return ValidatorResult(
            returncode=1, stdout="", stderr="", timed_out=False, missing_script=False, error=None,
        )

    worker = _seed_phase_a(tmp_path, runner=_runner)
    outcomes = worker.process_once()
    assert outcomes[0].status == "malformed_report"
    package = worker.failed / _PHASE_A_TASK_ID
    assert package.is_dir()
    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["status"] == "malformed_report"
    assert record["validator_report"] == "validation-report.json"
    assert (package / "validation-report.json").is_file()
    assert not (package / "result" / "validation-report.json").exists()


def test_missing_report_moves_to_failed(tmp_path: Path) -> None:
    worker = _seed_phase_a(tmp_path, runner=_stub_runner(0, json.dumps({"ready": True}), ""))
    outcomes = worker.process_once()
    assert outcomes[0].status == "missing_report"
    package = worker.failed / _PHASE_A_TASK_ID
    assert package.is_dir()
    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["status"] == "missing_report"
    assert record["validator_report"] is None
    assert record["validator_exit_code"] == 0


def test_unknown_task_type_fails_closed(tmp_path: Path) -> None:
    payload = _build_phase_a_payload(
        task_id=_PHASE_A_TASK_ID,
        schema_version="strategy-capability-assessment-task/1.0",
        task_type="not_supported",
    )
    worker = _seed_phase_a(tmp_path, task_payload=payload)
    outcomes = worker.process_once()
    assert outcomes[0].status == "unknown_task_type"
    assert outcomes[0].task_id == _PHASE_A_TASK_ID
    package = worker.failed / _PHASE_A_TASK_ID
    assert package.is_dir()
    record = json.loads((package / "validation-record.json").read_text(encoding="utf-8"))
    assert record["status"] == "unknown_task_type"
    assert any(err.get("code") == "unknown_task_type" for err in record["errors"])


def test_unknown_task_type_when_only_schema_mismatches(tmp_path: Path) -> None:
    payload = _build_phase_a_payload(
        schema_version="strategy-other-task/1.0", task_type="capability_assessment"
    )
    worker = _seed_phase_a(tmp_path, task_payload=payload)
    outcomes = worker.process_once()
    assert outcomes[0].status == "unknown_task_type"


def test_manifest_rehash_equality_for_phase_a_success(tmp_path: Path) -> None:
    if not _SCRIPT_A.exists():
        pytest.skip(f"Phase A validator missing: {_SCRIPT_A}")
    worker = _seed_phase_a(tmp_path)
    outcomes = worker.process_once()
    assert outcomes[0].status == "validated"
    package = worker.archive / _PHASE_A_TASK_ID
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        file_path = package / entry["path"]
        assert file_path.is_file(), f"missing manifest entry: {entry['path']}"
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_hash == entry["sha256"], entry["path"]
        assert file_path.stat().st_size == entry["size"]


def test_evidence_before_finish_conflict(tmp_path: Path) -> None:
    if not _SCRIPT_A.exists():
        pytest.skip(f"Phase A validator missing: {_SCRIPT_A}")
    worker = _seed_phase_a(tmp_path)
    (worker.archive / _PHASE_A_TASK_ID).mkdir(parents=True)
    (worker.archive / _PHASE_A_TASK_ID / "keep").write_text("preserve")
    outcomes = worker.process_once()
    assert outcomes[0].status == "archive_conflict"
    assert not (worker.processing / _PHASE_A_TASK_ID).exists()
    assert not (worker.failed / _PHASE_A_TASK_ID).exists()
    assert (worker.archive / _PHASE_A_TASK_ID / "keep").is_file()
    assert (worker.inbox / f"{_PHASE_A_TASK_ID}.ready").is_dir()
    assert (worker.results / f"{_PHASE_A_TASK_ID}.ready").is_dir()


# ---------------------------------------------------------------------------
# Slice C1: default repository_root + report relocation before parsing
# ---------------------------------------------------------------------------

_PHASE_A_VALIDATOR_REL = "scripts/validate_strategy_delivery.py"
_PHASE_B_VALIDATOR_REL = "scripts/validate_strategy_proposal.py"


def test_default_repository_root_resolves_from_module_layout(tmp_path: Path) -> None:
    """When repository_root is omitted, it must default to the module's
    repository layout, never to bridge_root. Validator identity must stay safe
    and relative inside that root."""
    worker = StrategyCombinedArchive(tmp_path)
    module_repo_root = Path(__file__).resolve().parents[4]
    assert worker.repository_root == module_repo_root
    assert worker.repository_root != worker.bridge_root

    expected_a = (module_repo_root / _PHASE_A_VALIDATOR_REL).resolve()
    expected_b = (module_repo_root / _PHASE_B_VALIDATOR_REL).resolve()
    assert worker.phase_a_validator == expected_a
    assert worker.phase_b_validator == expected_b
    assert (
        worker._relative_validator_id(worker.phase_a_validator)
        == _PHASE_A_VALIDATOR_REL
    )
    assert (
        worker._relative_validator_id(worker.phase_b_validator)
        == _PHASE_B_VALIDATOR_REL
    )


def test_explicit_repository_root_override_is_preserved(tmp_path: Path) -> None:
    """An explicit repository_root override must be preserved, and the default
    validator scripts resolve under it."""
    custom = tmp_path / "custom-root"
    custom.mkdir()
    worker = StrategyCombinedArchive(tmp_path, repository_root=custom)
    assert worker.repository_root == custom.resolve()
    assert worker.phase_a_validator == (
        custom / _PHASE_A_VALIDATOR_REL
    ).resolve()
    assert worker.phase_b_validator == (
        custom / _PHASE_B_VALIDATOR_REL
    ).resolve()
    assert (
        worker._relative_validator_id(worker.phase_a_validator)
        == _PHASE_A_VALIDATOR_REL
    )


def test_validator_identity_falls_back_to_basename_outside_repo_root(
    tmp_path: Path,
) -> None:
    """When the validator lives outside repository_root, the identity falls
    back to the basename so no absolute paths leak into the archive."""
    custom = tmp_path / "custom-root"
    custom.mkdir()
    outside = tmp_path / "outside-script.py"
    outside.write_text("#!/usr/bin/env python\n")
    worker = StrategyCombinedArchive(
        tmp_path,
        repository_root=custom,
        phase_a_validator=outside,
    )
    assert worker.repository_root == custom.resolve()
    assert worker.phase_a_validator == outside.resolve()
    assert (
        worker._relative_validator_id(worker.phase_a_validator)
        == "outside-script.py"
    )


def test_report_relocated_before_parsing_for_valid_report(tmp_path: Path) -> None:
    """For a valid report, the file moves from result/ to processing/ before
    any reading/parsing happens. The record references the relocated report
    and the file is no longer in result/."""
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    def _runner(args: list[str], cwd: Path, timeout: float):
        result_dir = Path(args[args.index("--result-dir") + 1])
        (result_dir / "validation-report.json").write_text(
            '{"ready": true}', encoding="utf-8"
        )
        return ValidatorResult(
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            missing_script=False,
            error=None,
        )

    worker = _seed_phase_a(tmp_path, runner=_runner)
    outcomes = worker.process_once()
    assert outcomes[0].status == "validated"

    archive = worker.archive / _PHASE_A_TASK_ID
    assert (archive / "validation-report.json").is_file()
    assert not (archive / "result" / "validation-report.json").exists()

    record = json.loads(
        (archive / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["validator_report"] == "validation-report.json"


def test_report_relocated_before_parsing_for_malformed_report(
    tmp_path: Path,
) -> None:
    """For a malformed report, the file is still relocated first and the
    record references the relocated report."""
    from invest_pipeline.integrations.workbuddy_strategy_archive import ValidatorResult

    def _runner(args: list[str], cwd: Path, timeout: float):
        result_dir = Path(args[args.index("--result-dir") + 1])
        (result_dir / "validation-report.json").write_text(
            "not-json-at-all", encoding="utf-8"
        )
        return ValidatorResult(
            returncode=1,
            stdout="",
            stderr="",
            timed_out=False,
            missing_script=False,
            error=None,
        )

    worker = _seed_phase_a(tmp_path, runner=_runner)
    outcomes = worker.process_once()
    assert outcomes[0].status == "malformed_report"

    package = worker.failed / _PHASE_A_TASK_ID
    assert (package / "validation-report.json").is_file()
    assert not (package / "result" / "validation-report.json").exists()

    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "malformed_report"
    assert record["validator_report"] == "validation-report.json"


# ---------------------------------------------------------------------------
# Slice D: recursive package safety (no symlinks, no non-regular entries)
# ---------------------------------------------------------------------------


def test_nested_symlink_in_task_is_rejected_and_preserves_processing(
    tmp_path: Path,
) -> None:
    """A nested symlink inside the claimed task package must be rejected
    as ``unsafe_package``. The processing directory is preserved untouched
    so an operator can inspect it."""
    worker = _make_worker(tmp_path)
    task_dir = worker.inbox / "task-001.ready"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps({"task_id": "task-001", "type": "phase_a"}),
        encoding="utf-8",
    )
    nested = task_dir / "nested"
    nested.mkdir()
    target_outside = tmp_path / "outside-target"
    target_outside.write_text("outside", encoding="utf-8")
    (nested / "leak").symlink_to(target_outside)

    _write_result(worker.results / "task-001.ready")

    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "unsafe_package"
    assert outcomes[0].task_id == "task-001"

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "task" / "task.json").is_file()
    assert (processing / "task" / "nested" / "leak").is_symlink()
    assert (processing / "result" / "result.json").is_file()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs require POSIX")
def test_nested_fifo_in_result_is_rejected_and_preserves_processing(
    tmp_path: Path,
) -> None:
    """A nested FIFO inside the claimed result package must be rejected
    as ``unsafe_package``. The processing directory is preserved untouched."""
    worker = _make_worker(tmp_path)
    _write_task(worker.inbox / "task-001.ready")

    result_dir = worker.results / "task-001.ready"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text("{}", encoding="utf-8")
    nested = result_dir / "nested"
    nested.mkdir()
    os.mkfifo(nested / "pipe")

    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "unsafe_package"
    assert outcomes[0].task_id == "task-001"

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "task" / "task.json").is_file()
    assert (processing / "result" / "result.json").is_file()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


# ---------------------------------------------------------------------------
# Slice C3: task.json failure evidence + failed-destination conflict
# ---------------------------------------------------------------------------


def _seed_task_with_raw_json(
    tmp_path: Path,
    task_id: str,
    *,
    task_json_text: str,
    write_task_json: bool = True,
) -> StrategyCombinedArchive:
    """Seed inbox/result with a controlled (possibly malformed) task.json."""
    worker = _make_worker(tmp_path)
    task_dir = worker.inbox / f"{task_id}.ready"
    task_dir.mkdir(parents=True, exist_ok=True)
    if write_task_json:
        (task_dir / "task.json").write_text(task_json_text, encoding="utf-8")
    _write_result(worker.results / f"{task_id}.ready")
    return worker


def test_malformed_task_json_writes_evidence_and_moves_to_failed(
    tmp_path: Path,
) -> None:
    """A malformed ``task.json`` must produce ``task_json_malformed`` with
    manifest and validation-record.json written to ``processing`` before the
    package is moved to ``failed/<task_id>``.  The original task and result
    files remain present inside the moved package."""
    worker = _seed_task_with_raw_json(
        tmp_path, "task-001", task_json_text="{not valid json"
    )
    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "task_json_malformed"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None
    assert "not valid JSON" in outcomes[0].error

    package = worker.failed / "task-001"
    assert package.is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.archive / "task-001").exists()

    assert (package / "manifest.json").is_file()
    assert (package / "validation-record.json").is_file()

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "strategy-archive-manifest/1.0"
    assert manifest["task_id"] == "task-001"
    assert manifest["task_type"] is None
    assert manifest["validator_identity"] is None
    paths = sorted(entry["path"] for entry in manifest["entries"])
    assert paths == sorted(["result/result.json", "task/task.json"])

    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["schema_version"] == "strategy-archive-record/1.0"
    assert record["authority"] == "file-level validated archive"
    assert record["task_id"] == "task-001"
    assert record["task_type"] is None
    assert record["status"] == "task_json_malformed"
    assert record["validator_exit_code"] is None
    assert record["validator_report"] is None
    assert record["validator_stdout"] is None
    assert record["validator_stderr"] is None
    assert record["processing_outcome"] is None
    assert record["errors"] == [
        {"code": "task_json_malformed", "message": outcomes[0].error}
    ]
    assert record["warnings"] == []
    assert record["reviews"] == []

    assert (package / "task" / "task.json").is_file()
    assert (package / "result" / "result.json").is_file()


def test_identity_mismatch_writes_evidence_and_moves_to_failed(
    tmp_path: Path,
) -> None:
    """An identity mismatch must produce ``identity_mismatch`` with manifest
    and validation-record.json written to ``processing`` before the package
    is moved to ``failed/<task_id>``.  The original task/result files remain
    present inside the moved package."""
    worker = _seed_pair(
        tmp_path,
        "task-001",
        task_payload={"task_id": "wrong-id", "type": "phase_a"},
    )
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "identity_mismatch"
    assert "wrong-id" in (outcomes[0].error or "")

    package = worker.failed / "task-001"
    assert package.is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.archive / "task-001").exists()

    assert (package / "manifest.json").is_file()
    assert (package / "validation-record.json").is_file()

    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "identity_mismatch"
    assert record["task_id"] == "task-001"
    assert record["errors"] == [
        {"code": "identity_mismatch", "message": outcomes[0].error}
    ]
    assert record["processing_outcome"] is None

    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_id"] == "task-001"
    assert manifest["validator_identity"] is None

    assert (package / "task" / "task.json").is_file()
    assert (package / "result" / "result.json").is_file()


def test_task_json_failure_with_existing_failed_does_not_overwrite(
    tmp_path: Path,
) -> None:
    """When ``failed/<task_id>`` already exists during a task.json failure
    path, the result must be ``finish_conflict``, processing must be
    preserved with both evidence files, and the existing failed directory
    must remain untouched."""
    worker = _seed_pair(
        tmp_path,
        "task-001",
        task_payload={"task_id": "wrong-id", "type": "phase_a"},
    )
    (worker.failed / "task-001").mkdir(parents=True)
    (worker.failed / "task-001" / "keep").write_text("preserve")

    outcomes = worker.process_once(lambda _p: None)
    assert len(outcomes) == 1
    assert outcomes[0].status == "finish_conflict"
    assert outcomes[0].task_id == "task-001"
    assert "finish failed" in (outcomes[0].error or "")
    assert "identity_mismatch" in (outcomes[0].error or "") or (
        "wrong-id" in (outcomes[0].error or "")
    )

    failed = worker.failed / "task-001"
    assert failed.is_dir()
    assert (failed / "keep").is_file()
    assert (failed / "keep").read_text(encoding="utf-8") == "preserve"
    assert not (failed / "manifest.json").exists()
    assert not (failed / "validation-record.json").exists()

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "manifest.json").is_file()
    assert (processing / "validation-record.json").is_file()
    assert (processing / "task" / "task.json").is_file()
    assert (processing / "result" / "result.json").is_file()

    record = json.loads(
        (processing / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "identity_mismatch"
    expected_message = (
        "task.json task_id does not match path: 'wrong-id' != 'task-001'"
    )
    assert record["errors"] == [
        {"code": "identity_mismatch", "message": expected_message}
    ]

    assert not (worker.archive / "task-001").exists()


def test_missing_task_json_writes_evidence_and_moves_to_failed(
    tmp_path: Path,
) -> None:
    """A safe package whose ``task.json`` is missing must produce
    ``task_json_missing`` with both evidence files in the failed package."""
    worker = _seed_task_with_raw_json(
        tmp_path, "task-001", task_json_text="", write_task_json=False
    )
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "task_json_missing"
    assert outcomes[0].task_id == "task-001"

    package = worker.failed / "task-001"
    assert package.is_dir()
    assert (package / "manifest.json").is_file()
    assert (package / "validation-record.json").is_file()

    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "task_json_missing"
    assert record["errors"] == [
        {"code": "task_json_missing", "message": outcomes[0].error}
    ]
    assert (package / "task").is_dir()
    assert (package / "result" / "result.json").is_file()


def test_non_object_task_json_writes_evidence_and_moves_to_failed(
    tmp_path: Path,
) -> None:
    """A non-object ``task.json`` payload must produce ``task_json_not_object``
    with both evidence files in the failed package."""
    worker = _seed_task_with_raw_json(
        tmp_path, "task-001", task_json_text="[1, 2, 3]"
    )
    outcomes = worker.process_once(lambda _p: None)
    assert outcomes[0].status == "task_json_not_object"
    assert outcomes[0].task_id == "task-001"
    assert "must be an object" in (outcomes[0].error or "")

    package = worker.failed / "task-001"
    assert package.is_dir()
    assert (package / "manifest.json").is_file()
    assert (package / "validation-record.json").is_file()

    record = json.loads(
        (package / "validation-record.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "task_json_not_object"
    assert record["errors"] == [
        {"code": "task_json_not_object", "message": outcomes[0].error}
    ]
    assert (package / "task" / "task.json").is_file()
    assert (package / "result" / "result.json").is_file()


# ---------------------------------------------------------------------------
# Slice C4: recover_once -- resume processing/<task_id> residue
# ---------------------------------------------------------------------------


def _seed_processing_residue(
    tmp_path: Path,
    task_id: str = "task-001",
    *,
    task_payload: dict[str, object] | None = None,
    skip_task: bool = False,
    skip_result: bool = False,
) -> StrategyCombinedArchive:
    """Seed a direct ``processing/<task_id>`` residue with safe task/result."""
    worker = _make_worker(tmp_path)
    processing = worker.processing / task_id
    processing.mkdir(parents=True, exist_ok=True)
    if not skip_task:
        task_dir = processing / "task"
        task_dir.mkdir(parents=True, exist_ok=True)
        payload = task_payload if task_payload is not None else {
            "task_id": task_id,
            "type": "phase_a",
        }
        (task_dir / "task.json").write_text(json.dumps(payload), encoding="utf-8")
    if not skip_result:
        result_dir = processing / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "result.json").write_text("{}", encoding="utf-8")
    return worker


def test_recover_once_resumes_valid_residue_to_archive(tmp_path: Path) -> None:
    """A processing residue with safe ``task/`` and ``result/`` subdirs
    resumes through the same handler path as :meth:`process_once` and ends
    up in ``archive``. The residue is never moved back to inbox/results."""
    worker = _seed_processing_residue(tmp_path, "task-001")
    processing = worker.processing / "task-001"

    seen: list[Path] = []

    def handler(processing_path: Path) -> None:
        seen.append(processing_path)

    outcomes = worker.recover_once(handler)

    assert len(outcomes) == 1
    assert outcomes[0].status == "success"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is None
    assert isinstance(outcomes[0], StrategyPackageOutcome)
    assert seen == [processing]
    assert (worker.archive / "task-001" / "task" / "task.json").is_file()
    assert (worker.archive / "task-001" / "result" / "result.json").is_file()
    assert not (worker.inbox / "task-001.ready").exists()
    assert not (worker.results / "task-001.ready").exists()
    assert not (worker.processing / "task-001").exists()


def test_recover_once_missing_task_returns_processing_residue(
    tmp_path: Path,
) -> None:
    """A residue without a ``task/`` subdirectory returns
    ``processing_residue`` and is left untouched -- no evidence files,
    no move to archive or failed."""
    worker = _seed_processing_residue(tmp_path, "task-001", skip_task=True)

    outcomes = worker.recover_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "processing_residue"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "result" / "result.json").is_file()
    assert not (processing / "task").exists()
    assert not (processing / "manifest.json").exists()
    assert not (processing / "validation-record.json").exists()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_recover_once_missing_result_returns_processing_residue(
    tmp_path: Path,
) -> None:
    """A residue without a ``result/`` subdirectory returns
    ``processing_residue`` and is left untouched -- no evidence files,
    no move to archive or failed."""
    worker = _seed_processing_residue(tmp_path, "task-001", skip_result=True)

    outcomes = worker.recover_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "processing_residue"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "task" / "task.json").is_file()
    assert not (processing / "result").exists()
    assert not (processing / "manifest.json").exists()
    assert not (processing / "validation-record.json").exists()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_recover_once_nested_symlink_returns_processing_residue(
    tmp_path: Path,
) -> None:
    """A residue whose ``result/`` contains a nested symlink returns
    ``processing_residue`` and is left untouched -- no evidence files,
    no move to archive or failed."""
    worker = _seed_processing_residue(tmp_path, "task-001")
    outside = tmp_path / "outside-target"
    outside.write_text("outside", encoding="utf-8")
    (worker.processing / "task-001" / "result" / "leak").symlink_to(outside)

    outcomes = worker.recover_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "processing_residue"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None

    processing = worker.processing / "task-001"
    assert processing.is_dir()
    assert (processing / "task" / "task.json").is_file()
    assert (processing / "result" / "result.json").is_file()
    assert (processing / "result" / "leak").is_symlink()
    assert not (processing / "manifest.json").exists()
    assert not (processing / "validation-record.json").exists()
    assert not (worker.archive / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_recover_once_repeated_after_success_returns_empty(
    tmp_path: Path,
) -> None:
    """After a successful recovery the ``processing/<task_id>`` entry is
    gone, so a second ``recover_once`` returns an empty tuple."""
    worker = _seed_processing_residue(tmp_path, "task-001")

    first = worker.recover_once(lambda _p: None)
    assert len(first) == 1
    assert first[0].status == "success"
    assert not (worker.processing / "task-001").exists()

    second = worker.recover_once(lambda _p: None)
    assert second == ()


# ---------------------------------------------------------------------------
# Slice C5a: compare ready trees with an archived manifest
# ---------------------------------------------------------------------------


def test_archive_matches_sources_requires_identical_safe_trees(tmp_path: Path) -> None:
    worker = _make_worker(tmp_path)
    task = worker.inbox / "task-001.ready"
    result = worker.results / "task-001.ready"
    _write_task(task)
    _write_result(result)
    (task / "nested").mkdir()
    (task / "nested" / "note.txt").write_text("note", encoding="utf-8")
    archive = worker.archive / "task-001"
    (archive / "task" / "nested").mkdir(parents=True)
    (archive / "result").mkdir()
    (archive / "task" / "task.json").write_bytes((task / "task.json").read_bytes())
    (archive / "task" / "nested" / "note.txt").write_text("note", encoding="utf-8")
    (archive / "result" / "result.json").write_bytes((result / "result.json").read_bytes())
    entries = []
    for relative in ("task/task.json", "task/nested/note.txt", "result/result.json"):
        path = archive / relative
        entries.append(
            {"path": relative, "size": path.stat().st_size, "sha256": _sha256_lower(path)}
        )
    _write_json(
        archive / "manifest.json",
        {"schema_version": MANIFEST_SCHEMA_VERSION, "task_id": "task-001", "entries": entries},
    )

    assert worker._archive_matches_sources("task-001") is True
    (result / "result.json").write_text("changed", encoding="utf-8")
    assert worker._archive_matches_sources("task-001") is False


def test_archive_matches_sources_rejects_invalid_manifest_and_symlink(
    tmp_path: Path,
) -> None:
    worker = _seed_pair(tmp_path)
    archive = worker.archive / "task-001"
    (archive / "task").mkdir(parents=True)
    (archive / "result").mkdir()
    (archive / "task" / "task.json").write_bytes(
        (worker.inbox / "task-001.ready" / "task.json").read_bytes()
    )
    (archive / "result" / "result.json").write_bytes(
        (worker.results / "task-001.ready" / "result.json").read_bytes()
    )
    _write_json(
        archive / "manifest.json",
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": "task-001",
            "entries": [{"path": "task/../result/result.json", "size": 2, "sha256": "0" * 64}],
        },
    )
    assert worker._archive_matches_sources("task-001") is False
    (worker.inbox / "task-001.ready" / "leak").symlink_to(
        worker.results / "task-001.ready" / "result.json"
    )
    assert worker._archive_matches_sources("task-001") is False


# ---------------------------------------------------------------------------
# Slice C5b: process_once short-circuits when archive already covers the pair
# ---------------------------------------------------------------------------


def _seed_archive_matching_pair(
    worker: StrategyCombinedArchive,
    task_id: str,
) -> None:
    """Materialize ``archive/<task_id>`` with files + manifest that match
    the seeded ``inbox`` and ``results`` ready trees for ``task_id``."""
    inbox_ready = worker.inbox / f"{task_id}.ready"
    result_ready = worker.results / f"{task_id}.ready"
    archive_dir = worker.archive / task_id
    (archive_dir / "task").mkdir(parents=True)
    (archive_dir / "result").mkdir()
    for relpath, source in (
        ("task/task.json", inbox_ready / "task.json"),
        ("result/result.json", result_ready / "result.json"),
    ):
        target = archive_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    entries = [
        {
            "path": relpath,
            "size": (archive_dir / relpath).stat().st_size,
            "sha256": _sha256_lower(archive_dir / relpath),
        }
        for relpath in ("task/task.json", "result/result.json")
    ]
    _write_json(
        archive_dir / "manifest.json",
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": task_id,
            "entries": entries,
        },
    )


def test_process_once_identical_archive_returns_already_archived(
    tmp_path: Path,
) -> None:
    """An archive whose manifest matches the ready trees must short-circuit
    ``process_once`` with ``already_archived``; the inbox, results, and
    archive directories are preserved untouched."""
    worker = _seed_pair(tmp_path, "task-001")
    _seed_archive_matching_pair(worker, "task-001")
    archive_manifest = (worker.archive / "task-001" / "manifest.json").read_bytes()
    archive_task_bytes = (
        worker.archive / "task-001" / "task" / "task.json"
    ).read_bytes()
    archive_result_bytes = (
        worker.archive / "task-001" / "result" / "result.json"
    ).read_bytes()

    outcomes = worker.process_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "already_archived"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is None
    assert (worker.inbox / "task-001.ready").is_dir()
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.failed / "task-001").exists()
    assert (worker.archive / "task-001" / "manifest.json").read_bytes() == archive_manifest
    assert (
        worker.archive / "task-001" / "task" / "task.json"
    ).read_bytes() == archive_task_bytes
    assert (
        worker.archive / "task-001" / "result" / "result.json"
    ).read_bytes() == archive_result_bytes


def test_process_once_changed_content_returns_archive_conflict(
    tmp_path: Path,
) -> None:
    """An archive whose manifest is structurally valid but whose file
    contents differ from the ready trees must short-circuit
    ``process_once`` with ``archive_conflict``; nothing is moved."""
    worker = _seed_pair(tmp_path, "task-001")
    archive_dir = worker.archive / "task-001"
    (archive_dir / "task").mkdir(parents=True)
    (archive_dir / "result").mkdir()
    (archive_dir / "task" / "task.json").write_text(
        json.dumps({"task_id": "task-001", "type": "phase_a"}),
        encoding="utf-8",
    )
    (archive_dir / "result" / "result.json").write_text(
        '{"changed": true}', encoding="utf-8"
    )
    entries = [
        {
            "path": relpath,
            "size": (archive_dir / relpath).stat().st_size,
            "sha256": _sha256_lower(archive_dir / relpath),
        }
        for relpath in ("task/task.json", "result/result.json")
    ]
    _write_json(
        archive_dir / "manifest.json",
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": "task-001",
            "entries": entries,
        },
    )
    archive_task_bytes = (archive_dir / "task" / "task.json").read_bytes()
    archive_result_bytes = (archive_dir / "result" / "result.json").read_bytes()

    outcomes = worker.process_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "archive_conflict"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None
    assert (worker.inbox / "task-001.ready").is_dir()
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.failed / "task-001").exists()
    assert (
        worker.archive / "task-001" / "task" / "task.json"
    ).read_bytes() == archive_task_bytes
    assert (
        worker.archive / "task-001" / "result" / "result.json"
    ).read_bytes() == archive_result_bytes


def test_process_once_invalid_manifest_returns_archive_conflict(
    tmp_path: Path,
) -> None:
    """An archive whose manifest cannot map to the ready trees (here an
    ``..``-laden entry path) must short-circuit ``process_once`` with
    ``archive_conflict``; the inbox and results are preserved untouched."""
    worker = _seed_pair(tmp_path, "task-001")
    archive_dir = worker.archive / "task-001"
    (archive_dir / "task").mkdir(parents=True)
    (archive_dir / "result").mkdir()
    (archive_dir / "task" / "task.json").write_bytes(
        (worker.inbox / "task-001.ready" / "task.json").read_bytes()
    )
    (archive_dir / "result" / "result.json").write_bytes(
        (worker.results / "task-001.ready" / "result.json").read_bytes()
    )
    _write_json(
        archive_dir / "manifest.json",
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": "task-001",
            "entries": [
                {
                    "path": "task/../result/result.json",
                    "size": 2,
                    "sha256": "0" * 64,
                }
            ],
        },
    )

    outcomes = worker.process_once(lambda _p: None)

    assert len(outcomes) == 1
    assert outcomes[0].status == "archive_conflict"
    assert outcomes[0].task_id == "task-001"
    assert outcomes[0].error is not None
    assert (worker.inbox / "task-001.ready").is_dir()
    assert (worker.results / "task-001.ready").is_dir()
    assert not (worker.processing / "task-001").exists()
    assert not (worker.failed / "task-001").exists()


def test_process_once_archive_path_symlink_or_file_preserves_sources(
    tmp_path: Path,
) -> None:
    """An ``archive/<task_id>`` path that is a symlink or a non-directory
    file must short-circuit ``process_once`` with ``archive_conflict``,
    leaving inbox/results and the unsafe archive entry untouched and never
    creating a processing package."""
    outside = tmp_path / "outside-archive"
    outside.mkdir()
    (outside / "task.json").write_text(
        json.dumps({"task_id": "task-001", "type": "phase_a"}),
        encoding="utf-8",
    )

    # Case A: archive/<task_id> is a symlink.
    case_a_root = tmp_path / "case-a"
    case_a_root.mkdir()
    worker_sym = _make_worker(case_a_root)
    _write_task(worker_sym.inbox / "task-001.ready", task_id="task-001")
    _write_result(worker_sym.results / "task-001.ready")
    (worker_sym.archive / "task-001").symlink_to(
        outside, target_is_directory=True
    )
    outcomes_sym = worker_sym.process_once(lambda _p: None)
    assert len(outcomes_sym) == 1
    assert outcomes_sym[0].status == "archive_conflict"
    assert outcomes_sym[0].task_id == "task-001"
    assert outcomes_sym[0].error is not None
    assert (worker_sym.inbox / "task-001.ready").is_dir()
    assert (worker_sym.results / "task-001.ready").is_dir()
    assert not (worker_sym.processing / "task-001").exists()
    assert not (worker_sym.failed / "task-001").exists()

    # Case B: archive/<task_id> is a regular file.
    case_b_root = tmp_path / "case-b"
    case_b_root.mkdir()
    worker_file = _make_worker(case_b_root)
    _write_task(worker_file.inbox / "task-001.ready", task_id="task-001")
    _write_result(worker_file.results / "task-001.ready")
    (worker_file.archive / "task-001").write_text(
        "not-a-directory", encoding="utf-8"
    )
    file_bytes = (worker_file.archive / "task-001").read_bytes()

    outcomes_file = worker_file.process_once(lambda _p: None)
    assert len(outcomes_file) == 1
    assert outcomes_file[0].status == "archive_conflict"
    assert outcomes_file[0].task_id == "task-001"
    assert outcomes_file[0].error is not None
    assert (worker_file.inbox / "task-001.ready").is_dir()
    assert (worker_file.results / "task-001.ready").is_dir()
    assert not (worker_file.processing / "task-001").exists()
    assert not (worker_file.failed / "task-001").exists()
    assert (worker_file.archive / "task-001").read_bytes() == file_bytes
    assert not (worker_file.archive / "task-001").is_dir()
    assert not (worker_file.archive / "task-001").is_symlink()
