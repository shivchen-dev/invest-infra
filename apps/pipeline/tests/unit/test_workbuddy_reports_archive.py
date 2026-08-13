"""Behavioral tests for ``invest_pipeline.workbuddy_reports.archive``.

M1 first atomic slice — immutable archive + governance manifest + CLI
``import`` subcommand.  M2 second atomic slice —
``latest-accepted.json`` pointer updates on accepted runs, with the
sort key ``(trade_date, finished_at, workflow_run_id)`` and atomic
write semantics.

Fixture builders are duplicated from
``test_workbuddy_reports_validator.py`` to keep the two test files
self-contained.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PIPELINE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_SRC))


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        env["PYTHONPATH"] = f"{_PIPELINE_SRC}{os.pathsep}{pythonpath}"
    else:
        env["PYTHONPATH"] = str(_PIPELINE_SRC)
    return env


# ---------------------------------------------------------------------------
# Pure-Python API tests
# ---------------------------------------------------------------------------


def test_archive_run_accepted_writes_full_archive(tmp_path: Path) -> None:
    """Accepted triplet produces an archive with the three triplet copies
    plus ``governed-quality-report.json`` and ``manifest.json``."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 0, outcome
    assert outcome.governance_status == "accepted"
    assert outcome.workflow_run_id == "wr-2026-08-13-001"
    assert outcome.trade_date == "2026-08-13"
    assert outcome.is_idempotent is False
    assert outcome.is_conflict is False

    run_dir = Path(outcome.run_dir)
    assert run_dir.is_dir()
    filenames = sorted(p.name for p in run_dir.iterdir())
    assert filenames == sorted(
        [
            "governed-quality-report.json",
            "manifest.json",
            "quality_report.json",
            "report.md",
            "result.json",
        ]
    ), filenames

    assert outcome.manifest_path == str(run_dir / "manifest.json")
    assert outcome.governed_report_path == str(
        run_dir / "governed-quality-report.json"
    )


def test_archive_run_partial_still_archives(tmp_path: Path) -> None:
    """Partial triplets are archived (contract section 7) but the latest
    pointer is not written in this slice."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_partial_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 2, outcome
    assert outcome.governance_status == "partial"
    assert outcome.run_dir is not None

    run_dir = Path(outcome.run_dir)
    assert run_dir.is_dir()
    assert (run_dir / "governed-quality-report.json").is_file()
    assert (run_dir / "manifest.json").is_file()

    _assert_no_latest_pointer(root)


def test_archive_run_rejected_with_identity_still_archives(tmp_path: Path) -> None:
    """Rejected triplets with valid identity are still archived (contract
    section 7) but no latest pointer is written."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(
        src,
        result_overrides={
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.42,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "CCC",
                    "dimension_scores": {"growth": 0.2, "value": 0.1},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.16,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
        },
    )

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 3, outcome
    assert outcome.governance_status == "rejected"
    assert outcome.run_dir is not None
    assert (Path(outcome.run_dir) / "manifest.json").is_file()
    _assert_no_latest_pointer(root)


def test_archive_run_input_error_without_identity_skips_archive(
    tmp_path: Path,
) -> None:
    """When validation fails before identity is extractable (bad JSON),
    archive_run returns an input error outcome WITHOUT creating the run
    directory."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (src / "result.json").write_text("{not valid json", encoding="utf-8")
    (src / "report.md").write_text("# report\n", encoding="utf-8")
    (src / "quality_report.json").write_text("{}", encoding="utf-8")

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 4, outcome
    assert outcome.governance_status == "rejected"
    assert outcome.run_dir is None
    assert "input_error" in outcome.error_codes

    runs_root = root / "runs"
    if runs_root.is_dir():
        for trade_date_dir in runs_root.iterdir():
            assert not any(trade_date_dir.iterdir()), (
                f"unexpected contents under {trade_date_dir!r}"
            )


def test_archive_run_is_idempotent_when_source_unchanged(tmp_path: Path) -> None:
    """Re-importing the same source triplet returns a success outcome with
    ``is_idempotent=True`` and produces no second archive directory."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    first = archive_run(source_dir=str(src), governance_root=str(root))
    second = archive_run(source_dir=str(src), governance_root=str(root))

    assert first.exit_code == 0, first
    assert second.exit_code == 0, second
    assert second.is_idempotent is True
    assert second.run_dir == first.run_dir

    manifest_path = Path(first.run_dir) / "manifest.json"
    manifest_bytes_first = manifest_path.read_bytes()

    third = archive_run(source_dir=str(src), governance_root=str(root))
    manifest_bytes_third = manifest_path.read_bytes()

    assert third.exit_code == 0, third
    assert third.is_idempotent is True
    assert manifest_bytes_first == manifest_bytes_third


def test_archive_run_conflicts_when_source_changes(tmp_path: Path) -> None:
    """Changing source content for the same identity triggers a conflict
    (exit 5, ``is_conflict=True``) and the original archive stays byte-
    identical."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    first = archive_run(source_dir=str(src), governance_root=str(root))
    assert first.exit_code == 0, first
    manifest_bytes_before = (Path(first.run_dir) / "manifest.json").read_bytes()
    report_bytes_before = (
        Path(first.run_dir) / "governed-quality-report.json"
    ).read_bytes()

    _write_triplet(
        src,
        result_overrides={
            "applied_rules": [
                {"rule_id": "rule_growth_floor", "source_ref": "src_fundamental"},
            ],
        },
    )

    second = archive_run(source_dir=str(src), governance_root=str(root))

    assert second.exit_code == 5, second
    assert second.is_conflict is True
    assert "input_error" not in second.error_codes

    assert (Path(first.run_dir) / "manifest.json").read_bytes() == manifest_bytes_before
    assert (
        Path(first.run_dir) / "governed-quality-report.json"
    ).read_bytes() == report_bytes_before


def test_archive_run_manifest_hashes_recomputable(tmp_path: Path) -> None:
    """Each manifest entry's size/sha256 must match a recomputation from
    the actual on-disk bytes of the archived file."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    run_dir = Path(outcome.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert isinstance(manifest.get("entries"), list)
    assert manifest["entries"], "manifest has no entries"
    for entry in manifest["entries"]:
        path = run_dir / entry["path"]
        assert path.is_file(), f"manifest references missing file {entry['path']!r}"
        actual_bytes = path.read_bytes()
        assert entry["size_bytes"] == len(actual_bytes)
        assert entry["sha256"] == hashlib.sha256(actual_bytes).hexdigest()


def test_archive_run_manifest_excludes_itself(tmp_path: Path) -> None:
    """``manifest.json`` must not list itself in its own entries."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    manifest = json.loads(
        Path(outcome.run_dir, "manifest.json").read_text(encoding="utf-8")
    )
    paths = {entry["path"] for entry in manifest["entries"]}
    assert "manifest.json" not in paths


def test_archive_run_governed_report_has_required_fields(tmp_path: Path) -> None:
    """``governed-quality-report.json`` contains every contract-required
    field plus a parseable ``file_hashes`` block."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    report = json.loads(
        Path(outcome.run_dir, "governed-quality-report.json").read_text(
            encoding="utf-8"
        )
    )

    required = {
        "schema_version",
        "workflow_run_id",
        "trade_date",
        "producer_status",
        "governance_status",
        "validated_at",
        "errors",
        "warnings",
        "file_hashes",
    }
    missing = required - set(report)
    assert not missing, f"missing required fields: {missing}"

    assert report["schema_version"] == "invest-pipeline/workbuddy-governed-quality-report@1.0"
    assert report["workflow_run_id"] == "wr-2026-08-13-001"
    assert report["trade_date"] == "2026-08-13"
    assert report["producer_status"] == "succeeded"
    assert report["governance_status"] == "accepted"
    assert isinstance(report["errors"], list)
    assert isinstance(report["warnings"], list)
    assert isinstance(report["file_hashes"], dict)
    assert set(report["file_hashes"]) == {"result", "report", "quality_report"}


def test_archive_run_governed_report_is_byte_independent(tmp_path: Path) -> None:
    """The ``file_hashes`` block in ``governed-quality-report.json`` must
    be independently re-computable from the actual archived bytes of the
    triplet copies."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    run_dir = Path(outcome.run_dir)
    report = json.loads(
        (run_dir / "governed-quality-report.json").read_text(encoding="utf-8")
    )

    expected_paths = {
        "result": "result.json",
        "report": "report.md",
        "quality_report": "quality_report.json",
    }
    for role, basename in expected_paths.items():
        actual = (run_dir / basename).read_bytes()
        block = report["file_hashes"][role]
        assert block["size_bytes"] == len(actual)
        assert block["sha256"] == hashlib.sha256(actual).hexdigest()


def test_archive_run_leaves_no_tmp_dir_after_success(tmp_path: Path) -> None:
    """Successful import cleans up its staging directory."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome

    trade_date_dir = Path(root) / "runs" / outcome.trade_date
    tmp_dirs = [p for p in trade_date_dir.iterdir() if p.name.startswith(".tmp-")]
    assert tmp_dirs == [], f"unexpected tmp dirs: {tmp_dirs}"


def test_archive_run_leaves_no_tmp_dir_after_conflict(tmp_path: Path) -> None:
    """Conflict case also cleans up its staging directory."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    archive_run(source_dir=str(src), governance_root=str(root))

    _write_triplet(
        src,
        result_overrides={
            "applied_rules": [
                {"rule_id": "rule_growth_floor", "source_ref": "src_fundamental"},
            ],
        },
    )
    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 5, second

    trade_date_dir = Path(root) / "runs" / "2026-08-13"
    tmp_dirs = [p for p in trade_date_dir.iterdir() if p.name.startswith(".tmp-")]
    assert tmp_dirs == [], f"unexpected tmp dirs: {tmp_dirs}"


def test_archive_run_leaves_no_tmp_dir_after_idempotent(tmp_path: Path) -> None:
    """Idempotent re-import also cleans up its staging directory."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    archive_run(source_dir=str(src), governance_root=str(root))
    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 0 and second.is_idempotent, second

    trade_date_dir = Path(root) / "runs" / "2026-08-13"
    tmp_dirs = [p for p in trade_date_dir.iterdir() if p.name.startswith(".tmp-")]
    assert tmp_dirs == [], f"unexpected tmp dirs: {tmp_dirs}"


def test_archive_run_writes_latest_pointer_for_accepted(tmp_path: Path) -> None:
    """M2: accepted runs write ``latest-accepted.json`` under the governance
    root.  The pointer sits at the root (not inside ``runs/``) and the
    idempotency assertion is replaced with a freshness assertion."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome
    assert outcome.pointer_updated is True
    assert outcome.pointer_path == str(root / "latest-accepted.json")
    assert (root / "latest-accepted.json").is_file()


def test_archive_run_returns_input_error_when_no_triplet(tmp_path: Path) -> None:
    """A source dir that contains none of the canonical triplet files
    returns an input error outcome."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 4, outcome
    assert "input_error" in outcome.error_codes
    assert outcome.run_dir is None


def test_archive_run_rejects_invalid_source_path_type() -> None:
    """A non-PathLike source argument yields an input error outcome
    without raising."""
    from invest_pipeline.workbuddy_reports import archive_run

    outcome = archive_run(source_dir=12345, governance_root="/tmp")  # type: ignore[arg-type]
    assert outcome.exit_code == 4, outcome
    assert "input_error" in outcome.error_codes


def test_archive_run_conflicts_when_target_dir_exists_empty(tmp_path: Path) -> None:
    """Pre-existing empty target_dir (no manifest) must be treated as a
    conflict: ``os.replace`` is never attempted, exit 5 is returned, and
    the target_dir is left untouched."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    target_dir = root / "runs" / "2026-08-13" / "wr-2026-08-13-001"
    target_dir.mkdir(parents=True)
    assert target_dir.is_dir() and not any(target_dir.iterdir())

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 5, outcome
    assert outcome.is_conflict is True
    assert target_dir.is_dir()
    assert not any(target_dir.iterdir()), "target_dir must remain empty"


# ---------------------------------------------------------------------------
# Path-traversal regression: archive boundary defense-in-depth
#
# The full character-class matrix is exercised in
# ``test_workbuddy_reports_validator.py``; here we only need a small set
# that proves (a) the archive boundary fail-closes on an unsafe identity
# without delegating to the validator, and (b) the failure path never
# materialises a ``runs/<date>/<id>/`` directory, an escape target, or a
# stray ``.tmp-*`` staging area.
# ---------------------------------------------------------------------------


_UNSAFE_ARCHIVE_IDENTITIES = [
    pytest.param({"workflow_run_id": "wr/../escape"}, "escape", id="wr-slash-traversal"),
    pytest.param({"workflow_run_id": "wr\\..\\escape"}, "escape", id="wr-backslash"),
    pytest.param({"workflow_run_id": "/etc/passwd"}, "etc", id="wr-absolute-path"),
    pytest.param({"workflow_run_id": ".."}, None, id="wr-bare-dot-dot"),
    pytest.param({"workflow_run_id": ".hidden"}, None, id="wr-leading-dot"),
    pytest.param({"trade_date": "2026-02-30"}, None, id="trade-date-invalid-calendar"),
    pytest.param({"trade_date": "../escape"}, "escape", id="trade-date-traversal"),
]


@pytest.mark.parametrize("overrides,escape_target", _UNSAFE_ARCHIVE_IDENTITIES)
def test_archive_run_rejects_unsafe_identity_fail_closed_no_escape(
    tmp_path: Path,
    overrides: dict[str, str],
    escape_target: str | None,
) -> None:
    """Archive boundary defense-in-depth (M0 contract §7).

    An adversarial ``workflow_run_id`` or ``trade_date`` must yield an
    ``input_error`` outcome (exit 4), no ``run_dir``, no escape target
    under the governance root, and never an archive artefact.  The
    full format-class matrix lives in the validator test suite; this
    parameterised check exists only to prove the archive re-validates
    defensively and does not honour an invalid identity path."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src, result_overrides=overrides, quality_overrides=overrides)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))

    assert outcome.exit_code == 4, outcome
    assert "input_error" in outcome.error_codes, outcome
    assert outcome.run_dir is None
    if escape_target is not None:
        assert not (root / escape_target).exists(), (
            f"escape target {escape_target!r} must not exist"
        )


def test_archive_run_unsafe_identity_leaves_no_staging(tmp_path: Path) -> None:
    """An unsafe identity must leave no ``.tmp-*`` staging anywhere.

    The validation-then-reject path must short-circuit before the
    staging directory is created; this proves that adversarial inputs
    never leak a partial archive tree under ``runs/`` (or anywhere
    else under the governance root)."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(
        src,
        result_overrides={"workflow_run_id": "../escape"},
        quality_overrides={"workflow_run_id": "../escape"},
    )

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 4, outcome

    if (root / "runs").is_dir():
        for p in (root / "runs").rglob("*"):
            assert not p.name.startswith(".tmp-"), f"unexpected tmp: {p}"
    assert [p for p in root.iterdir() if p.name.startswith(".tmp-")] == []


# ---------------------------------------------------------------------------
# M2: latest-accepted pointer tests
# ---------------------------------------------------------------------------


def test_pointer_first_accepted_creates_pointer_with_required_fields(
    tmp_path: Path,
) -> None:
    """First accepted import writes ``latest-accepted.json`` with every
    contract-required field plus the deterministic ``finished_at``."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome
    assert outcome.pointer_updated is True
    assert outcome.pointer_path == str(root / "latest-accepted.json")

    pointer = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "trade_date",
        "workflow_run_id",
        "relative_run_path",
        "governance_status",
        "governed_report_sha256",
        "manifest_sha256",
        "updated_at",
    }
    missing = required - set(pointer)
    assert not missing, f"missing required fields: {missing}"
    assert pointer["schema_version"] == (
        "invest-pipeline/workbuddy-latest-accepted-pointer@1.0"
    )
    assert pointer["trade_date"] == "2026-08-13"
    assert pointer["workflow_run_id"] == "wr-2026-08-13-001"
    assert pointer["relative_run_path"] == "runs/2026-08-13/wr-2026-08-13-001"
    assert pointer["governance_status"] == "accepted"
    assert isinstance(pointer["updated_at"], str) and pointer["updated_at"]
    assert "finished_at" in pointer


def test_pointer_hashes_recompute_from_archived_files(tmp_path: Path) -> None:
    """The pointer's ``governed_report_sha256`` and ``manifest_sha256``
    must be independently re-computable from the actual bytes of the
    files inside ``<root>/runs/<trade_date>/<workflow_run_id>/``."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome

    pointer = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    governed_path = (
        Path(outcome.run_dir) / "governed-quality-report.json"
    )
    manifest_path = Path(outcome.run_dir) / "manifest.json"
    governed_bytes = governed_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    assert pointer["governed_report_sha256"] == hashlib.sha256(governed_bytes).hexdigest()
    assert pointer["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()


def test_pointer_uses_result_finished_at_when_present(tmp_path: Path) -> None:
    """``finished_at`` is sourced from the archived result JSON when
    present so that re-imports do not drift to wall-clock time."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(
        src,
        result_overrides={
            "finished_at": "2026-08-13T10:30:00+00:00",
        },
    )
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome

    pointer = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    assert pointer["finished_at"] == "2026-08-13T10:30:00+00:00"


def test_pointer_falls_back_to_validated_at_for_missing_finished_at(
    tmp_path: Path,
) -> None:
    """When result.json has no ``finished_at`` the pointer uses the
    deterministic ``validated_at`` derived from the source triplet
    mtimes; idempotent re-imports must therefore yield byte-identical
    pointer contents (apart from the moving ``updated_at``)."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    first = archive_run(source_dir=str(src), governance_root=str(root))
    assert first.exit_code == 0, first

    pointer1 = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 0, second
    assert second.is_idempotent is True

    pointer2 = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    assert pointer2["finished_at"] == pointer1["finished_at"]
    assert pointer2["trade_date"] == pointer1["trade_date"]
    assert pointer2["workflow_run_id"] == pointer1["workflow_run_id"]
    assert pointer2["relative_run_path"] == pointer1["relative_run_path"]
    assert pointer2["governed_report_sha256"] == pointer1["governed_report_sha256"]
    assert pointer2["manifest_sha256"] == pointer1["manifest_sha256"]


def test_pointer_idempotent_reimport_does_not_overwrite_bytes(
    tmp_path: Path,
) -> None:
    """Accepted re-import (idempotent) must leave ``latest-accepted.json``
    byte-identical: pointer_updated is False and the file on disk is
    unchanged."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    first = archive_run(source_dir=str(src), governance_root=str(root))
    assert first.exit_code == 0, first
    assert first.pointer_updated is True
    pointer_bytes_first = (root / "latest-accepted.json").read_bytes()

    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 0, second
    assert second.is_idempotent is True
    assert second.pointer_updated is False
    pointer_bytes_second = (root / "latest-accepted.json").read_bytes()
    assert pointer_bytes_second == pointer_bytes_first


def test_pointer_old_trade_date_does_not_regress(tmp_path: Path) -> None:
    """An accepted import for an older ``trade_date`` must NOT overwrite
    a newer pointer.  The on-disk file remains byte-identical and the
    import still exits 0."""
    from invest_pipeline.workbuddy_reports import archive_run

    src_new = tmp_path / "src_new"
    src_new.mkdir()
    src_old = tmp_path / "src_old"
    src_old.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    _write_triplet(
        src_new,
        result_overrides={"finished_at": "2026-08-13T11:00:00+00:00"},
    )
    new_outcome = archive_run(source_dir=str(src_new), governance_root=str(root))
    assert new_outcome.exit_code == 0, new_outcome
    assert new_outcome.pointer_updated is True
    pointer_bytes_new = (root / "latest-accepted.json").read_bytes()

    _write_triplet(
        src_old,
        result_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-001",
            "finished_at": "2026-08-12T11:00:00+00:00",
        },
        quality_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-001",
        },
    )
    old_outcome = archive_run(source_dir=str(src_old), governance_root=str(root))
    assert old_outcome.exit_code == 0, old_outcome
    assert old_outcome.pointer_updated is False

    pointer_bytes_after = (root / "latest-accepted.json").read_bytes()
    assert pointer_bytes_after == pointer_bytes_new


def test_pointer_same_trade_date_newer_finished_at_wins(
    tmp_path: Path,
) -> None:
    """Two accepted runs for the same ``trade_date``: the one with the
    strictly greater ``finished_at`` (sort key) takes the pointer."""
    from invest_pipeline.workbuddy_reports import archive_run

    src_a = tmp_path / "src_a"
    src_a.mkdir()
    src_b = tmp_path / "src_b"
    src_b.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    _write_triplet(
        src_a,
        result_overrides={
            "workflow_run_id": "wr-2026-08-13-A",
            "finished_at": "2026-08-13T09:00:00+00:00",
        },
        quality_overrides={"workflow_run_id": "wr-2026-08-13-A"},
    )
    first = archive_run(source_dir=str(src_a), governance_root=str(root))
    assert first.exit_code == 0, first
    assert first.pointer_updated is True

    _write_triplet(
        src_b,
        result_overrides={
            "workflow_run_id": "wr-2026-08-13-B",
            "finished_at": "2026-08-13T10:00:00+00:00",
        },
        quality_overrides={"workflow_run_id": "wr-2026-08-13-B"},
    )
    second = archive_run(source_dir=str(src_b), governance_root=str(root))
    assert second.exit_code == 0, second
    assert second.pointer_updated is True

    pointer = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    assert pointer["workflow_run_id"] == "wr-2026-08-13-B"
    assert pointer["relative_run_path"] == "runs/2026-08-13/wr-2026-08-13-B"


def test_pointer_partial_does_not_create_or_modify(tmp_path: Path) -> None:
    """Partial runs archive but must not create or modify the pointer."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_partial_triplet(src)

    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 2, outcome
    assert outcome.governance_status == "partial"
    assert outcome.pointer_updated is False
    assert not (root / "latest-accepted.json").exists()


def test_pointer_partial_does_not_modify_existing_pointer(tmp_path: Path) -> None:
    """A partial run for a different (trade_date, workflow_run_id) — so
    it does not hash-conflict with an existing accepted archive — must
    not overwrite the pointer that the accepted run installed."""
    from invest_pipeline.workbuddy_reports import archive_run

    src_ok = tmp_path / "src_ok"
    src_ok.mkdir()
    src_partial = tmp_path / "src_partial"
    src_partial.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    _write_triplet(src_ok)
    first = archive_run(source_dir=str(src_ok), governance_root=str(root))
    assert first.exit_code == 0, first
    pointer_bytes_before = (root / "latest-accepted.json").read_bytes()

    _write_triplet(
        src_partial,
        result_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-001",
            "finished_at": "2026-08-12T11:00:00+00:00",
            "stages": [
                {
                    "name": "stage_universe",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_scoring",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_ranking",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA"],
                    "rejected_symbols": ["BBB"],
                    "missing_data_symbols": [],
                },
            ],
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.7,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
            "ranking": [
                {"sector_id": "AAA", "ranking_status": "candidate"},
                {"sector_id": "BBB", "ranking_status": "rejected"},
            ],
            "candidates": [{"sector_id": "AAA", "candidate_status": "candidate"}],
            "missing_data_symbols": ["CCC"],
        },
        quality_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-001",
        },
    )
    second = archive_run(source_dir=str(src_partial), governance_root=str(root))
    assert second.exit_code == 2, second
    assert second.pointer_updated is False

    pointer_bytes_after = (root / "latest-accepted.json").read_bytes()
    assert pointer_bytes_after == pointer_bytes_before


def test_pointer_rejected_does_not_create_or_modify(tmp_path: Path) -> None:
    """Rejected runs (with valid identity) archive but never write the
    pointer."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(
        src,
        result_overrides={
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.42,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "CCC",
                    "dimension_scores": {"growth": 0.2, "value": 0.1},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.16,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
        },
    )
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 3, outcome
    assert outcome.pointer_updated is False
    assert not (root / "latest-accepted.json").exists()


def test_pointer_corrupt_existing_returns_exit_5_and_preserves_file(
    tmp_path: Path,
) -> None:
    """A corrupt on-disk pointer must halt safely: exit 5, the original
    pointer bytes are preserved, and the archive that was just built is
    not promoted into a corrupted pointer slot."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    pointer_path = root / "latest-accepted.json"
    pointer_bytes_before = b"{not valid json at all"
    pointer_path.write_bytes(pointer_bytes_before)
    assert pointer_path.is_file()

    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 5, outcome
    assert outcome.pointer_updated is False
    assert outcome.pointer_path == str(pointer_path)
    assert pointer_path.read_bytes() == pointer_bytes_before


def test_pointer_corrupt_existing_via_missing_field_returns_exit_5(
    tmp_path: Path,
) -> None:
    """A pointer that parses as JSON but lacks the required sort-key
    fields is treated as corrupt and must not be overwritten."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    pointer_path = root / "latest-accepted.json"
    pointer_bytes_before = json.dumps(
        {"schema_version": "invest-pipeline/workbuddy-latest-accepted-pointer@1.0"}
    ).encode("utf-8")
    pointer_path.write_bytes(pointer_bytes_before)

    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 5, outcome
    assert outcome.pointer_updated is False
    assert pointer_path.read_bytes() == pointer_bytes_before


def test_pointer_conflict_does_not_update_pointer(tmp_path: Path) -> None:
    """A conflict (exit 5, ``is_conflict=True``) must leave the pointer
    untouched."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    first = archive_run(source_dir=str(src), governance_root=str(root))
    assert first.exit_code == 0, first
    assert first.pointer_updated is True
    pointer_bytes_before = (root / "latest-accepted.json").read_bytes()

    _write_triplet(
        src,
        result_overrides={
            "applied_rules": [
                {"rule_id": "rule_growth_floor", "source_ref": "src_fundamental"},
            ],
        },
    )
    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 5, second
    assert second.is_conflict is True
    assert second.pointer_updated is False

    pointer_bytes_after = (root / "latest-accepted.json").read_bytes()
    assert pointer_bytes_after == pointer_bytes_before


def test_pointer_atomic_write_leaves_no_temp_file(tmp_path: Path) -> None:
    """Atomic write via ``os.replace`` must not leave ``.tmp-*`` files
    under the governance root after a successful or skipped pointer
    update."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome

    tmp_files = [
        p for p in root.iterdir() if p.name.startswith(".tmp-")
    ]
    assert tmp_files == [], f"unexpected tmp files: {tmp_files}"


def test_pointer_relative_run_path_uses_forward_slashes(tmp_path: Path) -> None:
    """``relative_run_path`` must be ``runs/<trade_date>/<workflow_run_id>``
    with forward slashes regardless of platform separator."""
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    outcome = archive_run(source_dir=str(src), governance_root=str(root))
    assert outcome.exit_code == 0, outcome

    pointer = json.loads((root / "latest-accepted.json").read_text(encoding="utf-8"))
    assert "/" in pointer["relative_run_path"]
    assert "\\" not in pointer["relative_run_path"]
    parts = pointer["relative_run_path"].split("/")
    assert parts == ["runs", "2026-08-13", "wr-2026-08-13-001"]


# ---------------------------------------------------------------------------
# Concurrency: fcntl.flock serialization regression tests
# ---------------------------------------------------------------------------


def _race_old_pointer_update_in_subprocess(
    target_dir: str,
    result_basename: str,
    governance_root: str,
    validated_at: str,
) -> dict[str, object]:
    """Top-level helper run by ProcessPoolExecutor workers so that the
    concurrent ``_update_latest_pointer`` calls truly execute in
    separate OS processes (and therefore observe distinct
    ``fcntl.flock`` file descriptions).

    Calling the private ``_update_latest_pointer`` directly — rather
    than the full ``archive_run`` — lets every worker race on the
    *same* pre-staged old candidate.  Running ``archive_run`` instead
    would force each worker to materialise its own ``target_dir`` and
    introduce an unrelated ``ENOTEMPTY`` conflict that masks the
    pointer race this test is designed to exercise.
    """
    from invest_pipeline.workbuddy_reports.archive import _update_latest_pointer

    updated, status, path = _update_latest_pointer(
        target_dir=target_dir,
        result_basename=result_basename,
        governance_root=governance_root,
        validated_at=validated_at,
    )
    return {
        "pointer_updated": updated,
        "pointer_status": status,
        "pointer_path": path,
    }


def test_pointer_concurrent_old_writers_cannot_overwrite_new(
    tmp_path: Path,
) -> None:
    """Regression test for the M2 compare-and-set race: with a newer
    pointer already on disk, N truly-concurrent (separate-process) old
    candidate writers must all report ``pointer_updated=False`` /
    ``pointer_status='skipped'`` and the on-disk pointer must remain
    byte-identical to the newer one.

    The race only manifests under real OS-level concurrency because
    ``fcntl.flock`` is associated with an open-file-description and a
    fresh ``open()`` per process returns a distinct one.  Threads in
    the same process share fewer of those boundaries, so the test
    uses ``ProcessPoolExecutor`` (default ``fork`` on Linux) to
    guarantee multiple kernel-side contenders hit the lock
    simultaneously.
    """
    from concurrent.futures import ProcessPoolExecutor

    from invest_pipeline.workbuddy_reports import archive_run

    root = tmp_path / "root"
    root.mkdir()

    # 1. Establish the "new" pointer via a synchronous import.
    new_src = tmp_path / "new_src"
    new_src.mkdir()
    _write_triplet(
        new_src,
        result_overrides={
            "workflow_run_id": "wr-2026-08-13-NEW",
            "finished_at": "2026-08-13T11:00:00+00:00",
        },
        quality_overrides={"workflow_run_id": "wr-2026-08-13-NEW"},
    )
    new_outcome = archive_run(source_dir=str(new_src), governance_root=str(root))
    assert new_outcome.exit_code == 0, new_outcome
    assert new_outcome.pointer_updated is True, new_outcome
    new_pointer_bytes = (root / "latest-accepted.json").read_bytes()
    assert (root / ".latest-accepted.lock").is_file()

    # 2. Pre-archive an OLD candidate once (synchronously, single writer)
    #    so the race below can reuse the same target_dir without each
    #    worker stumbling over an ``os.replace`` / ``ENOTEMPTY`` conflict
    #    that would mask the pointer race we are actually testing.
    old_src = tmp_path / "old_src"
    old_src.mkdir()
    _write_triplet(
        old_src,
        result_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-OLD",
            "finished_at": "2026-08-12T11:00:00+00:00",
        },
        quality_overrides={
            "trade_date": "2026-08-12",
            "workflow_run_id": "wr-2026-08-12-OLD",
        },
    )
    old_outcome = archive_run(source_dir=str(old_src), governance_root=str(root))
    assert old_outcome.exit_code == 0, old_outcome
    assert old_outcome.pointer_updated is False, old_outcome
    assert old_outcome.pointer_status == "skipped", old_outcome
    assert old_outcome.run_dir is not None

    # Sanity check: the on-disk pointer still matches the NEW candidate.
    assert (root / "latest-accepted.json").read_bytes() == new_pointer_bytes

    # 3. Fan out N concurrent ``_update_latest_pointer`` calls in separate
    #    processes, all racing on the same pre-staged old candidate.
    n_workers = 8
    target_dir_str = str(old_outcome.run_dir)
    root_str = str(root)
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = [
            ex.submit(
                _race_old_pointer_update_in_subprocess,
                target_dir_str,
                "result.json",
                root_str,
                old_outcome.validated_at,
            )
            for _ in range(n_workers)
        ]
        results = [f.result() for f in futures]

    # 4. Every old writer must have been rejected by the sort-key guard
    #    while it held the lock — no writer may report success.
    for r in results:
        assert r["pointer_updated"] is False, r
        assert r["pointer_status"] == "skipped", r
        assert r["pointer_path"] == str(root / "latest-accepted.json"), r

    # 5. The on-disk pointer must still be the new one, byte-for-byte.
    assert (root / "latest-accepted.json").read_bytes() == new_pointer_bytes

    # 6. The lock sentinel must remain in place so future writers can flock.
    assert (root / ".latest-accepted.lock").is_file()
    # 7. No ``.tmp-*`` artefacts left behind after the race.
    assert [p for p in root.iterdir() if p.name.startswith(".tmp-")] == []


def test_pointer_lock_file_persists_across_runs(tmp_path: Path) -> None:
    """The ``fcntl.flock`` sentinel sits next to the pointer under
    ``governance_root`` and is never removed by ``archive_run`` so that
    subsequent invocations can reuse it as the lock target.  This is the
    structural companion to the multiprocessing race regression above.
    """
    from invest_pipeline.workbuddy_reports import archive_run

    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    first = archive_run(source_dir=str(src), governance_root=str(root))
    assert first.exit_code == 0, first
    lock_path = root / ".latest-accepted.lock"
    assert lock_path.is_file()

    second = archive_run(source_dir=str(src), governance_root=str(root))
    assert second.exit_code == 0, second
    assert second.is_idempotent is True
    # Lock sentinel still present after idempotent re-import.
    assert lock_path.is_file()
    # No stray ``.tmp-*`` artefacts left under the root.
    assert [p for p in root.iterdir() if p.name.startswith(".tmp-")] == []


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_import_exit_code_accepted(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "accepted"
    assert payload["is_idempotent"] is False
    assert payload["is_conflict"] is False
    assert payload["exit_code"] == 0
    assert payload["run_dir"].endswith("/runs/2026-08-13/wr-2026-08-13-001")


def test_cli_import_exit_code_partial(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_partial_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "partial"
    assert payload["exit_code"] == 2


def test_cli_import_exit_code_rejected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(
        src,
        result_overrides={
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.42,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "CCC",
                    "dimension_scores": {"growth": 0.2, "value": 0.1},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.16,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
        },
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "rejected"
    assert payload["exit_code"] == 3


def test_cli_import_exit_code_input_error(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            "/nonexistent/workbuddy/run",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "rejected"
    assert payload["exit_code"] == 4
    assert payload["run_dir"] is None


def test_cli_import_exit_code_conflict(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    _write_triplet(
        src,
        result_overrides={
            "applied_rules": [
                {"rule_id": "rule_growth_floor", "source_ref": "src_fundamental"},
            ],
        },
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 5, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["is_conflict"] is True
    assert payload["exit_code"] == 5


def test_cli_import_stdout_is_single_json(tmp_path: Path) -> None:
    """``import`` must emit exactly one JSON object on stdout (no leading
    banners, no extra lines)."""
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, lines
    payload = json.loads(lines[0])
    assert "schema_version" in payload
    assert payload["schema_version"] == "invest-pipeline/workbuddy-governed-quality-report@1.0"


def test_cli_import_stdout_exposes_pointer_fields(tmp_path: Path) -> None:
    """M2: the ``import`` stdout payload adds ``pointer_updated`` and
    ``pointer_path`` and remains a single JSON object."""
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, lines
    payload = json.loads(lines[0])
    assert payload["pointer_updated"] is True
    assert payload["pointer_path"] == str(root / "latest-accepted.json")
    assert "schema_version" in payload


def test_cli_import_stdout_pointer_updated_false_for_partial(tmp_path: Path) -> None:
    """M2: partial runs emit ``pointer_updated=False`` and exit 2."""
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_partial_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["pointer_updated"] is False
    assert not (root / "latest-accepted.json").exists()


def test_cli_import_stdout_pointer_updated_false_for_idempotent(
    tmp_path: Path,
) -> None:
    """M2: idempotent re-import emits ``pointer_updated=False`` while
    still exiting 0."""
    src = tmp_path / "src"
    src.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    _write_triplet(src)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "import",
            "--source-dir",
            str(src),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["is_idempotent"] is True
    assert payload["pointer_updated"] is False
    assert payload["pointer_path"] == str(root / "latest-accepted.json")


def test_cli_validate_regression(tmp_path: Path) -> None:
    """The ``validate`` subcommand continues to function after the M1
    import wiring."""
    src = tmp_path / "src"
    src.mkdir()
    _write_triplet(src)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "validate",
            "--source-dir",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "accepted"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_no_latest_pointer(root: Path) -> None:
    """Verify that no ``latest-accepted.json`` (or any other pointer) is
    written under ``root``."""
    candidates = [
        root / "latest-accepted.json",
        root / "runs" / "latest-accepted.json",
    ]
    for path in candidates:
        assert not path.exists(), f"unexpected latest pointer at {path!r}"

    if (root / "runs").is_dir():
        for dirpath, _dirnames, filenames in os.walk(root / "runs"):
            for filename in filenames:
                assert not filename.startswith("latest-"), (
                    f"unexpected latest file: {dirpath}/{filename}"
                )


# ---------------------------------------------------------------------------
# Fixture builders (duplicated from test_workbuddy_reports_validator.py
# to keep the two test files self-contained)
# ---------------------------------------------------------------------------


def _core_identity() -> dict[str, object]:
    return {
        "workflow_run_id": "wr-2026-08-13-001",
        "trade_date": "2026-08-13",
        "report_rules_version": "1.1.2",
        "strategy_version": "sector-seven-step-v2@1",
        "producer_status": "succeeded",
    }


def _good_sources() -> list[dict[str, object]]:
    return [
        {"source_id": "src_market", "type": "market", "path": "ignored"},
        {"source_id": "src_fundamental", "type": "fundamental", "path": "ignored"},
    ]


def _good_stages() -> list[dict[str, object]]:
    return [
        {
            "name": "stage_universe",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB", "CCC"],
            "rejected_symbols": [],
            "missing_data_symbols": [],
        },
        {
            "name": "stage_scoring",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB", "CCC"],
            "rejected_symbols": [],
            "missing_data_symbols": [],
        },
        {
            "name": "stage_ranking",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB"],
            "rejected_symbols": ["CCC"],
            "missing_data_symbols": [],
        },
    ]


def _good_scores() -> list[dict[str, object]]:
    return [
        {
            "sector_id": "AAA",
            "dimension_scores": {"growth": 0.9, "value": 0.4},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.9 * 0.6 + 0.4 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
        {
            "sector_id": "BBB",
            "dimension_scores": {"growth": 0.5, "value": 0.7},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.5 * 0.6 + 0.7 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
        {
            "sector_id": "CCC",
            "dimension_scores": {"growth": 0.2, "value": 0.1},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.2 * 0.6 + 0.1 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
    ]


def _good_ranking() -> list[dict[str, object]]:
    return [
        {"sector_id": "AAA", "ranking_status": "candidate"},
        {"sector_id": "BBB", "ranking_status": "candidate"},
        {"sector_id": "CCC", "ranking_status": "rejected"},
    ]


def _good_candidates() -> list[dict[str, object]]:
    return [
        {"sector_id": "AAA", "candidate_status": "candidate"},
        {"sector_id": "BBB", "candidate_status": "candidate"},
    ]


def _good_applied_rules() -> list[dict[str, object]]:
    return [
        {"rule_id": "rule_growth_floor", "source_ref": "src_market"},
        {"rule_id": "rule_value_ceiling", "source_refs": ["src_fundamental"]},
    ]


def _good_result() -> dict[str, object]:
    return {
        "schema_version": "invest-pipeline/sector-result@1.0",
        **_core_identity(),
        "sources": _good_sources(),
        "stages": _good_stages(),
        "scores": _good_scores(),
        "ranking": _good_ranking(),
        "candidates": _good_candidates(),
        "applied_rules": _good_applied_rules(),
        "missing_data_symbols": [],
        "normalization": {
            "growth": {"min": 0.0, "max": 1.0},
            "value": {"min": 0.0, "max": 1.0},
        },
    }


def _good_quality(*, result_path: Path, report_path: Path) -> dict[str, object]:
    def _sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    return {
        "schema_version": "1.0",
        **_core_identity(),
        "file_hashes": {
            result_path.name: _sha(result_path),
            report_path.name: _sha(report_path),
        },
        "checks": [{"check_id": "self_test", "status": "passed"}],
    }


def _good_markdown(result: dict[str, object]) -> str:
    lines = [
        f"# 板块强度排行榜 {result['trade_date']}",
        "",
        f"workflow_run_id: {result['workflow_run_id']}",
        f"trade_date: {result['trade_date']}",
        f"producer_status: {result['producer_status']}",
        "",
        "| 排名 | 板块 | 综合分 | 候选状态 |",
        "| ---: | --- | ---: | --- |",
    ]
    for i, entry in enumerate(result["ranking"], start=1):
        score = next(
            s["overall_score"]
            for s in result["scores"]
            if s["sector_id"] == entry["sector_id"]
        )
        lines.append(
            f"| {i} | {entry['sector_id']} | {score:.4f} | {entry['ranking_status']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _refresh_quality_hashes(
    quality: dict[str, object], result_path: Path, report_path: Path
) -> None:
    file_hashes = quality.get("file_hashes")
    if not isinstance(file_hashes, dict):
        return
    file_hashes[result_path.name] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    file_hashes[report_path.name] = hashlib.sha256(report_path.read_bytes()).hexdigest()


def _write_triplet(
    src_dir: Path,
    *,
    result_overrides: dict[str, object] | None = None,
    quality_overrides: dict[str, object] | None = None,
    markdown_text: str | None = None,
    result_file_name: str = "result.json",
    report_file_name: str = "report.md",
    quality_file_name: str = "quality_report.json",
) -> tuple[Path, Path, Path]:
    result = _good_result()
    if result_overrides:
        for key, value in result_overrides.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = {**result[key], **value}
            else:
                result[key] = value

    result_path = src_dir / result_file_name
    report_path = src_dir / report_file_name
    quality_path = src_dir / quality_file_name

    result_path.write_text(json.dumps(result), encoding="utf-8")
    report_path.write_text(
        markdown_text if markdown_text is not None else _good_markdown(result),
        encoding="utf-8",
    )

    quality = _good_quality(result_path=result_path, report_path=report_path)
    if quality_overrides:
        for key, value in quality_overrides.items():
            if isinstance(value, dict) and isinstance(quality.get(key), dict):
                quality[key] = {**quality[key], **value}
            else:
                quality[key] = value
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    return result_path, report_path, quality_path


def _write_partial_triplet(src_dir: Path) -> tuple[Path, Path, Path]:
    """Write a triplet that validates as ``partial`` (missing-data path)."""
    return _write_triplet(
        src_dir,
        result_overrides={
            "stages": [
                {
                    "name": "stage_universe",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_scoring",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_ranking",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA"],
                    "rejected_symbols": ["BBB"],
                    "missing_data_symbols": [],
                },
            ],
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.7,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
            "ranking": [
                {"sector_id": "AAA", "ranking_status": "candidate"},
                {"sector_id": "BBB", "ranking_status": "rejected"},
            ],
            "candidates": [{"sector_id": "AAA", "candidate_status": "candidate"}],
            "missing_data_symbols": ["CCC"],
        },
    )