"""Behavioral tests for scripts/validate_strategy_proposal.py Phase B preflight CLI."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO / "scripts" / "validate_strategy_proposal.py"
_REPORT_SCHEMA = "strategy-proposal-preflight/1.0"
_TASK_ID = "strategy-engineering-test-001"
_SOURCE_DOC_ID = "source-doc-test-001"
_ASSESSMENT_ID = "assessment-test-001"
_AS_OF = "2026-08-15T12:00:00+08:00"
_SOURCE_SHA = "0" * 64
_ASSESSMENT_SHA = "0" * 64
_PROPOSAL_ID = "strategy-proposal-test-001"
_VALIDATION_ID = "strategy-validation-test-001"
_PROPOSAL_REVISION = 1
_REQUIRED_OUTPUTS = ["strategy.json", "strategy.md", "validation.json"]

_SRC = {"source_document_id": _SOURCE_DOC_ID, "revision": 1, "content_sha256": _SOURCE_SHA}
_CAP = {"assessment_id": _ASSESSMENT_ID, "task_id": _TASK_ID, "artifact_sha256": _ASSESSMENT_SHA}
_TASK_TEMPLATE = {
    "schema_version": "strategy-engineering-task/1.0", "task_id": _TASK_ID, "stage": "strategy",
    "task_type": "strategy_engineering", "source_document": _SRC, "capability_assessment": _CAP,
    "as_of": _AS_OF, "required_outputs": list(_REQUIRED_OUTPUTS),
}
_PROPOSAL_TEMPLATE = {
    "schema_version": "strategy-proposal/1.0", "proposal_id": _PROPOSAL_ID, "revision": _PROPOSAL_REVISION,  # noqa: E501
    "task_id": _TASK_ID, "source_document": _SRC, "capability_assessment": _CAP,
    "generated_at": _AS_OF, "status": "ready_for_review",
    "name": "Example strategy proposal", "purpose": "Test purpose",
    "definition": {"stage_role": "example"}, "artifacts": [],
}
_VALIDATION_TEMPLATE = {
    "schema_version": "strategy-proposal-validation/1.0", "validation_id": _VALIDATION_ID,
    "task_id": _TASK_ID, "proposal_id": _PROPOSAL_ID, "proposal_revision": _PROPOSAL_REVISION,
    "validated_at": _AS_OF, "status": "passed",
    "checks": [], "warnings": [], "reviews": [], "errors": [],
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(_REPO / "apps" / "pipeline" / "src")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src
    return env


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(_SCRIPT), *args], capture_output=True, text=True, check=False, env=_env())  # noqa: E501


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply(template: dict, overrides: dict) -> dict:
    payload = copy.deepcopy(template)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(payload.get(k), dict):
            payload[k].update(v)
        else:
            payload[k] = v
    return payload


def _build_minimal(
    tmp_path: Path, *, proposal_overrides=None, validation_overrides=None,
    task_overrides=None, required_outputs=None, artifacts=None,
) -> dict:
    task_data = _apply(_TASK_TEMPLATE, task_overrides or {})
    if required_outputs is not None:
        task_data["required_outputs"] = list(required_outputs)
    task_path = tmp_path / "task.json"
    _write_json(task_path, task_data)
    result_dir = tmp_path / "delivery"
    result_dir.mkdir()
    strategy_md = result_dir / "strategy.md"
    strategy_md.write_text("# Strategy Proposal\n", encoding="utf-8")
    validation_path = result_dir / "validation.json"
    _write_json(validation_path, _apply(_VALIDATION_TEMPLATE, validation_overrides or {}))
    proposal_data = _apply(_PROPOSAL_TEMPLATE, proposal_overrides or {})
    if artifacts is not None:
        proposal_data["artifacts"] = artifacts
    elif "artifacts" not in (proposal_overrides or {}):
        proposal_data["artifacts"] = [
            {"name": "strategy.md", "sha256": _sha256(strategy_md)},
            {"name": "validation.json", "sha256": _sha256(validation_path)},
        ]
    _write_json(result_dir / "strategy.json", proposal_data)
    return {"task": task_path, "result_dir": result_dir}


def _read_report(result_dir: Path) -> dict:
    return json.loads((result_dir / "proposal-preflight-report.json").read_text(encoding="utf-8"))


def _codes(report: dict, key: str) -> list[str]:
    return [item.get("code") for item in report.get(key, []) if isinstance(item, dict)]


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_strategy_proposal", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_exists() -> None:
    assert _SCRIPT.exists(), f"missing script: {_SCRIPT}"


def test_minimal_valid_delivery(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    report = _read_report(paths["result_dir"])
    serialized = json.dumps(report)
    assert report["schema_version"] == _REPORT_SCHEMA and report["task_id"] == _TASK_ID
    assert report["proposal_status"] == "ready_for_review" and report["validation_status"] == "passed"  # noqa: E501
    assert report["ready"] is True and report["exit_code"] == 0
    assert report["errors"] == [] and report["unexpected_files"] == []
    assert "approved" not in serialized.lower() and "active" not in serialized.lower()


def test_report_symlink_does_not_overwrite_external_file(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    (paths["result_dir"] / "proposal-preflight-report.json").symlink_to(sentinel)

    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert _read_report(paths["result_dir"])["exit_code"] == 0
    assert not (paths["result_dir"] / "proposal-preflight-report.json").is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"


def test_report_hardlink_is_replaced_without_overwriting_external_file(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    report_path = paths["result_dir"] / "proposal-preflight-report.json"
    os.link(sentinel, report_path)

    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert _read_report(paths["result_dir"])["exit_code"] == 0
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"
    assert report_path.stat().st_ino != sentinel.stat().st_ino


def test_report_write_stays_with_opened_directory_if_path_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _build_minimal(tmp_path)
    moved = tmp_path / "opened-delivery"
    replacement = paths["result_dir"]
    module = _load_script()
    real_open = os.open

    def swap_after_open(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path) == replacement and flags & os.O_DIRECTORY:
            replacement.rename(moved)
            replacement.mkdir()
        return fd

    monkeypatch.setattr(module.os, "open", swap_after_open)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--task", str(paths["task"]), "--result-dir", str(replacement)])  # noqa: E501

    assert module.main() == 1
    assert (moved / "proposal-preflight-report.json").is_file()
    assert not (replacement / "proposal-preflight-report.json").exists()


def test_argparse_missing_args_returns_exit_2() -> None:
    proc = _run()
    assert proc.returncode == 2, (proc.stdout, proc.stderr)


@pytest.mark.parametrize("status", ["ready_for_review", "needs_review", "blocked"])
def test_proposal_status_whitelist_is_nonblocking(tmp_path: Path, status: str) -> None:
    paths = _build_minimal(tmp_path, proposal_overrides={"status": status})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (status, proc.stdout, proc.stderr)


@pytest.mark.parametrize("status", ["passed", "passed_with_review"])
def test_validation_status_passed_or_with_review_is_nonblocking(tmp_path: Path, status: str) -> None:  # noqa: E501
    paths = _build_minimal(tmp_path, validation_overrides={"status": status})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (status, proc.stdout, proc.stderr)


@pytest.mark.parametrize("label", ["task", "proposal", "validation"])
def test_malformed_json_returns_exit_1(tmp_path: Path, label: str) -> None:
    paths = _build_minimal(tmp_path)
    targets = {
        "task": paths["task"],
        "proposal": paths["result_dir"] / "strategy.json",
        "validation": paths["result_dir"] / "validation.json",
    }
    targets[label].write_text("{ not valid json", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (label, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("file", "version"),
    [
        ("task.json", "strategy-engineering-task/2.0"),
        ("strategy.json", "strategy-proposal/0.9"),
        ("validation.json", "strategy-proposal-validation/2.0"),
    ],
)
def test_schema_version_mismatch(tmp_path: Path, file: str, version: str) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["task"] if file == "task.json" else paths["result_dir"] / file
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = version
    _write_json(target, payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (file, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "execution"), ("stage", "STRATEGY"), ("stage", ""),
        ("task_type", "scoring"), ("task_type", "STRATEGY_ENGINEERING"), ("task_type", ""),
    ],
)
def test_task_stage_or_type_must_match_exact_enum(tmp_path: Path, field: str, value: str) -> None:
    paths = _build_minimal(tmp_path)
    payload = json.loads(paths["task"].read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(paths["task"], payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)
    assert f"task_{field}_value" in _codes(_read_report(paths["result_dir"]), "errors")


@pytest.mark.parametrize("name", ["../foo.json", "subdir/file.json", "/etc/passwd", "..", "."])
def test_required_output_path_traversal_rejected(tmp_path: Path, name: str) -> None:
    paths = _build_minimal(tmp_path, required_outputs=_REQUIRED_OUTPUTS + [name])
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (name, proc.stdout, proc.stderr)


def test_required_outputs_duplicate_rejected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path, required_outputs=_REQUIRED_OUTPUTS + ["strategy.json"])
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    assert "task_required_outputs_duplicate" in _codes(_read_report(paths["result_dir"]), "errors")


@pytest.mark.parametrize("missing", _REQUIRED_OUTPUTS)
def test_required_outputs_missing_canonical(tmp_path: Path, missing: str) -> None:
    paths = _build_minimal(tmp_path, required_outputs=[n for n in _REQUIRED_OUTPUTS if n != missing])  # noqa: E501
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (missing, proc.stdout, proc.stderr)
    assert "task_required_outputs_missing_canonical" in _codes(_read_report(paths["result_dir"]), "errors")  # noqa: E501


@pytest.mark.parametrize("kind", ["missing", "is_directory", "is_symlink"])
def test_task_path_safety(tmp_path: Path, kind: str) -> None:
    paths = _build_minimal(tmp_path)
    if kind == "missing":
        target = str(tmp_path / "missing.json")
    elif kind == "is_directory":
        target = str(paths["result_dir"])
    else:
        link = tmp_path / "task_link.json"
        link.symlink_to(paths["task"])
        target = str(link)
    proc = _run("--task", target, "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (kind, proc.stdout, proc.stderr)


@pytest.mark.parametrize("kind", ["missing", "symlink", "regular_file"])
def test_result_dir_safety(tmp_path: Path, kind: str) -> None:
    paths = _build_minimal(tmp_path)
    if kind == "missing":
        target = tmp_path / "nope"
    elif kind == "symlink":
        link = tmp_path / "delivery_link"
        link.symlink_to(paths["result_dir"])
        target = link
    else:
        target = tmp_path / "not_a_directory.txt"
        target.write_text("not a dir", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(target))
    assert proc.returncode == 1, (kind, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("kind", "name"),
    [("missing", n) for n in _REQUIRED_OUTPUTS] + [("symlink", n) for n in _REQUIRED_OUTPUTS],
)
def test_required_artifact_safety(tmp_path: Path, kind: str, name: str) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["result_dir"] / name
    if kind == "missing":
        target.unlink()
    else:
        real = tmp_path / f"real-{name}"
        real.write_text("# real\n", encoding="utf-8")
        target.unlink()
        target.symlink_to(real)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (kind, name, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "other-task"),
        ("source_document_id", "other-source"),
        ("revision", 2),
        ("content_sha256", "f" * 64),
        ("assessment_id", "other-assessment"),
        ("artifact_sha256", "e" * 64),
    ],
)
def test_proposal_to_task_binding_mismatch(tmp_path: Path, field: str, value) -> None:
    if field in {"source_document_id", "revision", "content_sha256"}:
        ov = {"source_document": {field: value}}
    elif field in {"assessment_id", "artifact_sha256"}:
        ov = {"capability_assessment": {field: value}}
    else:
        ov = {field: value}
    paths = _build_minimal(tmp_path, proposal_overrides=ov)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [("proposal_id", ""), ("name", ""), ("purpose", ""), ("generated_at", ""), ("revision", 0), ("revision", -1)],  # noqa: E501
)
def test_proposal_required_envelope_fields(tmp_path: Path, field: str, value) -> None:
    paths = _build_minimal(tmp_path, proposal_overrides={field: value})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)


@pytest.mark.parametrize("status", ["approved", "Ready_For_Review", "READY_FOR_REVIEW", ""])
def test_proposal_status_outside_whitelist(tmp_path: Path, status: str) -> None:
    paths = _build_minimal(tmp_path, proposal_overrides={"status": status})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (status, proc.stdout, proc.stderr)


@pytest.mark.parametrize("value", [None, [], "not-an-object", 123])
def test_proposal_definition_must_be_object(tmp_path: Path, value) -> None:
    paths = _build_minimal(tmp_path, proposal_overrides={"definition": value})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (value, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [("task_id", "other-task"), ("proposal_id", "other-proposal"), ("proposal_revision", 2)],
)
def test_validation_binding_mismatch(tmp_path: Path, field: str, value) -> None:
    paths = _build_minimal(tmp_path, validation_overrides={field: value})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)


@pytest.mark.parametrize(("field", "value"), [("validation_id", ""), ("validated_at", "")])
def test_validation_required_envelope_fields(tmp_path: Path, field: str, value: str) -> None:
    paths = _build_minimal(tmp_path, validation_overrides={field: value})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)


@pytest.mark.parametrize("status", ["Approved", "PASSED", "", "succeeded"])
def test_validation_status_outside_whitelist(tmp_path: Path, status: str) -> None:
    paths = _build_minimal(tmp_path, validation_overrides={"status": status})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (status, proc.stdout, proc.stderr)


@pytest.mark.parametrize("field", ["checks", "warnings", "reviews", "errors"])
def test_validation_lists_must_be_lists(tmp_path: Path, field: str) -> None:
    paths = _build_minimal(tmp_path, validation_overrides={field: "not-a-list"})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("label", "mutator", "expected_code"),
    [
        ("missing_validation", lambda arts: [a for a in arts if a["name"] != "validation.json"], "binding_missing"),  # noqa: E501
        ("duplicate_validation", lambda arts: arts + [dict(arts[-1])], "binding_duplicate"),
        ("bad_format", lambda arts: [{**a, "sha256": a["sha256"].upper()} if a["name"] == "strategy.md" else a for a in arts], "binding_hash_format"),  # noqa: E501
        ("mismatch", lambda arts: [{**a, "sha256": "f" * 64} if a["name"] == "strategy.md" else a for a in arts], "binding_hash_mismatch"),  # noqa: E501
    ],
)
def test_artifact_binding_failures(tmp_path: Path, label: str, mutator, expected_code: str) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["result_dir"] / "strategy.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["artifacts"] = mutator(payload["artifacts"])
    _write_json(target, payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (label, proc.stdout, proc.stderr)
    assert expected_code in _codes(_read_report(paths["result_dir"]), "errors")


def test_validation_status_failed_always_errors_with_empty_errors(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path, validation_overrides={"status": "failed", "errors": []})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    report = _read_report(paths["result_dir"])
    assert report["validation_status"] == "failed"
    assert "validation_status_failed" in _codes(report, "errors")


def test_validation_errors_copied_and_block_readiness(tmp_path: Path) -> None:
    error_msgs = ["rule mismatch", "missing reference"]
    paths = _build_minimal(tmp_path, validation_overrides={"errors": error_msgs})
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    report = _read_report(paths["result_dir"])
    assert [e["message"] for e in report["errors"] if e.get("code") == "validation_finding_error"] == error_msgs  # noqa: E501
    assert report["ready"] is False


def test_validation_warnings_and_reviews_copied_but_nonblocking(tmp_path: Path) -> None:
    warnings = ["warn one", "warn two"]
    reviews = ["rev A", "rev B"]
    paths = _build_minimal(tmp_path, validation_overrides={"warnings": warnings, "reviews": reviews})  # noqa: E501
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    report = _read_report(paths["result_dir"])
    assert [w["message"] for w in report["warnings"] if w.get("code") == "validation_finding_warning"] == warnings  # noqa: E501
    assert [r["message"] for r in report["reviews"] if r.get("code") == "validation_finding_review"] == reviews  # noqa: E501
    assert report["ready"] is True


@pytest.mark.parametrize(
    ("filename", "rejected"),
    [
        ("strategy-version-1.json", True), ("strategy_version_v2.json", True),
        ("approval-record.json", True), ("audit.json", True), ("decision-log.json", True),
        ("automation-definition.json", True), ("activation-record.json", True),
        ("strategy-run-1.json", True), ("run-1.json", True),
        ("stage-result.json", True), ("candidate-proposal.json", True), ("candidate-entry.json", True),  # noqa: E501
        ("README", False), ("notes.md", False), ("change-proposal.json", False),
    ],
)
def test_unexpected_file_policy(tmp_path: Path, filename: str, rejected: bool) -> None:
    paths = _build_minimal(tmp_path)
    (paths["result_dir"] / filename).write_text("{}", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    if rejected:
        assert proc.returncode == 1, (filename, proc.stdout, proc.stderr)
        assert filename in _read_report(paths["result_dir"])["unexpected_files"]
    else:
        assert proc.returncode == 0, (filename, proc.stdout, proc.stderr)
        report = _read_report(paths["result_dir"])
        assert filename not in report["unexpected_files"]
        assert "proposal-preflight-report.json" not in report["unexpected_files"]


def test_originals_unchanged_after_run(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    sources = (paths["task"], rd / "strategy.md", rd / "strategy.json", rd / "validation.json")
    snapshots = {p: p.read_bytes() for p in sources}
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 0
    for p, content in snapshots.items():
        assert p.read_bytes() == content, p


def test_idempotent_report_across_runs(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    first = _read_report(paths["result_dir"])
    _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert _read_report(paths["result_dir"]) == first


def test_report_contains_no_host_absolute_paths(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0
    serialized = json.dumps(_read_report(paths["result_dir"]))
    assert str(tmp_path) not in serialized
    assert "approved" not in serialized.lower()


def test_nonexistent_task_writes_report(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(tmp_path / "missing.json"), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    assert (paths["result_dir"] / "proposal-preflight-report.json").exists()
    assert "task_path_missing" in _codes(_read_report(paths["result_dir"]), "errors")


def test_missing_result_dir_is_not_created(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    missing = tmp_path / "nope"
    assert not missing.exists()
    proc = _run("--task", str(paths["task"]), "--result-dir", str(missing))
    assert proc.returncode == 1 and not missing.exists()
    assert any(e.get("code") == "result_dir_missing" for e in json.loads(proc.stdout)["errors"])


def test_report_records_file_hashes_and_bindings(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0
    report = _read_report(paths["result_dir"])
    assert report["file_hashes"]["strategy.md"] == _sha256(paths["result_dir"] / "strategy.md")
    assert report["file_hashes"]["validation.json"] == _sha256(paths["result_dir"] / "validation.json")  # noqa: E501
    assert {b["name"] for b in report["bindings"]} == {"strategy.md", "validation.json"}


def test_task_source_hash_rejects_trailing_newline(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    payload = json.loads(paths["task"].read_text(encoding="utf-8"))
    payload["source_document"]["content_sha256"] = _SOURCE_SHA + "\n"
    _write_json(paths["task"], payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "task_source_document_content_sha256_hex" in _codes(
        _read_report(paths["result_dir"]), "errors",
    )


def test_task_assessment_hash_rejects_trailing_newline(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    payload = json.loads(paths["task"].read_text(encoding="utf-8"))
    payload["capability_assessment"]["artifact_sha256"] = _ASSESSMENT_SHA + "\n"
    _write_json(paths["task"], payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "task_capability_assessment_artifact_sha256_hex" in _codes(
        _read_report(paths["result_dir"]), "errors",
    )


def test_proposal_artifact_binding_hash_rejects_trailing_newline(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["result_dir"] / "strategy.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    for entry in payload["artifacts"]:
        if entry["name"] == "strategy.md":
            entry["sha256"] = entry["sha256"] + "\n"
    _write_json(target, payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "binding_hash_format" in _codes(_read_report(paths["result_dir"]), "errors")


def test_nested_forbidden_file_detected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    sub = rd / "subdir"
    sub.mkdir()
    forbidden = "strategy-version-1.json"
    (sub / forbidden).write_text("{}", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    report = _read_report(rd)
    assert forbidden in report["unexpected_files"]
    assert "unexpected_file" in _codes(report, "errors")


def test_deeply_nested_forbidden_file_detected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    deep = rd / "a" / "b" / "c"
    deep.mkdir(parents=True)
    forbidden = "audit.json"
    (deep / forbidden).write_text("{}", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    report = _read_report(rd)
    assert forbidden in report["unexpected_files"]


def test_nested_directory_symlink_with_external_forbidden_not_flagged(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    nested = rd / "nested"
    nested.mkdir()
    external = tmp_path / "external_target"
    external.mkdir()
    forbidden = "strategy-version-1.json"
    (external / forbidden).write_text("{}", encoding="utf-8")
    (nested / "external_link").symlink_to(external)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    report = _read_report(rd)
    assert forbidden not in report["unexpected_files"]
    assert report["unexpected_files"] == []
    serialized = json.dumps(report)
    assert str(external) not in serialized
    assert str(tmp_path) not in serialized


def test_nested_harmless_extras_and_change_proposal_ignored(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    sub = rd / "notes"
    sub.mkdir()
    (sub / "README").write_text("notes", encoding="utf-8")
    (sub / "notes.md").write_text("notes", encoding="utf-8")
    (sub / "change-proposal.json").write_text("{}", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    report = _read_report(rd)
    assert report["unexpected_files"] == []
    assert "change-proposal.json" not in report["unexpected_files"]
