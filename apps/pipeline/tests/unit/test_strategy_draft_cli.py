from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from invest_pipeline.strategy_draft_cli import register_draft, run

SOURCE = "真实策略原文\n".encode()
SOURCE_HASH = hashlib.sha256(SOURCE).hexdigest()
FIXED_ID = UUID("11111111-1111-4111-8111-111111111111")


class Repo:
    def __init__(self) -> None:
        self.items = []

    def add(self, draft):
        for item in self.items:
            if (item.strategy_key, item.proposed_version) == (
                draft.strategy_key,
                draft.proposed_version,
            ):
                if item.artifact_hash != draft.artifact_hash:
                    raise RuntimeError("secret database detail")
                return item
        self.items.append(draft)
        return draft


class Uow:
    def __init__(self, repo: Repo) -> None:
        self.strategy_drafts = repo
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self):
        self.commits += 1


def _write_json(path: Path, value: object) -> bytes:
    data = json.dumps(value, ensure_ascii=False, indent=2).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _refresh_manifest(archive: Path) -> None:
    path = archive / "manifest.json"
    manifest = json.loads(path.read_bytes())
    for entry in manifest["entries"]:
        data = (archive / entry["path"]).read_bytes()
        entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    _write_json(path, manifest)


def make_archive(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "archive"
    source_file = tmp_path / "source.txt"
    source_file.write_bytes(SOURCE)
    source_doc = {
        "source_document_id": "source-1",
        "content_sha256": SOURCE_HASH,
        "source_uri": "https://example.test/article",
    }
    capability = {
        "assessment_id": "assessment-1",
        "task_id": "capability-task-1",
        "source_document": source_doc,
    }
    capability_bytes = _write_json(archive / "task/capability-assessment.json", capability)
    strategy = {
        "proposal_id": "proposal-1",
        "revision": 1,
        "task_id": "engineering-task-1",
        "status": "needs_review",
        "strategy_id": "sector-strength",
        "version_candidate": "1.0.0",
        "source_document": {
            "source_document_id": "source-1",
            "content_sha256": SOURCE_HASH,
        },
        "capability_assessment": {
            "assessment_id": "assessment-1",
            "task_id": "capability-task-1",
            "artifact_sha256": hashlib.sha256(capability_bytes).hexdigest(),
        },
    }
    validation = {
        "status": "passed",
        "task_id": "engineering-task-1",
        "proposal_id": "proposal-1",
        "proposal_revision": 1,
    }
    _write_json(archive / "result/strategy.json", strategy)
    _write_json(archive / "result/validation.json", validation)
    _write_json(archive / "task/source-document.json", source_doc)
    entries = []
    for relative in (
        "result/strategy.json",
        "result/validation.json",
        "task/source-document.json",
        "task/capability-assessment.json",
    ):
        data = (archive / relative).read_bytes()
        entries.append(
            {"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    manifest = {
        "schema_version": "strategy-archive-manifest/1.0",
        "task_id": "engineering-task-1",
        "entries": entries,
    }
    _write_json(archive / "manifest.json", manifest)
    return archive, source_file, manifest


def invoke(tmp_path: Path, repo: Repo | None = None, draft_id: UUID = FIXED_ID):
    archive, source_file, _ = make_archive(tmp_path)
    repository = repo or Repo()
    uow = Uow(repository)
    result = register_draft(
        archive_dir=archive,
        source_content_file=source_file,
        artifact_root=tmp_path / "artifacts",
        uow_factory=lambda: uow,
        draft_id_factory=lambda: draft_id,
        clock=lambda: datetime(2026, 8, 26, tzinfo=UTC),
    )
    return result, repository, uow, archive, source_file


def test_registers_verified_archive_and_safe_artifacts(tmp_path: Path) -> None:
    result, repo, uow, _, _ = invoke(tmp_path)

    draft = repo.items[0]
    assert result == {
        "draft_id": str(FIXED_ID),
        "strategy_key": "sector-strength",
        "proposed_version": "1.0.0",
        "artifact_hash": draft.artifact_hash,
        "artifact_ref": draft.artifact_ref,
        "idempotent": False,
    }
    assert uow.commits == 1
    assert draft.artifact_ref == f"sector-strength/1.0.0/{draft.artifact_hash}/strategy.json"
    base = tmp_path / "artifacts" / Path(draft.artifact_ref).parent
    assert (base / "strategy.json").read_bytes()
    assert (base / "source.txt").read_bytes() == SOURCE
    assert {item.ref for item in draft.source_refs} == {
        "https://example.test/article",
        f"{base.relative_to(tmp_path / 'artifacts')}/source.txt",
        f"{base.relative_to(tmp_path / 'artifacts')}/capability-assessment.json",
    }
    assert draft.validation_result["manifest"]["verified"] is True
    assert draft.validation_result["validation"]["status"] == "passed"
    assert draft.validation_result["capability_assessment"]["assessment_id"] == "assessment-1"


def test_repeated_registration_is_idempotent(tmp_path: Path) -> None:
    repo = Repo()
    first, _, _, _, _ = invoke(tmp_path, repo)
    second, _, _, _, _ = invoke(tmp_path, repo, UUID("22222222-2222-4222-8222-222222222222"))
    assert first["draft_id"] == second["draft_id"]
    assert second["idempotent"] is True
    assert len(repo.items) == 1


@pytest.mark.parametrize(
    ("mutation", "target"),
    [
        (lambda value: value.update(status="failed"), "result/validation.json"),
        (lambda value: value.update(content_sha256="0" * 64), "task/source-document.json"),
        (
            lambda value: value["capability_assessment"].update(artifact_sha256="0" * 64),
            "result/strategy.json",
        ),
    ],
)
def test_rejects_contract_mismatch(tmp_path: Path, mutation, target: str) -> None:
    archive, source_file, _ = make_archive(tmp_path)
    value = json.loads((archive / target).read_bytes())
    mutation(value)
    _write_json(archive / target, value)
    _refresh_manifest(archive)
    with pytest.raises(ValueError):
        register_draft(archive, source_file, tmp_path / "artifacts", lambda: Uow(Repo()))


def test_rejects_manifest_tampering_and_unsafe_entry(tmp_path: Path) -> None:
    archive, source_file, manifest = make_archive(tmp_path)
    (archive / "result/strategy.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        register_draft(archive, source_file, tmp_path / "artifacts", lambda: Uow(Repo()))

    archive, source_file, manifest = make_archive(tmp_path / "other")
    manifest["entries"][0]["path"] = "../escape.json"
    _write_json(archive / "manifest.json", manifest)
    with pytest.raises(ValueError):
        register_draft(archive, source_file, tmp_path / "artifacts2", lambda: Uow(Repo()))


def test_rejects_artifact_conflict_and_symlink_escape(tmp_path: Path) -> None:
    result, _, _, _, _ = invoke(tmp_path)
    target = tmp_path / "artifacts" / result["artifact_ref"]
    target.write_bytes(b"different")
    archive, source_file, _ = make_archive(tmp_path)
    with pytest.raises(ValueError):
        register_draft(archive, source_file, tmp_path / "artifacts", lambda: Uow(Repo()))

    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "linked-artifacts"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        register_draft(archive, source_file, root, lambda: Uow(Repo()))


def test_run_redacts_failure_and_writes_safe_json(tmp_path: Path) -> None:
    archive, source_file, _ = make_archive(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    code = run(
        archive_dir=archive,
        source_content_file=source_file,
        artifact_root=tmp_path / "artifacts",
        uow_factory=lambda: Uow(Repo()),
        stdout=out,
        stderr=err,
        draft_id_factory=lambda: FIXED_ID,
    )
    assert code == 0
    assert json.loads(out.getvalue())["draft_id"] == str(FIXED_ID)
    assert err.getvalue() == ""

    code = run(
        archive_dir="/secret/missing",
        source_content_file="/secret/source",
        artifact_root=tmp_path / "artifacts",
        uow_factory=lambda: Uow(Repo()),
        stdout=out,
        stderr=err,
    )
    assert code == 1
    assert err.getvalue() == "error: strategy draft registration failed\n"
    assert "/secret" not in err.getvalue()
