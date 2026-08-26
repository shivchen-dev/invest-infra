from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

from invest_domain.strategy import SourceRef, StrategyDraft

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_REQUIRED = {
    "result/strategy.json",
    "result/validation.json",
    "task/source-document.json",
    "task/capability-assessment.json",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(data: bytes) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _safe_relative(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid manifest path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid manifest path")
    return path


def _archive_file(root: Path, relative: PurePosixPath) -> Path:
    root_real = root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("invalid archive entry")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root_real):
        raise ValueError("archive entry escaped root")
    return resolved


def _verify_manifest(archive: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    manifest_path = archive / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest unavailable")
    manifest = _object(manifest_path.read_bytes())
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest entries invalid")
    verified: dict[str, bytes] = {}
    normalized: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("manifest entry invalid")
        relative = _safe_relative(item.get("path"))
        key = relative.as_posix()
        if key in verified:
            raise ValueError("duplicate manifest entry")
        data = _archive_file(archive, relative).read_bytes()
        if item.get("size") != len(data) or item.get("sha256") != _sha(data):
            raise ValueError("manifest integrity failure")
        verified[key] = data
        normalized.append({"path": key, "size": len(data), "sha256": _sha(data)})
    if not _REQUIRED.issubset(verified):
        raise ValueError("required artifact absent")
    summary = {
        "task_id": manifest.get("task_id"),
        "entries": normalized,
        "verified": True,
    }
    return verified, summary


def _same_source(left: Any, right: dict[str, Any]) -> bool:
    return isinstance(left, dict) and all(
        left.get(field) == right.get(field) for field in ("source_document_id", "content_sha256")
    )


def _validate_contract(
    files: dict[str, bytes], manifest: dict[str, Any], source_bytes: bytes
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    strategy = _object(files["result/strategy.json"])
    validation = _object(files["result/validation.json"])
    source = _object(files["task/source-document.json"])
    capability = _object(files["task/capability-assessment.json"])
    source_bytes.decode("utf-8", errors="strict")
    if source.get("content_sha256") != _sha(source_bytes):
        raise ValueError("source content mismatch")
    if strategy.get("status") != "needs_review":
        raise ValueError("strategy status invalid")
    key, version = strategy.get("strategy_id"), strategy.get("version_candidate")
    if not isinstance(key, str) or not _SAFE_SEGMENT.fullmatch(key):
        raise ValueError("strategy identity invalid")
    if not isinstance(version, str) or not _SAFE_SEGMENT.fullmatch(version):
        raise ValueError("strategy version invalid")
    if not _same_source(strategy.get("source_document"), source):
        raise ValueError("strategy source mismatch")
    task_id = strategy.get("task_id")
    if task_id != manifest.get("task_id") or validation.get("task_id") != task_id:
        raise ValueError("task binding mismatch")
    if validation.get("status") != "passed":
        raise ValueError("validation did not pass")
    if validation.get("proposal_id") != strategy.get("proposal_id") or validation.get(
        "proposal_revision"
    ) != strategy.get("revision"):
        raise ValueError("proposal binding mismatch")
    declared = strategy.get("capability_assessment")
    capability_bytes = files["task/capability-assessment.json"]
    if not isinstance(declared, dict) or declared.get("artifact_sha256") != _sha(capability_bytes):
        raise ValueError("capability hash mismatch")
    for field in ("assessment_id", "task_id"):
        if declared.get(field) != capability.get(field):
            raise ValueError("capability binding mismatch")
    return strategy, validation, source, capability


def _prepare_directory(root: Path, parts: tuple[str, ...]) -> Path:
    if root.is_symlink():
        raise ValueError("artifact root invalid")
    root.mkdir(parents=True, exist_ok=True)
    root_real = root.resolve(strict=True)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("artifact path invalid")
        current.mkdir(exist_ok=True)
    if not current.resolve(strict=True).is_relative_to(root_real):
        raise ValueError("artifact path escaped root")
    return current


def _atomic_immutable(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise ValueError("artifact target invalid")
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError("artifact conflict")
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError("artifact conflict")
        else:
            os.replace(temporary, path)
            temporary = ""
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def register_draft(
    archive_dir: str | Path,
    source_content_file: str | Path,
    artifact_root: str | Path,
    uow_factory: Callable[[], Any],
    *,
    draft_id_factory: Callable[[], Any] | None = None,
    clock: Callable[[], Any] | None = None,
) -> dict[str, object]:
    archive = Path(archive_dir)
    files, manifest = _verify_manifest(archive)
    source_bytes = Path(source_content_file).read_bytes()
    strategy, validation, source, capability = _validate_contract(files, manifest, source_bytes)
    strategy_bytes = files["result/strategy.json"]
    artifact_hash = _sha(strategy_bytes)
    parts = (strategy["strategy_id"], strategy["version_candidate"], artifact_hash)
    destination = _prepare_directory(Path(artifact_root), parts)
    artifacts = {
        "strategy.json": strategy_bytes,
        "source.txt": source_bytes,
        "capability-assessment.json": files["task/capability-assessment.json"],
        "validation.json": files["result/validation.json"],
    }
    for name, data in artifacts.items():
        _atomic_immutable(destination / name, data)
    base_ref = PurePosixPath(*parts)
    draft = StrategyDraft.create(
        strategy_key=strategy["strategy_id"],
        proposed_version=strategy["version_candidate"],
        artifact_ref=(base_ref / "strategy.json").as_posix(),
        artifact_hash=artifact_hash,
        source_refs=(
            SourceRef(ref=source["source_uri"], content_hash=source["content_sha256"]),
            SourceRef(ref=(base_ref / "source.txt").as_posix(), content_hash=_sha(source_bytes)),
            SourceRef(
                ref=(base_ref / "capability-assessment.json").as_posix(),
                content_hash=_sha(artifacts["capability-assessment.json"]),
            ),
        ),
        validation_result={
            "manifest": manifest,
            "validation": validation,
            "capability_assessment": capability,
        },
        draft_id_factory=draft_id_factory,
        clock=clock,
    )
    with uow_factory() as uow:
        saved = uow.strategy_drafts.add(draft)
        uow.commit()
    return {
        "draft_id": str(saved.draft_id),
        "strategy_key": saved.strategy_key,
        "proposed_version": saved.proposed_version,
        "artifact_hash": saved.artifact_hash,
        "artifact_ref": saved.artifact_ref,
        "idempotent": saved.draft_id != draft.draft_id,
    }


def run(*, stdout: TextIO | None = None, stderr: TextIO | None = None, **kwargs: Any) -> int:
    try:
        result = register_draft(**kwargs)
        (stdout or sys.stdout).write(json.dumps(result, sort_keys=True) + "\n")
        return 0
    except Exception:  # noqa: BLE001
        (stderr or sys.stderr).write("error: strategy draft registration failed\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invest_pipeline.strategy_draft_cli")
    for name in ("archive-dir", "source-content-file", "artifact-root"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    from invest_storage.database import build_engine, session_factory
    from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

    from invest_pipeline.config import get_settings

    engine = build_engine(get_settings().database_url)
    try:
        factory = session_factory(engine)
        return run(**vars(args), uow_factory=lambda: SqlAlchemyUnitOfWork(factory))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
