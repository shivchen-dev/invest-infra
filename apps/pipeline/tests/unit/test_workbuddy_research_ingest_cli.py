import hashlib
import json
from pathlib import Path

import pytest
from invest_pipeline import workbuddy_research_ingest_cli as cli
from invest_pipeline.integrations.workbuddy_research_artifacts import (
    SUPPORTED_SCHEMA_VERSION,
)


def _write_package(
    package: Path,
    *,
    valid: bool = True,
    status: str = "success",
    task_id: str | None = None,
) -> None:
    package.mkdir(parents=True)
    report = b"research report"
    result = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "task_id": task_id or package.name.removesuffix(".ready"),
        "status": status,
        "artifacts": [
            {"path": "report.md", "sha256": hashlib.sha256(report).hexdigest()}
        ],
    }
    unsigned = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    result["result_hash"] = hashlib.sha256(unsigned).hexdigest()
    if not valid:
        result["result_hash"] = "0" * 64
    (package / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (package / "report.md").write_bytes(report)


def _stage_root(bridge_root: Path) -> Path:
    return bridge_root / "workbuddy" / "research"


def test_parser_exposes_required_archive_and_recovery_help() -> None:
    help_text = cli.build_parser().format_help()

    assert "--archive-root" in help_text
    assert "--bridge-root" in help_text
    assert "--recover" in help_text
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_empty_queue_is_success_and_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.run_import(tmp_path / "bridge", tmp_path / "artifacts")

    assert exit_code == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("artifact_status", ["success", "failed"])
def test_processes_real_package_and_creates_immutable_archive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    artifact_status: str,
) -> None:
    bridge_root = tmp_path / "private" / "bridge"
    result_package = _stage_root(bridge_root) / "results" / "task-001.ready"
    _write_package(result_package, status=artifact_status)
    archive_root = tmp_path / "private" / "immutable-artifacts"

    exit_code = cli.run_import(bridge_root, archive_root)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "stage": "research",
        "status": "success",
        "task_id": "task-001",
    }
    assert (_stage_root(bridge_root) / "archive" / "task-001").is_dir()
    archived = list((archive_root / "task-001" / SUPPORTED_SCHEMA_VERSION).iterdir())
    assert len(archived) == 1
    assert (archived[0] / "result.json").is_file()
    assert (archived[0] / "report.md").is_file()


def test_invalid_package_moves_to_failed_and_returns_nonzero_without_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bridge_root = tmp_path / "secret-bridge"
    package = _stage_root(bridge_root) / "results" / "bad-task.ready"
    _write_package(package, valid=False)
    archive_root = tmp_path / "secret-archive"

    exit_code = cli.run_import(bridge_root, archive_root)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.out) == {
        "stage": "research",
        "status": "failed",
        "task_id": "bad-task",
    }
    assert str(tmp_path) not in captured.out + captured.err
    assert (_stage_root(bridge_root) / "failed" / "bad-task").is_dir()


def test_declared_task_id_mismatch_fails_without_archiving_or_leaking_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bridge_root = tmp_path / "secret-bridge"
    package = _stage_root(bridge_root) / "results" / "directory-task.ready"
    _write_package(package, task_id="declared-task")
    archive_root = tmp_path / "secret-archive"

    exit_code = cli.run_import(bridge_root, archive_root)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.out) == {
        "stage": "research",
        "status": "failed",
        "task_id": "directory-task",
    }
    assert "declared-task" not in captured.out + captured.err
    assert not (archive_root / "declared-task").exists()
    assert (_stage_root(bridge_root) / "failed" / "directory-task").is_dir()


def test_recover_resumes_processing_residue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bridge_root = tmp_path / "bridge"
    residue = _stage_root(bridge_root) / "processing" / "interrupted"
    _write_package(residue)

    exit_code = cli.run_import(tmp_path / "bridge", tmp_path / "artifacts", recover=True)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["task_id"] == "interrupted"
    assert (_stage_root(bridge_root) / "archive" / "interrupted").is_dir()


def test_main_emits_fixed_error_for_factory_exception(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "must-not-leak"

    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(str(secret))

    monkeypatch.setattr(cli, "run_import", fail)

    exit_code = cli.main(["--archive-root", str(tmp_path / "archive")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.err) == {
        "error": "workbuddy_research_import_failed",
        "status": "error",
    }
    assert str(secret) not in captured.out + captured.err
