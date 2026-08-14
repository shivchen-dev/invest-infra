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
        ),
        SimpleNamespace(package="candidates_bad.json", result=None, error="invalid payload"),
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
            {"file": "candidates_ok.json", "status": "success", "observation_count": 2},
            {"file": "candidates_bad.json", "status": "failed", "observation_count": 0},
        ]
    }
    assert "invalid payload" not in capsys.readouterr().out


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
