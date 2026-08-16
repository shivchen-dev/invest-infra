from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO / "scripts" / "validate_strategy_delivery.py"
_REPORT_SCHEMA = "strategy-capability-preflight/1.0"
_TASK_ID = "strategy-capability-test-001"
_SOURCE_DOC_ID = "source-doc-test-001"
_DATA_MATRIX = "data-matrix-test-001"
_ASSESSMENT_ID = "assessment-test-001"
_AS_OF = "2026-08-15T10:00:00+08:00"
_SOURCE_SHA = "0" * 64
_REQUIRED_OUTPUTS = [
    "capability-assessment.json",
    "capability-assessment.md",
    "capability-probes.json",
]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(_REPO / "apps" / "pipeline" / "src")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src
    return env


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(_SCRIPT), *args], capture_output=True, text=True, check=False, env=_env())  # noqa: E501


def _sha256_lower(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply(payload: dict, overrides: dict) -> dict:
    for k, v in overrides.items():
        if k == "source":
            payload["source_document"].update(v)
        else:
            payload[k] = v
    return payload


def _task_payload(**overrides) -> dict:
    return _apply({
        "schema_version": "strategy-capability-assessment-task/1.0",
        "task_id": _TASK_ID,
        "stage": "strategy",
        "task_type": "capability_assessment",
        "source_document": {"source_document_id": _SOURCE_DOC_ID, "revision": 1, "content_sha256": _SOURCE_SHA},  # noqa: E501
        "data_matrix_version": _DATA_MATRIX,
        "as_of": _AS_OF,
        "required_outputs": list(_REQUIRED_OUTPUTS),
    }, overrides)


def _assessment_payload(**overrides) -> dict:
    return _apply({
        "schema_version": "strategy-capability-assessment/1.0",
        "assessment_id": _ASSESSMENT_ID,
        "task_id": _TASK_ID,
        "source_document": {"source_document_id": _SOURCE_DOC_ID, "revision": 1, "content_sha256": _SOURCE_SHA},  # noqa: E501
        "data_matrix_version": _DATA_MATRIX,
        "as_of": _AS_OF,
        "status": "ready",
        "capabilities": [],
        "findings": {"warnings": [], "reviews": [], "blockers": []},
        "artifacts": [],
    }, overrides)


def _build_minimal(tmp_path: Path, **overrides) -> dict:  # noqa: E501
    task_overrides = {"required_outputs": overrides.pop("required_outputs")} if "required_outputs" in overrides else {}  # noqa: E501
    probes_task_id = overrides.pop("probes_task_id", _TASK_ID)
    artifacts = overrides.pop("artifacts", None)
    task_path = tmp_path / "task.json"
    _write_json(task_path, _task_payload(**task_overrides))
    result_dir = tmp_path / "delivery"
    result_dir.mkdir()
    md_path = result_dir / "capability-assessment.md"
    md_path.write_text("# Capability Assessment\n", encoding="utf-8")
    probes_path = result_dir / "capability-probes.json"
    _write_json(probes_path, {"schema_version": "strategy-capability-probes/1.0", "task_id": probes_task_id, "assessed_at": _AS_OF, "probes": []})  # noqa: E501
    payload = _assessment_payload(**overrides)
    payload["artifacts"] = artifacts if artifacts is not None else [
        {"name": "capability-assessment.md", "sha256": _sha256_lower(md_path)},
        {"name": "capability-probes.json", "sha256": _sha256_lower(probes_path)},
    ]
    _write_json(result_dir / "capability-assessment.json", payload)
    return {"task": task_path, "result_dir": result_dir}


def _read_report(result_dir: Path) -> dict:
    return json.loads((result_dir / "validation-report.json").read_text(encoding="utf-8"))


def _codes(report: dict, key: str) -> list[str]:
    return [item.get("code") for item in report.get(key, []) if isinstance(item, dict)]


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_strategy_delivery", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_minimal_valid_delivery(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    report = _read_report(paths["result_dir"])
    assert report["schema_version"] == _REPORT_SCHEMA and report["task_id"] == _TASK_ID
    assert report["assessment_status"] == "ready" and report["ready"] is True
    assert report["exit_code"] == 0 and report["errors"] == [] and report["unexpected_files"] == []


def test_report_symlink_does_not_overwrite_external_file(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    (paths["result_dir"] / "validation-report.json").symlink_to(sentinel)

    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert _read_report(paths["result_dir"])["exit_code"] == 0
    assert not (paths["result_dir"] / "validation-report.json").is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"


def test_report_hardlink_is_replaced_without_overwriting_external_file(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")
    report_path = paths["result_dir"] / "validation-report.json"
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
    assert (moved / "validation-report.json").is_file()
    assert not (replacement / "validation-report.json").exists()


def test_argparse_missing_args_returns_exit_2() -> None:
    proc = _run()
    assert proc.returncode == 2, (proc.stdout, proc.stderr)


@pytest.mark.parametrize("status", ["ready", "ready_with_degradation", "needs_review", "blocked"])
def test_each_valid_status_is_nonblocking(tmp_path: Path, status: str) -> None:
    paths = _build_minimal(tmp_path, status=status)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0, (status, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("label", "corrupt"),
    [("task", "{ this is not valid json"), ("assessment", "{\"schema_version\": broken")],
)
def test_malformed_json_returns_exit_1(tmp_path: Path, label: str, corrupt: str) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["task"] if label == "task" else paths["result_dir"] / "capability-assessment.json"  # noqa: E501
    target.write_text(corrupt, encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (label, proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("file", "version"),
    [
        ("task.json", "strategy-capability-assessment-task/0.9"),
        ("capability-assessment.json", "strategy-capability-assessment/0.9"),
        ("capability-probes.json", "strategy-capability-probes/2.0"),
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


def test_missing_required_output_returns_exit_1(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    (paths["result_dir"] / "capability-probes.json").unlink()
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1


@pytest.mark.parametrize(
    ("assessment_id", "source_doc_id", "revision", "source_sha", "matrix", "as_of"),
    [
        ("", _SOURCE_DOC_ID, 1, _SOURCE_SHA, _DATA_MATRIX, _AS_OF),
        (_ASSESSMENT_ID, "different-source", 1, _SOURCE_SHA, _DATA_MATRIX, _AS_OF),
        (_ASSESSMENT_ID, _SOURCE_DOC_ID, 2, _SOURCE_SHA, _DATA_MATRIX, _AS_OF),
        (_ASSESSMENT_ID, _SOURCE_DOC_ID, 1, "f" * 64, _DATA_MATRIX, _AS_OF),
        (_ASSESSMENT_ID, _SOURCE_DOC_ID, 1, _SOURCE_SHA, "other-matrix", _AS_OF),
        (_ASSESSMENT_ID, _SOURCE_DOC_ID, 1, _SOURCE_SHA, _DATA_MATRIX, "2026-12-31T00:00:00+08:00"),
    ],
)
def test_assessment_envelope_mismatch(tmp_path: Path, assessment_id, source_doc_id, revision, source_sha, matrix, as_of) -> None:  # noqa: E501
    paths = _build_minimal(
        tmp_path,
        assessment_id=assessment_id,
        source={"source_document_id": source_doc_id, "revision": revision, "content_sha256": source_sha},  # noqa: E501
        data_matrix_version=matrix,
        as_of=as_of,
    )
    assert _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"])).returncode == 1  # noqa: E501


@pytest.mark.parametrize("status", ["approved", "Accepted", "READY", ""])
def test_assessment_status_outside_whitelist(tmp_path: Path, status: str) -> None:
    paths = _build_minimal(tmp_path, status=status)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1


def test_probes_task_id_must_match_task(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path, probes_task_id="mismatched")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    assert "binding_probes_task_id" in _codes(_read_report(paths["result_dir"]), "errors")


@pytest.mark.parametrize(
    "filename",
    ["strategy.json", "strategy.md", "validation.json", "change-proposal.json",
     "strategy-version-1.json", "strategy-proposal-001.json",
     "automation-definition.json", "activation-record.json",
     "strategy-run-1.json", "stage-result.json",
     "candidate-proposal.json", "candidate-entry.json"],
)
def test_later_stage_filename_rejected(tmp_path: Path, filename: str) -> None:
    paths = _build_minimal(tmp_path)
    (paths["result_dir"] / filename).write_text("{}", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (filename, proc.stdout, proc.stderr)
    assert filename in _read_report(paths["result_dir"])["unexpected_files"]


def test_harmless_file_not_flagged_and_report_excluded(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    (paths["result_dir"] / "README").write_text("notes", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0
    report = _read_report(paths["result_dir"])
    assert report["unexpected_files"] == []
    assert "validation-report.json" not in report["unexpected_files"]


def test_findings_warnings_and_reviews_copied(tmp_path: Path) -> None:
    warnings = ["warn one", "warn two"]
    reviews = ["rev A", "rev B"]
    paths = _build_minimal(tmp_path, findings={"warnings": warnings, "reviews": reviews, "blockers": []})  # noqa: E501
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0
    report = _read_report(paths["result_dir"])
    assert [w["message"] for w in report["warnings"]] == warnings
    assert [r["message"] for r in report["reviews"]] == reviews


def test_originals_unchanged_after_run(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    rd = paths["result_dir"]
    snapshots = {p: p.read_bytes() for p in (paths["task"], rd / "capability-assessment.md", rd / "capability-assessment.json", rd / "capability-probes.json")}  # noqa: E501
    proc = _run("--task", str(paths["task"]), "--result-dir", str(rd))
    assert proc.returncode == 0
    for p, content in snapshots.items():
        assert p.read_bytes() == content


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
    report = _read_report(paths["result_dir"])
    assert str(tmp_path) not in json.dumps(report)


def test_symlink_required_artifact_rejected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    real_target = tmp_path / "real-target.md"
    real_target.write_text("# real\n", encoding="utf-8")
    symlink = paths["result_dir"] / "capability-assessment.md"
    symlink.unlink()
    symlink.symlink_to(real_target)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1


@pytest.mark.parametrize("kind", ["task_is_directory", "task_is_symlink"])
def test_task_path_safety(tmp_path: Path, kind: str) -> None:
    paths = _build_minimal(tmp_path)
    if kind == "task_is_directory":
        target = str(paths["result_dir"])
    else:
        link = tmp_path / "task_link.json"
        link.symlink_to(paths["task"])
        target = str(link)
    proc = _run("--task", target, "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1


def test_report_records_file_hashes_and_bindings(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 0
    report = _read_report(paths["result_dir"])
    assert report["file_hashes"]["capability-assessment.md"] == _sha256_lower(paths["result_dir"] / "capability-assessment.md")  # noqa: E501
    assert report["file_hashes"]["capability-probes.json"] == _sha256_lower(paths["result_dir"] / "capability-probes.json")  # noqa: E501
    assert {b["name"] for b in report["bindings"]} >= {"capability-assessment.md", "capability-probes.json"}  # noqa: E501


@pytest.mark.parametrize("name", ["../foo.json", "subdir/file.json", "/etc/passwd", "..", "."])
def test_path_traversal_in_required_outputs_rejected(tmp_path: Path, name: str) -> None:
    paths = _build_minimal(tmp_path, required_outputs=_REQUIRED_OUTPUTS + [name])
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (name, proc.stdout, proc.stderr)


def test_missing_result_dir_is_not_created(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    missing = tmp_path / "nope"
    assert not missing.exists()
    proc = _run("--task", str(paths["task"]), "--result-dir", str(missing))
    assert proc.returncode == 1 and not missing.exists()
    assert "result_dir_missing" in json.loads(proc.stdout)["errors"][0]["code"]


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda artifacts: [a for a in artifacts if a["name"] != "capability-probes.json"],
            "binding_missing",
        ),
        (
            lambda artifacts: artifacts + [dict(artifacts[-1])],
            "binding_duplicate",
        ),
        (
            lambda artifacts: [{**a, "sha256": a["sha256"].upper()} if a["name"] == "capability-probes.json" else a for a in artifacts],  # noqa: E501
            "binding_hash",
        ),
    ],
)
def test_artifact_binding_failures(tmp_path: Path, mutator, expected_code: str) -> None:
    paths = _build_minimal(tmp_path)
    target = paths["result_dir"] / "capability-assessment.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["artifacts"] = mutator(payload["artifacts"])
    _write_json(target, payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (expected_code, proc.stdout, proc.stderr)
    assert any(expected_code in c for c in _codes(_read_report(paths["result_dir"]), "errors") if c)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "execution"),
        ("stage", "STRATEGY"),
        ("stage", ""),
        ("task_type", "scoring"),
        ("task_type", "CAPABILITY_ASSESSMENT"),
        ("task_type", ""),
    ],
)
def test_task_stage_or_type_must_match_exact_enum(tmp_path: Path, field: str, value: str) -> None:
    paths = _build_minimal(tmp_path)
    payload = json.loads(paths["task"].read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(paths["task"], payload)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (field, value, proc.stdout, proc.stderr)
    expected_code = f"task_{field}_value"
    assert expected_code in _codes(_read_report(paths["result_dir"]), "errors")


def test_result_dir_symlink_rejected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    link = tmp_path / "delivery_link"
    link.symlink_to(paths["result_dir"])
    proc = _run("--task", str(paths["task"]), "--result-dir", str(link))
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert any(e.get("code") == "result_dir_symlink" for e in payload["errors"])


def test_result_dir_regular_file_rejected(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    not_dir = tmp_path / "not_a_directory.txt"
    not_dir.write_text("not a dir", encoding="utf-8")
    proc = _run("--task", str(paths["task"]), "--result-dir", str(not_dir))
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert any(e.get("code") == "result_dir_not_dir" for e in payload["errors"])


@pytest.mark.parametrize("missing", _REQUIRED_OUTPUTS)
def test_required_outputs_missing_canonical(tmp_path: Path, missing: str) -> None:
    outputs = [n for n in _REQUIRED_OUTPUTS if n != missing]
    paths = _build_minimal(tmp_path, required_outputs=outputs)
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (missing, proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert any(e.get("code") == "task_required_outputs_missing_canonical" for e in payload["errors"])  # noqa: E501


def test_required_outputs_duplicate(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path, required_outputs=_REQUIRED_OUTPUTS + ["capability-assessment.json"])  # noqa: E501
    proc = _run("--task", str(paths["task"]), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert any(e.get("code") == "task_required_outputs_duplicate" for e in payload["errors"])


def test_nonexistent_task_writes_report_and_task_path_missing(tmp_path: Path) -> None:
    paths = _build_minimal(tmp_path)
    proc = _run("--task", str(tmp_path / "missing.json"), "--result-dir", str(paths["result_dir"]))
    assert proc.returncode == 1
    assert (paths["result_dir"] / "validation-report.json").exists()
    report = _read_report(paths["result_dir"])
    assert "task_path_missing" in _codes(report, "errors")
