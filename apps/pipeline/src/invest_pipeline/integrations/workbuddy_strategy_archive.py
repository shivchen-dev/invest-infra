"""Combined ``task``+``result`` lifecycle for the WorkBuddy strategy stage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_READY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ready$")
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

MANIFEST_SCHEMA_VERSION = "strategy-archive-manifest/1.0"
RECORD_SCHEMA_VERSION = "strategy-archive-record/1.0"
ARCHIVE_AUTHORITY = "file-level validated archive"

PHASE_A_TASK_SCHEMA = "strategy-capability-assessment-task/1.0"
PHASE_A_TASK_TYPE = "capability_assessment"
PHASE_A_VALIDATOR_REL = "scripts/validate_strategy_delivery.py"
PHASE_A_REPORT_NAME = "validation-report.json"

PHASE_B_TASK_SCHEMA = "strategy-engineering-task/1.0"
PHASE_B_TASK_TYPE = "strategy_engineering"
PHASE_B_VALIDATOR_REL = "scripts/validate_strategy_proposal.py"
PHASE_B_REPORT_NAME = "proposal-preflight-report.json"

DEFAULT_VALIDATOR_TIMEOUT = 60.0
DEFAULT_EVIDENCE_MAX_BYTES = 65_536

_ROUTING: dict[tuple[str, str], tuple[str, str]] = {
    (PHASE_A_TASK_SCHEMA, PHASE_A_TASK_TYPE): (PHASE_A_VALIDATOR_REL, PHASE_A_REPORT_NAME),
    (PHASE_B_TASK_SCHEMA, PHASE_B_TASK_TYPE): (PHASE_B_VALIDATOR_REL, PHASE_B_REPORT_NAME),
}


@dataclass(frozen=True, slots=True)
class StrategyPackageOutcome:
    task_id: str
    status: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatorResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    missing_script: bool
    error: str | None = None


class TaskJsonError(ValueError):
    """Stable failure raised while validating ``processing/<task_id>/task/task.json``.

    The ``status`` attribute is the package-level outcome status code so that
    callers (e.g. ``process_once``) can attach the correct evidence files
    without re-deriving it from the message text.  Subclasses ``ValueError``
    so existing callers that catch ``ValueError`` continue to work.
    """

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


ValidatorRunner = Callable[[list[str], Path, float], ValidatorResult]


def _default_runner(args: list[str], cwd: Path, timeout: float) -> ValidatorResult:
    script = Path(args[1])
    if not script.exists() or script.is_symlink() or not script.is_file():
        return ValidatorResult(
            returncode=-1,
            stdout="",
            stderr="",
            timed_out=False,
            missing_script=True,
            error=f"validator script not found: {script}",
        )
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else ""
        )
        stderr = exc.stderr if isinstance(exc.stderr, str) else (
            exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else ""
        )
        return ValidatorResult(
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            missing_script=False,
            error=f"validator timeout after {timeout}s",
        )
    except Exception as exc:
        return ValidatorResult(
            returncode=-1,
            stdout="",
            stderr="",
            timed_out=False,
            missing_script=False,
            error=f"validator runner exception: {exc!r}",
        )
    return ValidatorResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        timed_out=False,
        missing_script=False,
    )


class StrategyCombinedArchive:
    """Claim and archive paired strategy ``task``+``result`` packages.

    Each task produces two ``.ready`` directories that must arrive together:

    * ``inbox/<task_id>.ready`` -- the task description.
    * ``results/<task_id>.ready`` -- the producer's result payload.

    Both sources are moved into a single
    ``processing/<task_id>/{task,result}`` package, validated for identity,
    and handed to ``process_once``'s callback.  A successful handler call
    renames the whole processing package into ``archive/<task_id>``; a
    handler exception renames it into ``failed/<task_id>`` when safe.
    """

    def __init__(
        self,
        bridge_root: str | Path,
        *,
        repository_root: str | Path | None = None,
        phase_a_validator: str | Path | None = None,
        phase_b_validator: str | Path | None = None,
        runner: ValidatorRunner | None = None,
        timeout: float = DEFAULT_VALIDATOR_TIMEOUT,
        evidence_max_bytes: int = DEFAULT_EVIDENCE_MAX_BYTES,
    ) -> None:
        self.bridge_root = Path(bridge_root).resolve()
        self.root = self.bridge_root / "workbuddy" / "strategy"
        self.inbox = self.root / "inbox"
        self.processing = self.root / "processing"
        self.results = self.root / "results"
        self.archive = self.root / "archive"
        self.failed = self.root / "failed"
        self._ensure_directories()

        self.repository_root = (
            Path(repository_root).resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[5]
        )
        self.phase_a_validator = (
            Path(phase_a_validator).resolve()
            if phase_a_validator is not None
            else self.repository_root / PHASE_A_VALIDATOR_REL
        )
        self.phase_b_validator = (
            Path(phase_b_validator).resolve()
            if phase_b_validator is not None
            else self.repository_root / PHASE_B_VALIDATOR_REL
        )
        self.runner: ValidatorRunner = runner or _default_runner
        self.timeout = timeout
        self.evidence_max_bytes = evidence_max_bytes

    def _ensure_directories(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise ValueError(f"stage root is not a directory: {self.root}")
        for directory in (
            self.inbox,
            self.processing,
            self.results,
            self.archive,
            self.failed,
        ):
            if directory.exists() and (
                directory.is_symlink() or not directory.is_dir()
            ):
                raise ValueError(f"stage directory is not a directory: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _task_id(name: str) -> str | None:
        match = _READY_RE.fullmatch(name)
        if match is None:
            return None
        task_id = name[: -len(".ready")]
        return task_id if _TASK_RE.fullmatch(task_id) else None

    def discover_ready(self) -> tuple[Path, ...]:
        entries: list[Path] = []
        for entry in os.scandir(self.results):
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if self._task_id(entry.name) is not None:
                entries.append(Path(entry.path))
        return tuple(sorted(entries, key=lambda path: path.name))

    def _inbox_state(self, task_id: str) -> tuple[Path | None, str]:
        inbox_path = self.inbox / f"{task_id}.ready"
        if inbox_path.is_symlink():
            return None, "unsafe"
        if not inbox_path.is_dir():
            return None, "missing"
        return inbox_path, "ok"

    def _validated_result_source(self, ready_path: Path) -> tuple[Path, str]:
        if ready_path.is_symlink() or not ready_path.is_dir():
            raise ValueError(f"unsafe result source: {ready_path}")
        if ready_path.parent != self.results:
            raise ValueError(f"result source escapes results root: {ready_path}")
        task_id = self._task_id(ready_path.name)
        if task_id is None:
            raise ValueError(f"unsafe result package name: {ready_path.name}")
        return ready_path, task_id

    def _prepare_processing(self, task_id: str) -> Path:
        destination = self.processing / task_id
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        destination.mkdir(parents=True, exist_ok=False)
        return destination

    def _claim_pair(
        self, task_id: str, result_source: Path, inbox_source: Path
    ) -> Path:
        processing = self._prepare_processing(task_id)
        try:
            os.replace(result_source, processing / "result")
        except OSError:
            try:
                if processing.exists() and not any(processing.iterdir()):
                    processing.rmdir()
            except OSError:
                pass
            raise
        try:
            os.replace(inbox_source, processing / "task")
        except OSError:
            raise
        return processing

    def _validate_task_json(
        self, processing: Path, task_id: str
    ) -> dict[str, object]:
        task_dir = processing / "task"
        task_json = task_dir / "task.json"
        if task_json.is_symlink() or not task_json.is_file():
            raise TaskJsonError(
                "task_json_missing", "task.json missing or unsafe"
            )
        try:
            payload = json.loads(task_json.read_bytes())
        except json.JSONDecodeError as exc:
            raise TaskJsonError(
                "task_json_malformed",
                f"task.json is not valid JSON: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise TaskJsonError(
                "task_json_not_object", "task.json must be an object"
            )
        if payload.get("task_id") != task_id:
            raise TaskJsonError(
                "identity_mismatch",
                (
                    f"task.json task_id does not match path: "
                    f"{payload.get('task_id')!r} != {task_id!r}"
                ),
            )
        return payload

    def _finish(self, processing: Path, task_id: str, success: bool) -> Path:
        destination = (self.archive if success else self.failed) / task_id
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        os.replace(processing, destination)
        return destination

    def _resolve_route(
        self, schema_version: object, task_type: object
    ) -> tuple[Path, str] | None:
        if not isinstance(schema_version, str) or not isinstance(task_type, str):
            return None
        if (schema_version, task_type) not in _ROUTING:
            return None
        if schema_version == PHASE_A_TASK_SCHEMA:
            return self.phase_a_validator, PHASE_A_REPORT_NAME
        if schema_version == PHASE_B_TASK_SCHEMA:
            return self.phase_b_validator, PHASE_B_REPORT_NAME
        return None

    def _relative_validator_id(self, validator_path: Path) -> str:
        try:
            return validator_path.relative_to(self.repository_root).as_posix()
        except ValueError:
            return validator_path.name

    def _redact_paths(self, text: str) -> str:
        replacements = sorted(
            (
                (self.bridge_root, "<bridge-root>"),
                (self.repository_root, "<repository-root>"),
            ),
            key=lambda item: len(item[0].parts),
            reverse=True,
        )
        for root, label in replacements:
            text = re.sub(
                re.escape(root.as_posix()) + r"(?=$|[\\/])",
                label,
                text,
            )
        return text

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._redact_paths(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, dict):
            return {
                self._redact_paths(key) if isinstance(key, str) else key:
                self._redact_value(item)
                for key, item in value.items()
            }
        return value

    def _outcome(
        self, task_id: str, status: str, error: str | None = None
    ) -> StrategyPackageOutcome:
        return StrategyPackageOutcome(
            task_id,
            status,
            self._redact_paths(error) if error is not None else None,
        )

    def _bound_text(self, text: str) -> str:
        cap = self.evidence_max_bytes
        encoded = text.encode("utf-8")
        if len(encoded) <= cap:
            return text
        truncated = encoded[:cap].decode("utf-8", errors="replace")
        return truncated + f"\n[truncated to {cap} bytes]"

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _collect_files(self, processing: Path) -> list[Path]:
        files: list[Path] = []
        for subdir_name in ("task", "result"):
            base = processing / subdir_name
            if not base.is_dir() or base.is_symlink():
                continue
            for entry in sorted(base.rglob("*")):
                if entry.is_symlink() or not entry.is_file():
                    continue
                files.append(entry)
        return files

    def _archive_matches_sources(self, task_id: str) -> bool:
        """Return whether an archive manifest matches the two ready trees."""
        try:
            if _TASK_RE.fullmatch(task_id) is None:
                return False

            def _files(root: Path, prefix: str) -> dict[str, Path]:
                mode = os.lstat(root).st_mode
                if not stat.S_ISDIR(mode):
                    raise ValueError(f"unsafe tree root: {root}")
                found: dict[str, Path] = {}

                def _walk(directory: Path, relative: Path) -> None:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            entry_path = Path(entry.path)
                            entry_mode = os.lstat(entry.path).st_mode
                            if stat.S_ISLNK(entry_mode):
                                raise ValueError(f"unsafe tree symlink: {entry_path}")
                            child_relative = relative / entry.name
                            if stat.S_ISDIR(entry_mode):
                                _walk(entry_path, child_relative)
                            elif stat.S_ISREG(entry_mode):
                                found[f"{prefix}/{child_relative.as_posix()}"] = entry_path
                            else:
                                raise ValueError(
                                    f"unsafe tree non-regular entry: {entry_path}"
                                )

                _walk(root, Path())
                return found

            source_files = {
                **_files(self.inbox / f"{task_id}.ready", "task"),
                **_files(self.results / f"{task_id}.ready", "result"),
            }
            archive = self.archive / task_id
            archive_mode = os.lstat(archive).st_mode
            if not stat.S_ISDIR(archive_mode):
                return False
            manifest_path = archive / "manifest.json"
            manifest_mode = os.lstat(manifest_path).st_mode
            if not stat.S_ISREG(manifest_mode):
                return False
            manifest = json.loads(manifest_path.read_bytes())
            if not isinstance(manifest, dict):
                return False
            if (
                manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
                or manifest.get("task_id") != task_id
                or not isinstance(manifest.get("entries"), list)
            ):
                return False

            manifest_files: dict[str, tuple[int, str]] = {}
            for entry in manifest["entries"]:
                if not isinstance(entry, dict):
                    return False
                path = entry.get("path")
                size = entry.get("size")
                sha256 = entry.get("sha256")
                if (
                    not isinstance(path, str)
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                    or not isinstance(sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
                ):
                    return False
                relative = Path(path)
                if (
                    relative.is_absolute()
                    or relative.as_posix() != path
                    or path.split("/", 1)[0] not in {"task", "result"}
                    or len(relative.parts) < 2
                    or ".." in relative.parts
                ):
                    return False
                if path in manifest_files:
                    return False
                manifest_files[path] = (size, sha256)

            archive_files = {
                **_files(archive / "task", "task"),
                **_files(archive / "result", "result"),
            }
            if set(source_files) != set(manifest_files) or set(archive_files) != set(
                manifest_files
            ):
                return False
            for relative, (size, expected_hash) in manifest_files.items():
                source_path = source_files[relative]
                archive_path = archive_files[relative]
                if source_path.stat().st_size != size or archive_path.stat().st_size != size:
                    return False
                source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
                archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
                if source_hash != expected_hash or archive_hash != expected_hash:
                    return False
            return True
        except Exception:
            return False

    def _assert_package_safety(self, processing: Path) -> None:
        def _walk(root: Path) -> None:
            with os.scandir(root) as it:
                for entry in it:
                    try:
                        mode = os.lstat(entry.path).st_mode
                    except OSError as exc:
                        raise ValueError(
                            f"unsafe package entry: {entry.path} ({exc})"
                        ) from exc
                    if stat.S_ISLNK(mode):
                        raise ValueError(
                            f"unsafe package symlink: {entry.path}"
                        )
                    if stat.S_ISDIR(mode):
                        _walk(Path(entry.path))
                    elif not stat.S_ISREG(mode):
                        raise ValueError(
                            f"unsafe package non-regular entry: {entry.path}"
                        )

        for subdir_name in ("task", "result"):
            base = processing / subdir_name
            try:
                base_mode = os.lstat(base).st_mode
            except OSError as exc:
                raise ValueError(
                    f"unsafe package entry: {base} ({exc})"
                ) from exc
            if stat.S_ISLNK(base_mode):
                raise ValueError(f"unsafe package symlink: {base}")
            if not stat.S_ISDIR(base_mode):
                raise ValueError(
                    f"unsafe package entry is not a directory: {base}"
                )
            _walk(base)

    def _build_manifest(
        self,
        processing: Path,
        task_id: str,
        task_type: object,
        validator_id: str | None,
    ) -> dict[str, object]:
        entries: list[dict[str, object]] = []
        for path in self._collect_files(processing):
            rel = path.relative_to(processing).as_posix()
            entries.append(
                {
                    "path": rel,
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        entries.sort(key=lambda item: item["path"])
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": task_id,
            "task_type": task_type,
            "processed_at": self._now_iso(),
            "validator_identity": validator_id,
            "entries": entries,
        }

    def _build_validation_record(
        self,
        task_id: str,
        task_type: object,
        status: str,
        *,
        validator_exit_code: int | None,
        report_relpath: str | None,
        stdout_relpath: str | None,
        stderr_relpath: str | None,
        errors: list[dict[str, object]] | None = None,
        warnings: list[dict[str, object]] | None = None,
        reviews: list[dict[str, object]] | None = None,
        processing_outcome: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "authority": ARCHIVE_AUTHORITY,
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "validator_exit_code": validator_exit_code,
            "errors": self._redact_value(list(errors or [])),
            "warnings": self._redact_value(list(warnings or [])),
            "reviews": self._redact_value(list(reviews or [])),
            "validator_report": report_relpath,
            "validator_stdout": stdout_relpath,
            "validator_stderr": stderr_relpath,
            "processing_outcome": processing_outcome,
        }

    def _write_evidence_files(
        self,
        processing: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> tuple[str | None, str | None]:
        stdout_rel = "validator.stdout.txt"
        stderr_rel = "validator.stderr.txt"
        stdout_path: str | None = None
        stderr_path: str | None = None
        if stdout_text:
            (processing / stdout_rel).write_text(
                self._bound_text(self._redact_paths(stdout_text)), encoding="utf-8"
            )
            stdout_path = stdout_rel
        if stderr_text:
            (processing / stderr_rel).write_text(
                self._bound_text(self._redact_paths(stderr_text)), encoding="utf-8"
            )
            stderr_path = stderr_rel
        return stdout_path, stderr_path

    def _write_package_artifacts(
        self,
        processing: Path,
        manifest: dict[str, object],
        record: dict[str, object],
    ) -> None:
        (processing / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (processing / "validation-record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_task_json_failure(
        self,
        processing: Path,
        task_id: str,
        exc: TaskJsonError,
    ) -> StrategyPackageOutcome:
        status = exc.status
        error = str(exc)

        manifest = self._build_manifest(processing, task_id, None, None)
        record = self._build_validation_record(
            task_id=task_id,
            task_type=None,
            status=status,
            validator_exit_code=None,
            report_relpath=None,
            stdout_relpath=None,
            stderr_relpath=None,
            errors=[{"code": status, "message": error}],
            warnings=[],
            reviews=[],
            processing_outcome=None,
        )
        self._write_package_artifacts(processing, manifest, record)

        try:
            self._finish(processing, task_id, success=False)
        except FileExistsError as finish_exc:
            return self._outcome(
                task_id,
                "finish_conflict",
                f"{error}; finish failed: {finish_exc}",
            )
        return self._outcome(task_id, status, error)

    def _extract_findings(
        self, report_payload: dict[str, object] | None
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        errors: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        reviews: list[dict[str, object]] = []
        if not isinstance(report_payload, dict):
            return errors, warnings, reviews
        for key, target in (
            ("errors", errors),
            ("warnings", warnings),
            ("reviews", reviews),
        ):
            value = report_payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        target.append(item)
        return errors, warnings, reviews

    def _invoke_handler(
        self,
        processing: Path,
        task_id: str,
        handler: Callable[[Path], object],
    ) -> StrategyPackageOutcome:
        try:
            handler(processing)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            try:
                self._finish(processing, task_id, success=False)
            except FileExistsError as finish_exc:
                return self._outcome(
                    task_id, "failed", f"{error}; finish failed: {finish_exc}"
                )
            return self._outcome(task_id, "failed", error)
        try:
            self._finish(processing, task_id, success=True)
        except FileExistsError as exc:
            return self._outcome(task_id, "finish_conflict", str(exc))
        return self._outcome(task_id, "success", None)

    def _record_and_finish(
        self,
        processing: Path,
        task_id: str,
        task_type: object,
        *,
        status: str,
        error: str | None,
        success: bool,
        validator_id: str | None,
        validator_exit_code: int | None,
        stdout_text: str,
        stderr_text: str,
        report_payload: dict[str, object] | None,
        report_relpath: str | None,
    ) -> StrategyPackageOutcome:
        report_errors, report_warnings, report_reviews = self._extract_findings(report_payload)

        manifest = self._build_manifest(processing, task_id, task_type, validator_id)
        stdout_relpath, stderr_relpath = self._write_evidence_files(
            processing, stdout_text, stderr_text
        )

        errors: list[dict[str, object]] = list(report_errors)
        warnings: list[dict[str, object]] = list(report_warnings)
        reviews: list[dict[str, object]] = list(report_reviews)

        if status != "validated":
            if not errors and error:
                errors.append({"code": status, "message": error})
            elif not errors:
                errors.append({"code": status, "message": status})

        processing_outcome = {
            "task_id": task_id,
            "kind": "archive" if success else "failed",
        }

        record = self._build_validation_record(
            task_id=task_id,
            task_type=task_type,
            status=status,
            validator_exit_code=validator_exit_code,
            report_relpath=report_relpath,
            stdout_relpath=stdout_relpath,
            stderr_relpath=stderr_relpath,
            errors=errors,
            warnings=warnings,
            reviews=reviews,
            processing_outcome=processing_outcome,
        )

        self._write_package_artifacts(processing, manifest, record)

        try:
            self._finish(processing, task_id, success=success)
        except FileExistsError as exc:
            if error:
                return self._outcome(
                    task_id, "finish_conflict", f"{error}; finish failed: {exc}"
                )
            return self._outcome(task_id, "finish_conflict", str(exc))
        return self._outcome(task_id, status, error)

    def _validate_package(
        self,
        processing: Path,
        task_id: str,
        task_payload: dict[str, object],
    ) -> StrategyPackageOutcome:
        schema_version = task_payload.get("schema_version")
        task_type = task_payload.get("task_type")

        route = self._resolve_route(schema_version, task_type)
        if route is None:
            manifest = self._build_manifest(processing, task_id, task_type, None)
            record = self._build_validation_record(
                task_id=task_id,
                task_type=task_type,
                status="unknown_task_type",
                validator_exit_code=None,
                report_relpath=None,
                stdout_relpath=None,
                stderr_relpath=None,
                errors=[
                    {
                        "code": "unknown_task_type",
                        "message": (
                            "no validator route for "
                            f"schema_version={schema_version!r}, task_type={task_type!r}"
                        ),
                    }
                ],
                processing_outcome=None,
            )
            self._write_package_artifacts(processing, manifest, record)
            try:
                self._finish(processing, task_id, success=False)
            except FileExistsError as exc:
                return self._outcome(
                    task_id, "finish_conflict", f"unknown_task_type; finish failed: {exc}"
                )
            return self._outcome(task_id, "unknown_task_type", "no validator route")

        validator_script, report_name = route
        validator_id = self._relative_validator_id(validator_script)

        task_json_path = processing / "task" / "task.json"
        result_dir = processing / "result"
        args = [
            sys.executable,
            str(validator_script),
            "--task",
            str(task_json_path),
            "--result-dir",
            str(result_dir),
        ]

        validator_result = self.runner(args, processing, self.timeout)

        if validator_result.missing_script:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="validator_missing",
                error=validator_result.error or "validator script not found",
                success=False,
                validator_id=validator_id,
                validator_exit_code=-1,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=None,
            )

        if validator_result.timed_out:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="validator_timeout",
                error=validator_result.error or "validator timed out",
                success=False,
                validator_id=validator_id,
                validator_exit_code=-1,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=None,
            )

        if validator_result.error is not None:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="validator_error",
                error=validator_result.error,
                success=False,
                validator_id=validator_id,
                validator_exit_code=-1,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=None,
            )

        report_path = result_dir / report_name
        relocated_path = processing / report_name
        if (
            report_path.is_symlink()
            or not report_path.exists()
            or not report_path.is_file()
        ):
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="missing_report",
                error=f"validator did not produce {report_name}",
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=None,
            )

        try:
            os.replace(report_path, relocated_path)
        except OSError as exc:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="report_relocate_failed",
                error=str(exc),
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=None,
            )

        try:
            raw = relocated_path.read_text(encoding="utf-8")
        except OSError as exc:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="malformed_report",
                error=f"cannot read {report_name}: {exc}",
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=report_name,
            )

        try:
            report_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="malformed_report",
                error=f"cannot parse {report_name}: {exc.msg}",
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=report_name,
            )

        if not isinstance(report_payload, dict):
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status="malformed_report",
                error=f"{report_name} must be a JSON object",
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=None,
                report_relpath=report_name,
            )

        report_ready = report_payload.get("ready") is True
        if validator_result.returncode != 0 or not report_ready:
            status = "validation_failed"
            message: str | None = None
            if validator_result.returncode != 0:
                message = (
                    f"validator exit code {validator_result.returncode}"
                )
            elif not report_ready:
                message = "validator reported ready=false"
            return self._record_and_finish(
                processing,
                task_id,
                task_type,
                status=status,
                error=message,
                success=False,
                validator_id=validator_id,
                validator_exit_code=validator_result.returncode,
                stdout_text=validator_result.stdout,
                stderr_text=validator_result.stderr,
                report_payload=report_payload,
                report_relpath=report_name,
            )

        return self._record_and_finish(
            processing,
            task_id,
            task_type,
            status="validated",
            error=None,
            success=True,
            validator_id=validator_id,
            validator_exit_code=validator_result.returncode,
            stdout_text=validator_result.stdout,
            stderr_text=validator_result.stderr,
            report_payload=report_payload,
            report_relpath=report_name,
        )

    def process_once(
        self, handler: Callable[[Path], object] | None = None
    ) -> tuple[StrategyPackageOutcome, ...]:
        outcomes: list[StrategyPackageOutcome] = []
        for ready_path in self.discover_ready():
            try:
                result_source, task_id = self._validated_result_source(ready_path)
            except ValueError as exc:
                raw_id = self._task_id(ready_path.name) or ready_path.name
                outcomes.append(self._outcome(raw_id, "unsafe_input", str(exc)))
                continue

            inbox_source, inbox_state = self._inbox_state(task_id)
            if inbox_state == "missing":
                outcomes.append(self._outcome(task_id, "missing_task", None))
                continue
            if inbox_state == "unsafe":
                outcomes.append(
                    self._outcome(
                        task_id,
                        "unsafe_input",
                        "inbox source is not a safe directory",
                    )
                )
                continue
            assert inbox_source is not None

            # Slice C5b: short-circuit duplicate pairs when an existing archive
            # already covers the ready trees. Sources are preserved untouched
            # so the operator can reconcile them out-of-band; processing is
            # never created in any of the C5b branches.
            archive_path = self.archive / task_id
            if os.path.lexists(archive_path):
                try:
                    archive_mode = os.lstat(archive_path).st_mode
                except OSError as exc:
                    outcomes.append(
                        self._outcome(task_id, "archive_conflict", str(exc))
                    )
                    continue
                if stat.S_ISLNK(archive_mode) or not stat.S_ISDIR(archive_mode):
                    outcomes.append(
                        self._outcome(
                            task_id,
                            "archive_conflict",
                            f"archive path is not a directory: {archive_path}",
                        )
                    )
                    continue
                if self._archive_matches_sources(task_id):
                    outcomes.append(
                        self._outcome(task_id, "already_archived", None)
                    )
                else:
                    outcomes.append(
                        self._outcome(
                            task_id,
                            "archive_conflict",
                            "archive does not match sources",
                        )
                    )
                continue

            try:
                processing = self._claim_pair(task_id, result_source, inbox_source)
            except (FileExistsError, OSError) as exc:
                outcomes.append(self._outcome(task_id, "claim_conflict", str(exc)))
                continue

            try:
                self._assert_package_safety(processing)
            except ValueError as exc:
                outcomes.append(self._outcome(task_id, "unsafe_package", str(exc)))
                continue

            try:
                task_payload = self._validate_task_json(processing, task_id)
            except TaskJsonError as exc:
                outcomes.append(
                    self._record_task_json_failure(processing, task_id, exc)
                )
                continue

            if handler is not None:
                outcomes.append(self._invoke_handler(processing, task_id, handler))
            else:
                outcomes.append(self._validate_package(processing, task_id, task_payload))

        return tuple(outcomes)

    def recover_once(
        self, handler: Callable[[Path], object] | None = None
    ) -> tuple[StrategyPackageOutcome, ...]:
        """Resume ``processing/<task_id>`` residue left by an interrupted claim.

        Scans direct ``processing/<task_id>`` entries whose names pass the
        existing task-id validation, ignoring non-direct entries and
        symlink directories safely (no symlink is followed, no candidate
        outside ``processing`` is touched). A residue with both safe
        ``task/`` and ``result/`` directories resumes through the same
        task JSON validation and Phase A/B validator path as
        :meth:`process_once`. Unsafe residue -- missing ``task/`` or
        ``result/``, nested symlinks, non-regular entries, or malformed
        structure -- returns ``processing_residue`` and is left untouched.

        No evidence is written before the package is structurally safe.
        The package is never moved back to ``inbox``/``results`` and is
        never silently deleted.
        """
        outcomes: list[StrategyPackageOutcome] = []
        for entry in os.scandir(self.processing):
            try:
                entry_mode = os.lstat(entry.path).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(entry_mode):
                continue
            if not stat.S_ISDIR(entry_mode):
                continue
            if _TASK_RE.fullmatch(entry.name) is None:
                continue

            task_id = entry.name
            processing = Path(entry.path)

            try:
                self._assert_package_safety(processing)
            except ValueError as exc:
                outcomes.append(
                    self._outcome(task_id, "processing_residue", str(exc))
                )
                continue

            try:
                task_payload = self._validate_task_json(processing, task_id)
            except TaskJsonError as exc:
                outcomes.append(
                    self._record_task_json_failure(processing, task_id, exc)
                )
                continue

            if handler is not None:
                outcomes.append(self._invoke_handler(processing, task_id, handler))
            else:
                outcomes.append(self._validate_package(processing, task_id, task_payload))

        return tuple(outcomes)


__all__ = ["StrategyCombinedArchive", "StrategyPackageOutcome"]
