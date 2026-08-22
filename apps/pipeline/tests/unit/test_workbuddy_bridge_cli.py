"""Behavioral tests for the WorkBuddy bridge import CLI."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from invest_pipeline import workbuddy_bridge_cli as cli
from invest_pipeline.config import Settings


def test_parser_accepts_optional_path_overrides() -> None:
    args = cli.build_parser().parse_args(
        ["--bridge-root", "/mnt/shared", "--source-dir", "/mnt/reports"]
    )

    assert args.bridge_root == Path("/mnt/shared")
    assert args.source_dir == Path("/mnt/reports")


def test_default_paths_follow_settings() -> None:
    settings = Settings()

    bridge_root, source_dir = cli.resolve_paths(settings, cli.build_parser().parse_args([]))

    assert bridge_root == Path("/shared")
    assert source_dir == Path("/shared/选股报告")


def test_run_import_emits_redacted_summary_with_fake_dependencies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SimpleNamespace(
            package="candidates_ok.json",
            result=SimpleNamespace(observations=(1, 2)),
            error=None,
            archive_uri="archive://runs/2026-08-14/ok",
            accepted_count=2,
            rejected_count=0,
            needs_symbol_resolution_count=0,
            findings=({"scope": "item", "index": 0, "error": "symbol needs resolution"},),
            archive_idempotent=False,
            import_idempotent=False,
            conflict=False,
        ),
        SimpleNamespace(
            package="candidates_bad.json",
            result=None,
            error="invalid payload",
            archive_uri=None,
            accepted_count=None,
            rejected_count=None,
            needs_symbol_resolution_count=None,
            findings=(),
            archive_idempotent=None,
            import_idempotent=None,
            conflict=None,
        ),
    )

    class _Gateway:
        def __init__(self, bridge_root, source_dir):
            assert bridge_root == Path("/shared")
            assert source_dir == Path("/shared/选股报告")

        def process_once(self, *, uow):
            assert uow == "uow"
            return outcomes

    class _Uow:
        def __init__(self, factory):
            assert factory == "sessions"

        def __enter__(self):
            return "uow"

        def __exit__(self, *exc_info):
            return False

    cli.run_import(
        Path("/shared"),
        Path("/shared/选股报告"),
        engine_builder=lambda _url: "engine",
        session_factory_builder=lambda _engine: "sessions",
        gateway_factory=_Gateway,
        uow_factory=_Uow,
        settings=Settings(),
    )

    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "imports": [
            {
                "file": "candidates_ok.json",
                "status": "success",
                "observation_count": 2,
                "archive_uri": "archive://runs/2026-08-14/ok",
                "accepted_count": 2,
                "rejected_count": 0,
                "needs_symbol_resolution_count": 0,
                "findings": [
                    {"scope": "item", "index": 0, "error": "symbol needs resolution"},
                ],
                "archive_idempotent": False,
                "import_idempotent": False,
                "conflict": False,
            },
            {
                "file": "candidates_bad.json",
                "status": "failed",
                "observation_count": 0,
                "archive_uri": None,
                "accepted_count": None,
                "rejected_count": None,
                "needs_symbol_resolution_count": None,
                "findings": [],
                "archive_idempotent": None,
                "import_idempotent": None,
                "conflict": None,
            },
        ]
    }
    assert "invalid payload" not in capsys.readouterr().out


def test_summary_tolerates_legacy_outcomes_without_new_fields() -> None:
    outcomes = (
        SimpleNamespace(
            package="legacy.json",
            result=SimpleNamespace(observations=(1,)),
            error=None,
        ),
    )

    summary = cli._summary(outcomes)

    assert summary == {
        "imports": [
            {
                "file": "legacy.json",
                "status": "success",
                "observation_count": 1,
                "archive_uri": None,
                "accepted_count": None,
                "rejected_count": None,
                "needs_symbol_resolution_count": None,
                "findings": [],
                "archive_idempotent": None,
                "import_idempotent": None,
                "conflict": None,
            },
        ]
    }


def test_summary_marks_conflict_outcome_without_leaking_payload() -> None:
    outcomes = (
        SimpleNamespace(
            package="conflict.json",
            result=None,
            error="archive conflict for workflow_run_id=run-1 trade_date=2026-08-14",
            archive_uri="archive://runs/2026-08-14/run-1",
            accepted_count=1,
            rejected_count=0,
            needs_symbol_resolution_count=None,
            findings=({"scope": "item", "error": "rejected_by_intake"},),
            archive_idempotent=False,
            import_idempotent=None,
            conflict=True,
        ),
    )

    summary = cli._summary(outcomes)
    payload = json.dumps(summary, ensure_ascii=False)

    assert summary["imports"][0]["status"] == "failed"
    assert summary["imports"][0]["conflict"] is True
    assert summary["imports"][0]["archive_uri"] == "archive://runs/2026-08-14/run-1"
    assert summary["imports"][0]["accepted_count"] == 1
    assert summary["imports"][0]["rejected_count"] == 0
    assert summary["imports"][0]["archive_idempotent"] is False
    assert summary["imports"][0]["import_idempotent"] is None
    # The raw error text and any candidate raw payload must never appear in
    # the summary; archive_uri is the only identity that surfaces.
    assert "archive conflict for workflow_run_id" not in payload
    assert "trade_date" not in payload
    assert "raw" not in payload


def test_main_returns_nonzero_without_printing_exception_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "run_import",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret payload")),
    )

    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: WorkBuddy import failed\n"
    assert "secret payload" not in captured.err
