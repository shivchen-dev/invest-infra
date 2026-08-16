#!/usr/bin/env python3
"""Stdlib-only preflight CLI for Phase B strategy-proposal deliveries.

Usage: python3 scripts/validate_strategy_proposal.py --task PATH --result-dir DIR

Writes ``proposal-preflight-report.json`` inside ``--result-dir`` (no parent
creation). The report contains no host-absolute paths. Exit codes: 0 = no
envelope errors with a nonblocking proposal status
({ready_for_review, needs_review, blocked}) and a nonblocking producer
validation status ({passed, passed_with_review}); 1 = any envelope, path, or
binding error, or producer validation status failed; 2 = argparse usage error.

Producer states are claims only; none of these results means approved/active.
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

REPORT_SCHEMA = "strategy-proposal-preflight/1.0"
TASK_SCHEMA = "strategy-engineering-task/1.0"
PROPOSAL_SCHEMA = "strategy-proposal/1.0"
VALIDATION_SCHEMA = "strategy-proposal-validation/1.0"
CANONICAL_OUTPUTS = ("strategy.json", "strategy.md", "validation.json")
BINDING_NAMES = frozenset({"strategy.md", "validation.json"})
VALID_PROPOSAL_STATUSES = frozenset({"ready_for_review", "needs_review", "blocked"})
VALID_VALIDATION_STATUSES = frozenset({"passed", "passed_with_review", "failed"})
EXCLUDED_FROM_UNEXPECTED = frozenset({"proposal-preflight-report.json"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LATER_STAGE = re.compile(
    r"^(?:strategy[-_]version.*|approval.*|audit.*|decision.*|automation.*|"
    r"activation.*|strategy[-_]run.*|run-.*|stage[-_]result.*|"
    r"candidate[-_]proposal.*|candidate[-_]entry.*)$",
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
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


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
        errors.append(_err(code, f"cannot read {path.name}: {exc.strerror or exc}", path.name))
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
        errors.append(_err(code, f"{label}.{field} must be a non-empty string", label))
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
    if expect_str(task_obj, "task_id", errors, code="task_task_id", label="task.json") is None:
        return None
    if expect_str(task_obj, "as_of", errors, code="task_as_of", label="task.json") is None:
        return None
    expected_stage = "strategy"
    if task_obj.get("stage") != expected_stage:
        msg = f"task.stage must be {expected_stage!r}, got {task_obj.get('stage')!r}"
        errors.append(_err("task_stage_value", msg, "task.json"))
        return None
    expected_task_type = "strategy_engineering"
    if task_obj.get("task_type") != expected_task_type:
        msg = f"task.task_type must be {expected_task_type!r}, got {task_obj.get('task_type')!r}"
        errors.append(_err("task_task_type_value", msg, "task.json"))
        return None
    src = task_obj.get("source_document")
    if not isinstance(src, dict):
        errors.append(_err("task_source_document", "task.source_document must be an object", "task.json"))  # noqa: E501
        return None
    if expect_str(src, "source_document_id", errors, code="task_source_document_source_document_id", label="task.source_document") is None:  # noqa: E501
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
    assess = task_obj.get("capability_assessment")
    if not isinstance(assess, dict):
        errors.append(_err("task_capability_assessment", "task.capability_assessment must be an object", "task.json"))  # noqa: E501
        return None
    if expect_str(assess, "assessment_id", errors, code="task_capability_assessment_assessment_id", label="task.capability_assessment") is None:  # noqa: E501
        return None
    if expect_str(assess, "task_id", errors, code="task_capability_assessment_task_id", label="task.capability_assessment") is None:  # noqa: E501
        return None
    if not is_lowercase_hex64(assess.get("artifact_sha256", "")):
        msg = "task.capability_assessment.artifact_sha256 must be lowercase 64-hex"
        errors.append(_err("task_capability_assessment_artifact_sha256_hex", msg, "task.capability_assessment"))  # noqa: E501
        return None
    required_outputs = task_obj.get("required_outputs")
    if not isinstance(required_outputs, list):
        errors.append(_err("task_required_outputs", "task.required_outputs must be a list", "task.json"))  # noqa: E501
        return None
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in required_outputs:
        if not is_safe_basename(item):
            errors.append(_err("task_required_outputs_basename", f"required output {item!r} must be a plain basename", "task.json"))  # noqa: E501
            return None
        if item in seen:
            errors.append(_err("task_required_outputs_duplicate", f"required output {item!r} listed twice", "task.json"))  # noqa: E501
            return None
        seen.add(item)
        cleaned.append(item)
    for canonical in CANONICAL_OUTPUTS:
        if canonical not in cleaned:
            msg = f"required_outputs must include {canonical!r}"
            errors.append(_err("task_required_outputs_missing_canonical", msg, "task.json"))
            return None
    return task_obj


def validate_proposal_envelope(proposal: object, *, task: dict, errors: list[dict]) -> tuple[dict | None, str | None]:  # noqa: E501
    if not isinstance(proposal, dict):
        errors.append(_err("proposal_shape", "proposal must be a JSON object", "strategy.json"))
        return None, None
    if proposal.get("schema_version") != PROPOSAL_SCHEMA:
        got = proposal.get("schema_version")
        msg = f"proposal.schema_version must be {PROPOSAL_SCHEMA!r}, got {got!r}"
        errors.append(_err("proposal_schema", msg, "strategy.json"))
        return None, None
    for field in ("proposal_id", "name", "purpose", "generated_at"):
        if expect_str(proposal, field, errors, code=f"proposal_{field}", label="proposal") is None:
            return None, None
    rev = proposal.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev <= 0:
        msg = "proposal.revision must be a positive integer"
        errors.append(_err("proposal_revision", msg, "strategy.json"))
        return None, None
    if proposal.get("task_id") != task.get("task_id"):
        msg = f"proposal.task_id ({proposal.get('task_id')!r}) must match task.task_id ({task.get('task_id')!r})"  # noqa: E501
        errors.append(_err("binding_proposal_task_id", msg, "strategy.json"))
        return None, None
    p_src = proposal.get("source_document")
    if not isinstance(p_src, dict):
        errors.append(_err("proposal_source_document", "proposal.source_document must be an object", "strategy.json"))  # noqa: E501
        return None, None
    t_src = task["source_document"]
    for key in ("source_document_id", "revision", "content_sha256"):
        if p_src.get(key) != t_src.get(key):
            msg = (
                f"proposal.source_document.{key} ({p_src.get(key)!r}) "
                f"must match task.source_document.{key} ({t_src.get(key)!r})"
            )
            errors.append(_err(f"binding_proposal_source_{key}", msg, "strategy.json"))
            return None, None
    p_assess = proposal.get("capability_assessment")
    if not isinstance(p_assess, dict):
        errors.append(_err("proposal_capability_assessment", "proposal.capability_assessment must be an object", "strategy.json"))  # noqa: E501
        return None, None
    t_assess = task["capability_assessment"]
    for key in ("assessment_id", "task_id", "artifact_sha256"):
        if p_assess.get(key) != t_assess.get(key):
            msg = (
                f"proposal.capability_assessment.{key} ({p_assess.get(key)!r}) "
                f"must match task.capability_assessment.{key} ({t_assess.get(key)!r})"
            )
            errors.append(_err(f"binding_proposal_assessment_{key}", msg, "strategy.json"))
            return None, None
    status = proposal.get("status")
    if status not in VALID_PROPOSAL_STATUSES:
        msg = f"proposal.status must be one of {sorted(VALID_PROPOSAL_STATUSES)}, got {status!r}"
        errors.append(_err("proposal_status", msg, "strategy.json"))
        return None, None
    if not isinstance(proposal.get("definition"), dict):
        errors.append(_err("proposal_definition", "proposal.definition must be an object", "strategy.json"))  # noqa: E501
        return None, None
    if not isinstance(proposal.get("artifacts"), list):
        errors.append(_err("proposal_artifacts", "proposal.artifacts must be a list", "strategy.json"))  # noqa: E501
        return None, None
    return proposal, str(status)


def validate_validation_envelope(
    validation: object, *, task_id: str, proposal_id: str, proposal_revision: int,
    errors: list[dict],
) -> tuple[dict | None, str | None]:
    if not isinstance(validation, dict):
        errors.append(_err("validation_shape", "validation must be a JSON object", "validation.json"))  # noqa: E501
        return None, None
    if validation.get("schema_version") != VALIDATION_SCHEMA:
        got = validation.get("schema_version")
        msg = f"validation.schema_version must be {VALIDATION_SCHEMA!r}, got {got!r}"
        errors.append(_err("validation_schema", msg, "validation.json"))
        return None, None
    if expect_str(validation, "validation_id", errors, code="validation_validation_id", label="validation") is None:  # noqa: E501
        return None, None
    if expect_str(validation, "validated_at", errors, code="validation_validated_at", label="validation") is None:  # noqa: E501
        return None, None
    if validation.get("task_id") != task_id:
        msg = f"validation.task_id ({validation.get('task_id')!r}) must match task.task_id ({task_id!r})"  # noqa: E501
        errors.append(_err("binding_validation_task_id", msg, "validation.json"))
        return None, None
    if validation.get("proposal_id") != proposal_id:
        msg = f"validation.proposal_id ({validation.get('proposal_id')!r}) must match proposal.proposal_id ({proposal_id!r})"  # noqa: E501
        errors.append(_err("binding_validation_proposal_id", msg, "validation.json"))
        return None, None
    if validation.get("proposal_revision") != proposal_revision:
        msg = f"validation.proposal_revision ({validation.get('proposal_revision')!r}) must match proposal.revision ({proposal_revision!r})"  # noqa: E501
        errors.append(_err("binding_validation_proposal_revision", msg, "validation.json"))
        return None, None
    status = validation.get("status")
    if status not in VALID_VALIDATION_STATUSES:
        msg = f"validation.status must be one of {sorted(VALID_VALIDATION_STATUSES)}, got {status!r}"  # noqa: E501
        errors.append(_err("validation_status", msg, "validation.json"))
        return None, None
    for field in ("checks", "warnings", "reviews", "errors"):
        if not isinstance(validation.get(field), list):
            msg = f"validation.{field} must be a list"
            errors.append(_err(f"validation_{field}", msg, "validation.json"))
            return None, None
    return validation, str(status)


def copy_validation_findings(validation: object, *, errors: list[dict], warnings: list[dict], reviews: list[dict]) -> None:  # noqa: E501
    if not isinstance(validation, dict):
        return
    if validation.get("status") == "failed":
        errors.append(_err("validation_status_failed", "validation status is failed", "validation.json"))  # noqa: E501
    for message in validation.get("errors") or ():
        if isinstance(message, str):
            errors.append(_err("validation_finding_error", message, "validation.json"))
    for message in validation.get("warnings") or ():
        if isinstance(message, str):
            warnings.append(_err("validation_finding_warning", message, "validation.json"))
    for message in validation.get("reviews") or ():
        if isinstance(message, str):
            reviews.append(_err("validation_finding_review", message, "validation.json"))


def check_artifact_bindings(
    artifacts: object, *, file_hashes: dict[str, str], bindings: list[dict], errors: list[dict],
) -> None:
    if not isinstance(artifacts, list):
        errors.append(_err("proposal_artifacts_shape", "proposal.artifacts must be a list", "strategy.json"))  # noqa: E501
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
            errors.append(_err("binding_missing", f"artifacts must contain a binding for {name!r}", "strategy.json"))  # noqa: E501
            continue
        if len(entries) > 1:
            errors.append(_err("binding_duplicate", f"artifacts contains multiple bindings for {name!r}", "strategy.json"))  # noqa: E501
            continue
        declared = entries[0].get("sha256")
        if not is_lowercase_hex64(declared):
            errors.append(_err("binding_hash_format", f"{name} sha256 must be lowercase 64-hex, got {declared!r}", name))  # noqa: E501
            continue
        actual = file_hashes.get(name)
        if actual is None:
            errors.append(_err("binding_hash", f"required artifact {name!r} is missing for binding check", name))  # noqa: E501
            continue
        if actual != declared:
            errors.append(_err("binding_hash_mismatch", f"{name} sha256 mismatch: declared {declared}, actual {actual}", name))  # noqa: E501
            continue
        bindings.append({"name": name, "sha256": actual})


def scan_unexpected_files(result_dir: Path) -> list[str]:
    unexpected: list[str] = []
    for _root, dirs, files in os.walk(result_dir):
        for name in sorted(set(dirs) | set(files)):
            if name.startswith(".") or name in EXCLUDED_FROM_UNEXPECTED:
                continue
            if _LATER_STAGE.match(name):
                unexpected.append(name)
    return unexpected


def ingest_required_outputs(
    result_dir: Path, task: dict, *, errors: list[dict], file_hashes: dict[str, str],
) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for name in task["required_outputs"]:
        path = result_dir / name
        if not require_regular_file(path, prefix=f"output_{name}", errors=errors):
            continue
        if name == "strategy.json":
            parsed[name] = parse_json(path, code="proposal_parse", errors=errors)
        elif name == "validation.json":
            parsed[name] = parse_json(path, code="validation_parse", errors=errors)
        else:
            parsed[name] = None
        file_hashes[name] = sha256_lower(path)
    return parsed


def build_report(
    *, task_id: str | None, proposal_status: str | None, validation_status: str | None,
    ready: bool, exit_code: int, errors: list[dict], warnings: list[dict], reviews: list[dict],
    file_hashes: dict[str, str], bindings: list[dict], unexpected_files: list[str],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA,
        "task_id": task_id,
        "proposal_status": proposal_status,
        "validation_status": validation_status,
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
        prog="python3 scripts/validate_strategy_proposal.py",
        description="Preflight a Phase B strategy-proposal delivery.",
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
    proposal_status: str | None = None
    validation_status: str | None = None

    if require_regular_file(args.task, prefix="task_path", errors=errors):
        task_obj = parse_json(args.task, code="task_parse", errors=errors)
        task = validate_task(task_obj, errors) if task_obj is not None else None
    else:
        task = None

    result_dir_fd: int | None = None
    if not args.result_dir.exists():
        errors.append(_err("result_dir_missing", f"result directory not found: {args.result_dir.name}", args.result_dir.name))  # noqa: E501
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

    proposal: dict | None = None
    if task is not None and result_dir_ready:
        task_id = str(task["task_id"])
        parsed = ingest_required_outputs(args.result_dir, task, errors=errors, file_hashes=file_hashes)  # noqa: E501
        proposal_raw = parsed.get("strategy.json")
        validation_raw = parsed.get("validation.json")
        if isinstance(proposal_raw, dict):
            proposal, status = validate_proposal_envelope(proposal_raw, task=task, errors=errors)
            if proposal is not None:
                proposal_status = status
                check_artifact_bindings(proposal.get("artifacts"), file_hashes=file_hashes, bindings=bindings, errors=errors)  # noqa: E501
        if isinstance(proposal, dict) and isinstance(validation_raw, dict):
            validation, vstatus = validate_validation_envelope(
                validation_raw, task_id=task_id,
                proposal_id=str(proposal["proposal_id"]), proposal_revision=proposal["revision"],
                errors=errors,
            )
            if validation is not None:
                validation_status = vstatus
                copy_validation_findings(validation, errors=errors, warnings=warnings, reviews=reviews)  # noqa: E501
        unexpected = scan_unexpected_files(args.result_dir)
        if unexpected:
            unexpected_files = unexpected
            for filename in unexpected:
                msg = f"{filename!r} looks like a later-stage authority/activation artifact and must not appear in a Phase B delivery"  # noqa: E501
                errors.append(_err("unexpected_file", msg, filename))

    ready = not errors
    exit_code = 0 if ready else 1
    report = build_report(
        task_id=task_id, proposal_status=proposal_status, validation_status=validation_status,
        ready=ready, exit_code=exit_code, errors=errors, warnings=warnings, reviews=reviews,
        file_hashes=file_hashes, bindings=bindings, unexpected_files=unexpected_files,
    )
    if result_dir_ready:
        try:
            _write_report(result_dir_fd, "proposal-preflight-report.json", report)
        except OSError:
            report["errors"].append(_err(
                "report_write_failed",
                "proposal-preflight-report.json could not be written safely",
                "proposal-preflight-report.json",
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
