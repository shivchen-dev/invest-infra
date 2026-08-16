from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from invest_pipeline import research_run_worker_cli as cli

_RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
_CASE_ID = UUID("22222222-2222-4222-8222-222222222222")


def _argv(tmp_path: Path) -> list[str]:
    return [
        "--helper-path",
        str(tmp_path / "helper.py"),
        "--workspace",
        str(tmp_path / "workspace"),
        "--artifact-root",
        str(tmp_path / "artifacts"),
    ]


def test_parser_requires_paths_and_has_requested_defaults(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args(_argv(tmp_path))

    assert args.helper_path == tmp_path / "helper.py"
    assert args.workspace == tmp_path / "workspace"
    assert args.artifact_root == tmp_path / "artifacts"
    assert args.playbook_key == "etf_medium_term_assessment"
    assert args.playbook_version == "v0.1.0"
    assert args.limit == 1
    assert args.run_id is None

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_empty_queue_emits_empty_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    worker = SimpleNamespace(run_next=lambda *, limit: None)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_jiuwenswarm_worker", lambda **kwargs: worker)
    stdout = StringIO()

    assert cli.main(_argv(tmp_path), stdout=stdout) == 0
    assert json.loads(stdout.getvalue()) == {
        "status": "empty",
        "run_id": None,
        "case_id": None,
        "replay": False,
    }


def test_run_id_calls_run_once_and_emits_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[UUID] = []
    outcome = SimpleNamespace(
        run=SimpleNamespace(run_id=_RUN_ID, status="succeeded"),
        case=SimpleNamespace(case_id=_CASE_ID),
        replay=True,
    )
    worker = SimpleNamespace(run_once=lambda run_id: calls.append(run_id) or outcome)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_jiuwenswarm_worker", lambda **kwargs: worker)
    stdout = StringIO()

    assert cli.main(_argv(tmp_path) + ["--run-id", str(_RUN_ID)], stdout=stdout) == 0
    assert calls == [_RUN_ID]
    assert json.loads(stdout.getvalue()) == {
        "status": "succeeded",
        "run_id": str(_RUN_ID),
        "case_id": str(_CASE_ID),
        "replay": True,
    }


def test_error_is_short_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = SimpleNamespace(run_next=lambda *, limit: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(cli, "build_jiuwenswarm_worker", lambda **kwargs: worker)
    stderr = StringIO()

    assert cli.main(_argv(tmp_path), stderr=stderr) != 0
    assert stderr.getvalue().count("\n") == 1
    assert stderr.getvalue().startswith("error: ")
