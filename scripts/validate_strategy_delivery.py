#!/usr/bin/env python3
"""Stdlib-only preflight CLI for Phase A capability-assessment deliveries.

Usage: python3 scripts/validate_strategy_delivery.py --task PATH --result-dir DIR

Writes ``validation-report.json`` inside result-dir (no parent creation). Reports
contain no host-absolute paths. Exit codes: 0 = no envelope errors (any
assessment status), 1 = validation error or missing result-dir, 2 = usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

REPORT_SCHEMA = "strategy-capability-preflight/1.0"
TASK_SCHEMA = "strategy-capability-assessment-task/1.0"
ASSESSMENT_SCHEMA = "strategy-capability-assessment/1.0"
PROBES_SCHEMA = "strategy-capability-probes/1.0"
CANONICAL_OUTPUTS = (
    "capability-assessment.json",
    "capability-assessment.md",
    "capability-probes.json",
)
BINDING_NAMES = frozenset({"capability-assessment.md", "capability-probes.json"})
VALID_STATUSES = frozenset({"ready", "ready_with_degradation", "needs_review", "blocked"})
EXCLUDED_FROM_UNEXPECTED = frozenset({"validation-report.json"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LATER_STAGE = re.compile(
    r"^(?:strategy\.(?:json|md)|validation\.json|change-proposal\.json|"
    r"strategy[-_]version.*|strategy[-_]proposal.*|automation.*|activation.*|"
    r"strategy[-_]run.*|stage[-_]result.*|candidate[-_]proposal.*|candidate[-_]entry.*)$",
    re.IGNORECASE,
)


def _err(code: str, message: str, path: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"code": code, "message": message}
    if path is not None:
        entry["path"] = path
    return entry


def _open_result_dir(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise NotADirectoryError(path)
    return fd


def _write_report(dir_fd: int, name: str, report: dict[str, object]) -> None:
    temporary = f".{name}.{secrets.token_hex(16)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(temporary, flags, 0o666, dir_fd=dir_fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            stream.write(json.dumps(report, ensure_ascii=False, indent=2))
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        if fd is not None:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)


def is_safe_basename(name: object) -> bool:
    return (
        isinstance(name, str)
        and name != ""
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
    )


def is_lowercase_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def sha256_lower(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_regular_file(path: Path, *, prefix: str, errors: list[dict]) -> bool:
    if not path.exists():
        errors.append(_err(f"{prefix}_missing", f"{path.name} not found", path.name))
        return False
    if path.is_symlink():
        errors.append(_err(f"{prefix}_symlink", f"{path.name} must not be a symlink", path.name))
        return False
    if not path.is_file():
        errors.append(_err(f"{prefix}_not_file", f"{path.name} is not a regular file", path.name))
        return False
    return True


def parse_json(path: Path, *, code: str, errors: list[dict]):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read {path.name}: {exc.strerror or exc}"
        errors.append(_err(code, msg, path.name))
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"invalid JSON in {path.name}: {exc.msg} (line {exc.lineno}, col {exc.colno})"
        errors.append(_err(code, msg, path.name))
        return None


def expect_str(obj: dict, field: str, errors: list[dict], *, code: str, label: str) -> str | None:
    value = obj.get(field)
    if not isinstance(value, str) or not value:
        msg = f"{label}.{field} must be a non-empty string"
        errors.append(_err(code, msg, label))
        return None
    return value


def validate_task(task_obj: object, errors: list[dict]) -> dict | None:
    if not isinstance(task_obj, dict):
        errors.append(_err("task_shape", "task must be a JSON object", "task.json"))
        return None
    if task_obj.get("schema_version") != TASK_SCHEMA:
        got = task_obj.get("schema_version")
        msg = f"task.schema_version must be {TASK_SCHEMA!r}, got {got!r}"
        errors.append(_err("task_schema", msg, "task.json"))
        return None
    for field in ("task_id", "data_matrix_version", "as_of"):
        if expect_str(task_obj, field, errors, code=f"task_{field}", label="task.json") is None:
            return None
    expected_stage = "strategy"
    stage_value = task_obj.get("stage")
    if not isinstance(stage_value, str) or stage_value != expected_stage:
        msg = f"task.stage must be {expected_stage!r}, got {stage_value!r}"
        errors.append(_err("task_stage_value", msg, "task.json"))
        return None
    expected_task_type = "capability_assessment"
    task_type_value = task_obj.get("task_type")
    if not isinstance(task_type_value, str) or task_type_value != expected_task_type:
        msg = f"task.task_type must be {expected_task_type!r}, got {task_type_value!r}"
        errors.append(_err("task_task_type_value", msg, "task.json"))
        return None
    src = task_obj.get("source_document")
    if not isinstance(src, dict):
        msg = "task.source_document must be an object"
        errors.append(_err("task_source_document", msg, "task.json"))
        return None
    for key in ("source_document_id",):
        if expect_str(src, key, errors, code=f"task_source_document_{key}", label="task.source_document") is None:  # noqa: E501
            return None
    if not is_lowercase_hex64(src.get("content_sha256", "")):
        msg = "task.source_document.content_sha256 must be lowercase 64-hex"
        errors.append(_err("task_source_document_content_sha256_hex", msg, "task.source_document"))
        return None
    rev = src.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev <= 0:
        msg = "task.source_document.revision must be a positive integer"
        errors.append(_err("task_source_document_revision", msg, "task.source_document"))
        return None
    required_outputs = task_obj.get("required_outputs")
    if not isinstance(required_outputs, list):
        errors.append(_err("task_required_outputs", "task.required_outputs must be a list", "task.json"))  # noqa: E501
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in required_outputs:
        if not is_safe_basename(item):
            msg = f"required output {item!r} must be a plain basename"
            errors.append(_err("task_required_outputs_basename", msg, "task.json"))
            return None
        if item in seen:
            msg = f"required output {item!r} listed twice"
            errors.append(_err("task_required_outputs_duplicate", msg, "task.json"))
            return None
        seen.add(item)
        cleaned.append(item)
    for canonical in CANONICAL_OUTPUTS:
        if canonical not in cleaned:
            msg = f"required_outputs must include {canonical!r}"
            errors.append(_err("task_required_outputs_missing_canonical", msg, "task.json"))
            return None
    return task_obj


def validate_assessment_envelope(assessment: object, *, task: dict, errors: list[dict]) -> tuple[dict | None, str | None]:  # noqa: E501
    if not isinstance(assessment, dict):
        msg = "assessment must be a JSON object"
        errors.append(_err("assessment_shape", msg, "capability-assessment.json"))
        return None, None
    if assessment.get("schema_version") != ASSESSMENT_SCHEMA:
        got = assessment.get("schema_version")
        msg = f"assessment.schema_version must be {ASSESSMENT_SCHEMA!r}, got {got!r}"
        errors.append(_err("assessment_schema", msg, "capability-assessment.json"))
        return None, None
    aid = assessment.get("assessment_id")
    if not isinstance(aid, str) or not aid.strip():
        msg = "assessment.assessment_id must be a non-empty string"
        errors.append(_err("assessment_id", msg, "capability-assessment.json"))
        return None, None
    if not isinstance(assessment.get("capabilities"), list):
        msg = "assessment.capabilities must be a list"
        errors.append(_err("assessment_capabilities", msg, "capability-assessment.json"))
        return None, None
    if not isinstance(assessment.get("artifacts"), list):
        msg = "assessment.artifacts must be a list"
        errors.append(_err("assessment_artifacts", msg, "capability-assessment.json"))
        return None, None
    status = assessment.get("status")
    if status not in VALID_STATUSES:
        msg = f"assessment.status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
        errors.append(_err("assessment_status", msg, "capability-assessment.json"))
        return None, None
    for field in ("task_id", "data_matrix_version", "as_of"):
        if assessment.get(field) != task.get(field):
            actual = assessment.get(field)
            expected = task.get(field)
            msg = f"assessment.{field} ({actual!r}) must match task.{field} ({expected!r})"
            errors.append(_err(f"binding_{field}", msg, "capability-assessment.json"))
            return None, None
    a_src = assessment.get("source_document")
    t_src = task["source_document"]
    if not isinstance(a_src, dict):
        msg = "assessment.source_document must be an object"
        errors.append(_err("binding_source_document", msg, "capability-assessment.json"))
        return None, None
    for key, label in (
        ("source_document_id", "source_document_id"),
        ("revision", "revision"),
        ("content_sha256", "source_sha256"),
    ):
        if a_src.get(key) != t_src.get(key):
            actual = a_src.get(key)
            expected = t_src.get(key)
            msg = (
                f"assessment.source_document.{key} ({actual!r}) "
                f"must match task.source_document.{key} ({expected!r})"
            )
            errors.append(_err(f"binding_{label}", msg, "capability-assessment.json"))
            return None, None
    return assessment, str(status)


def validate_probes(probes: object, *, expected_task_id: str, errors: list[dict]) -> dict | None:
    if not isinstance(probes, dict):
        errors.append(_err("probes_shape", "probes must be a JSON object", "capability-probes.json"))  # noqa: E501
        return None
    if probes.get("schema_version") != PROBES_SCHEMA:
        got = probes.get("schema_version")
        msg = f"probes.schema_version must be {PROBES_SCHEMA!r}, got {got!r}"
        errors.append(_err("probes_schema", msg, "capability-probes.json"))
        return None
    if probes.get("task_id") != expected_task_id:
        actual = probes.get("task_id")
        msg = f"probes.task_id ({actual!r}) must match task.task_id ({expected_task_id!r})"
        errors.append(_err("binding_probes_task_id", msg, "capability-probes.json"))
        return None
    if not isinstance(probes.get("probes"), list):
        errors.append(_err("probes_list", "probes.probes must be a list", "capability-probes.json"))
        return None
    return probes


def copy_findings(findings: object, *, warnings: list[dict], reviews: list[dict]) -> None:
    if not isinstance(findings, dict):
        return
    for message in findings.get("warnings") or ():
        if isinstance(message, str):
            warnings.append(_err("assessment_finding_warning", message, "capability-assessment.json"))  # noqa: E501
    for message in findings.get("reviews") or ():
        if isinstance(message, str):
            reviews.append(_err("assessment_finding_review", message, "capability-assessment.json"))


def check_artifact_bindings(artifacts: object, *, file_hashes: dict[str, str], bindings: list[dict], errors: list[dict]) -> None:  # noqa: E501
    if not isinstance(artifacts, list):
        msg = "assessment.artifacts must be a list"
        errors.append(_err("assessment_artifacts_shape", msg, "capability-assessment.json"))
        return
    counts: dict[str, list] = {name: [] for name in BINDING_NAMES}
    for entry in artifacts:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or name not in BINDING_NAMES:
            continue
        counts[name].append(entry)
    for name in sorted(BINDING_NAMES):
        entries = counts[name]
        if not entries:
            msg = f"artifacts must contain a binding for {name!r}"
            errors.append(_err("binding_missing", msg, "capability-assessment.json"))
            continue
        if len(entries) > 1:
            msg = f"artifacts contains multiple bindings for {name!r}"
            errors.append(_err("binding_duplicate", msg, "capability-assessment.json"))
            continue
        declared = entries[0].get("sha256")
        if not is_lowercase_hex64(declared):
            msg = f"{name} sha256 must be lowercase 64-hex, got {declared!r}"
            errors.append(_err("binding_hash_format", msg, name))
            continue
        actual = file_hashes.get(name)
        if actual is None:
            msg = f"required artifact {name!r} is missing for binding check"
            errors.append(_err("binding_hash", msg, name))
            continue
        if actual != declared:
            msg = f"{name} sha256 mismatch: declared {declared}, actual {actual}"
            errors.append(_err("binding_hash_mismatch", msg, name))
            continue
        bindings.append({"name": name, "sha256": actual})


def scan_unexpected_files(result_dir: Path) -> list[str]:
    unexpected: list[str] = []
    for entry in sorted(result_dir.iterdir()):
        if entry.name.startswith(".") or entry.name in EXCLUDED_FROM_UNEXPECTED:
            continue
        if _LATER_STAGE.match(entry.name):
            unexpected.append(entry.name)
    return unexpected


def ingest_required_outputs(result_dir: Path, task: dict, *, errors: list[dict], file_hashes: dict[str, str]) -> dict:  # noqa: E501
    parsed: dict[str, object] = {}
    for name in task["required_outputs"]:
        path = result_dir / name
        if not require_regular_file(path, prefix=f"output_{name}", errors=errors):
            continue
        if name == "capability-assessment.json":
            parsed[name] = parse_json(path, code="assessment_parse", errors=errors)
        elif name == "capability-probes.json":
            parsed[name] = parse_json(path, code="probes_parse", errors=errors)
        else:
            parsed[name] = None
        file_hashes[name] = sha256_lower(path)
    return parsed


def build_report(
    *,
    task_id: str | None,
    assessment_status: str | None,
    ready: bool,
    exit_code: int,
    errors: list[dict],
    warnings: list[dict],
    reviews: list[dict],
    file_hashes: dict[str, str],
    bindings: list[dict],
    unexpected_files: list[str],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA,
        "task_id": task_id,
        "assessment_status": assessment_status,
        "ready": ready,
        "exit_code": exit_code,
        "errors": errors,
        "warnings": warnings,
        "reviews": reviews,
        "file_hashes": file_hashes,
        "bindings": sorted(bindings, key=lambda b: b["name"]),
        "unexpected_files": unexpected_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/validate_strategy_delivery.py",
        description="Preflight a Phase A capability-assessment delivery.",
    )
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--result-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    errors: list[dict] = []
    warnings: list[dict] = []
    reviews: list[dict] = []
    file_hashes: dict[str, str] = {}
    bindings: list[dict] = []
    unexpected_files: list[str] = []
    task_id: str | None = None
    assessment_status: str | None = None

    if require_regular_file(args.task, prefix="task_path", errors=errors):
        task_obj = parse_json(args.task, code="task_parse", errors=errors)
        task = validate_task(task_obj, errors) if task_obj is not None else None
    else:
        task = None

    result_dir_fd: int | None = None
    if not args.result_dir.exists():
        msg = f"result directory not found: {args.result_dir.name}"
        errors.append(_err("result_dir_missing", msg, args.result_dir.name))
    elif args.result_dir.is_symlink():
        errors.append(_err("result_dir_symlink", "result-dir must not be a symlink", args.result_dir.name))  # noqa: E501
    elif not args.result_dir.is_dir():
        errors.append(_err("result_dir_not_dir", "result-dir must be a directory", args.result_dir.name))  # noqa: E501
    else:
        try:
            result_dir_fd = _open_result_dir(args.result_dir)
        except OSError:
            errors.append(_err("result_dir_unsafe", "result-dir could not be opened safely", args.result_dir.name))  # noqa: E501

    result_dir_ready = result_dir_fd is not None

    if task is not None and result_dir_ready:
        task_id = str(task["task_id"])
        parsed = ingest_required_outputs(args.result_dir, task, errors=errors, file_hashes=file_hashes)  # noqa: E501
        assessment_raw = parsed.get("capability-assessment.json")
        probes_raw = parsed.get("capability-probes.json")

        if isinstance(assessment_raw, dict):
            assessment, status = validate_assessment_envelope(assessment_raw, task=task, errors=errors)  # noqa: E501
            if assessment is not None:
                assessment_status = status
                check_artifact_bindings(
                    assessment.get("artifacts"),
                    file_hashes=file_hashes,
                    bindings=bindings,
                    errors=errors,
                )
                copy_findings(assessment.get("findings"), warnings=warnings, reviews=reviews)
        if isinstance(probes_raw, dict):
            validate_probes(probes_raw, expected_task_id=task_id, errors=errors)

        unexpected = scan_unexpected_files(args.result_dir)
        if unexpected:
            unexpected_files = unexpected
            for filename in unexpected:
                msg = (
                    f"{filename!r} looks like a later-stage "
                    "authority/activation artifact and must not appear "
                    "in a Phase A delivery"
                )
                errors.append(_err("unexpected_file", msg, filename))

    ready = not errors
    exit_code = 0 if ready else 1
    report = build_report(
        task_id=task_id,
        assessment_status=assessment_status,
        ready=ready,
        exit_code=exit_code,
        errors=errors,
        warnings=warnings,
        reviews=reviews,
        file_hashes=file_hashes,
        bindings=bindings,
        unexpected_files=unexpected_files,
    )

    if result_dir_ready:
        try:
            _write_report(result_dir_fd, "validation-report.json", report)
        except OSError:
            report["errors"].append(_err(
                "report_write_failed",
                "validation-report.json could not be written safely",
                "validation-report.json",
            ))
            report["ready"] = False
            report["exit_code"] = exit_code = 1

    if result_dir_fd is not None:
        os.close(result_dir_fd)

    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
