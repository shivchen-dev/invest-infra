from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from invest_domain.research import ResearchPlaybook
from invest_pipeline import research_run_worker_cli as cli

_RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
_CASE_ID = UUID("22222222-2222-4222-8222-222222222222")


def _jiuwenswarm_argv(tmp_path: Path) -> list[str]:
    return [
        "--runner",
        "jiuwenswarm",
        "--helper-path",
        str(tmp_path / "helper.py"),
        "--workspace",
        str(tmp_path / "workspace"),
        "--artifact-root",
        str(tmp_path / "artifacts"),
    ]


def test_parser_defaults_to_fake_runner_without_external_paths() -> None:
    args = cli.build_parser().parse_args([])

    assert args.runner == "fake"
    assert args.helper_path is None
    assert args.workspace is None
    assert args.artifact_root is None
    assert args.playbook_key == "etf_medium_term_assessment"
    assert args.playbook_version == "v0.1.0"
    assert args.limit == 1
    assert args.run_id is None


def test_parser_accepts_explicit_jiuwenswarm_with_paths(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args(_jiuwenswarm_argv(tmp_path))

    assert args.runner == "jiuwenswarm"
    assert args.helper_path == tmp_path / "helper.py"
    assert args.workspace == tmp_path / "workspace"
    assert args.artifact_root == tmp_path / "artifacts"


def test_jiuwenswarm_runner_requires_external_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main(["--runner", "jiuwenswarm"])

    captured = capsys.readouterr()
    assert rc != 0
    assert "helper-path" in captured.err
    assert "requires" in captured.err


def test_empty_queue_emits_empty_summary_default_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = SimpleNamespace(run_next=lambda *, limit: None)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_fake_research_worker", lambda **kwargs: worker)
    stdout = StringIO()

    assert cli.main([], stdout=stdout) == 0
    assert json.loads(stdout.getvalue()) == {
        "status": "empty",
        "run_id": None,
        "case_id": None,
        "replay": False,
    }


def test_fake_default_calls_build_fake_research_worker_with_database_url_and_playbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_next=lambda *, limit: None)

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_fake_research_worker", fake_builder)
    stdout = StringIO()

    assert cli.main([], stdout=stdout) == 0

    assert captured["database_url"] == "sqlite://"
    playbook = captured["playbook"]
    assert isinstance(playbook, ResearchPlaybook)
    assert playbook.playbook_key == "etf_medium_term_assessment"
    assert playbook.playbook_version == "v0.1.0"


def test_run_id_calls_run_once_and_emits_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[UUID] = []
    outcome = SimpleNamespace(
        run=SimpleNamespace(run_id=_RUN_ID, status="succeeded"),
        case=SimpleNamespace(case_id=_CASE_ID),
        replay=True,
    )
    worker = SimpleNamespace(run_once=lambda run_id: calls.append(run_id) or outcome)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_fake_research_worker", lambda **kwargs: worker)
    stdout = StringIO()

    assert cli.main(["--run-id", str(_RUN_ID)], stdout=stdout) == 0
    assert calls == [_RUN_ID]
    assert json.loads(stdout.getvalue()) == {
        "status": "succeeded",
        "run_id": str(_RUN_ID),
        "case_id": str(_CASE_ID),
        "replay": True,
    }


def test_jiuwenswarm_explicit_calls_compatibility_builder_with_external_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def jw_builder(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(run_next=lambda *, limit: None)

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_jiuwenswarm_worker", jw_builder)
    stdout = StringIO()

    assert cli.main(_jiuwenswarm_argv(tmp_path), stdout=stdout) == 0

    assert captured["database_url"] == "sqlite://"
    assert captured["helper_path"] == tmp_path / "helper.py"
    assert captured["workspace"] == str(tmp_path / "workspace")
    assert captured["artifact_root"] == tmp_path / "artifacts"
    playbook = captured["playbook"]
    assert isinstance(playbook, ResearchPlaybook)
    assert playbook.playbook_key == "etf_medium_term_assessment"
    assert playbook.playbook_version == "v0.1.0"
    assert captured["mode"] == "default"
    assert captured["timeout_seconds"] == 900.0
    assert captured["idle_timeout_seconds"] == 120.0


def test_error_is_short_and_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = SimpleNamespace(
        run_next=lambda *, limit: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_fake_research_worker", lambda **kwargs: worker)
    stderr = StringIO()

    assert cli.main([], stderr=stderr) != 0
    assert stderr.getvalue().count("\n") == 1
    assert stderr.getvalue().startswith("error: ")