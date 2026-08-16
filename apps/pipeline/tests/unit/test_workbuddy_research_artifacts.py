import hashlib
import json
from pathlib import Path

import pytest
from invest_pipeline.integrations.workbuddy_research_artifacts import (
    SUPPORTED_SCHEMA_VERSION,
    discover_research_artifact_packages,
    ingest_research_artifact,
)


def _write_package(root: Path, *, status="success", task_id="task-001", report="hello") -> Path:
    package = root / "package"
    package.mkdir(parents=True)
    report_bytes = report.encode()
    result = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "task_id": task_id,
        "status": status,
        "summary": "test",
        "artifacts": [{"path": "report.md", "sha256": hashlib.sha256(report_bytes).hexdigest()}],
    }
    unsigned = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    result["result_hash"] = hashlib.sha256(unsigned).hexdigest()
    (package / "result.json").write_bytes(json.dumps(result, ensure_ascii=False).encode())
    (package / "report.md").write_bytes(report_bytes)
    return package


def test_ingests_each_supported_status_and_is_idempotent(tmp_path: Path) -> None:
    for status in ("success", "partial", "failed", "blocked_no_data"):
        package = _write_package(tmp_path / status, status=status, task_id=f"task-{status}")
        first = ingest_research_artifact(package, tmp_path / "archive")
        second = ingest_research_artifact(package, tmp_path / "archive")
        assert first.status == status
        assert first.idempotent is False
        assert second.idempotent is True
        assert second.archive_dir == first.archive_dir


@pytest.mark.parametrize("task_id", ["../escape", "/absolute", "bad id", ".hidden"])
def test_rejects_unsafe_task_id(tmp_path: Path, task_id: str) -> None:
    package = _write_package(tmp_path / "case", task_id=task_id)
    outcome = ingest_research_artifact(package, tmp_path / "archive")
    assert outcome.status == "failed"
    assert "safe single path segment" in outcome.diagnostics[0]
    assert not (tmp_path / "archive").exists()


def test_rejects_unexpected_task_id_before_archiving(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "case", task_id="declared-task")
    archive = tmp_path / "archive"

    outcome = ingest_research_artifact(
        package, archive, expected_task_id="directory-task"
    )

    assert outcome.status == "failed"
    assert outcome.archive_dir is None
    assert not (archive / "declared-task").exists()


def test_rejects_bad_hash_malformed_and_report_symlink(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "hash")
    payload = json.loads((package / "result.json").read_text())
    payload["result_hash"] = "0" * 64
    (package / "result.json").write_text(json.dumps(payload))
    assert ingest_research_artifact(package, tmp_path / "archive").status == "failed"

    malformed = _write_package(tmp_path / "malformed")
    (malformed / "result.json").write_text("{")
    assert ingest_research_artifact(malformed, tmp_path / "archive2").status == "failed"

    symlinked = _write_package(tmp_path / "symlink")
    (symlinked / "report.md").unlink()
    (symlinked / "report.md").symlink_to(tmp_path / "outside.md")
    assert ingest_research_artifact(symlinked, tmp_path / "archive3").status == "failed"


def test_conflicting_task_delivery_is_diagnostic_and_does_not_overwrite(tmp_path: Path) -> None:
    first = _write_package(tmp_path / "first", report="one")
    second = _write_package(tmp_path / "second", report="two")
    archive = tmp_path / "archive"
    ingest_research_artifact(first, archive)
    conflict = ingest_research_artifact(second, archive)
    assert conflict.status == "failed"
    assert "conflicting delivery" in conflict.diagnostics[0]
    assert (archive / "task-001" / SUPPORTED_SCHEMA_VERSION).exists()


def test_rejects_archive_symlink_escape(tmp_path: Path) -> None:
    package = _write_package(tmp_path / "package")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "task-001").symlink_to(tmp_path / "outside", target_is_directory=True)
    outcome = ingest_research_artifact(package, archive)
    assert outcome.status == "failed"
    assert "escapes archive root" in outcome.diagnostics[0]


def _create_bare_package(parent: Path, name: str) -> Path:
    package = parent / name
    package.mkdir(parents=True)
    (package / "result.json").write_text("{}")
    (package / "report.md").write_text("report")
    return package


def test_discovers_valid_packages_only(tmp_path: Path) -> None:
    valid_a = _create_bare_package(tmp_path, "alpha")
    valid_b = _create_bare_package(tmp_path, "beta")
    missing_result = tmp_path / "missing-result"
    missing_result.mkdir()
    (missing_result / "report.md").write_text("r")
    missing_report = tmp_path / "missing-report"
    missing_report.mkdir()
    (missing_report / "result.json").write_text("{}")

    discovered = discover_research_artifact_packages(tmp_path)

    assert discovered == [valid_a, valid_b]


def test_discovery_ignores_symlinked_package_directories(tmp_path: Path) -> None:
    valid = _create_bare_package(tmp_path, "real-pkg")
    outside_target = tmp_path / "outside-root" / "target-pkg"
    outside_target.mkdir(parents=True)
    (outside_target / "result.json").write_text("{}")
    (outside_target / "report.md").write_text("report")
    (tmp_path / "linked-pkg").symlink_to(outside_target, target_is_directory=True)

    discovered = discover_research_artifact_packages(tmp_path)

    assert discovered == [valid]


def test_discovery_ignores_symlinked_result_or_report_files(tmp_path: Path) -> None:
    valid = _create_bare_package(tmp_path, "good")
    sym_result = _create_bare_package(tmp_path, "sym-result")
    (sym_result / "result.json").unlink()
    (sym_result / "result.json").symlink_to(valid / "result.json")

    sym_report = _create_bare_package(tmp_path, "sym-report")
    (sym_report / "report.md").unlink()
    (sym_report / "report.md").symlink_to(valid / "report.md")

    discovered = discover_research_artifact_packages(tmp_path)

    assert discovered == [valid]


def test_discovery_ignores_temporary_directories(tmp_path: Path) -> None:
    valid = _create_bare_package(tmp_path, "good")
    _create_bare_package(tmp_path, ".workbuddy-abc123")
    _create_bare_package(tmp_path, ".workbuddy-partial")

    discovered = discover_research_artifact_packages(tmp_path)

    assert discovered == [valid]
    assert all(not path.name.startswith(".workbuddy-") for path in discovered)


def test_discovery_returns_results_in_stable_sorted_order(tmp_path: Path) -> None:
    names = ["zeta", "alpha", "mu", "beta"]
    expected_paths = [_create_bare_package(tmp_path, name) for name in sorted(names)]

    discovered = discover_research_artifact_packages(tmp_path)

    assert [p.name for p in discovered] == sorted(names)
    assert discovered == sorted(expected_paths)
    first = discover_research_artifact_packages(tmp_path)
    second = discover_research_artifact_packages(tmp_path)
    assert first == second
