import os
from pathlib import Path

import pytest
from invest_pipeline.integrations.workbuddy_stage_worker import (
    STAGES,
    StagePackageOutcome,
    StagePackageWorker,
)


def make_worker(tmp_path: Path, stage: str = "research") -> StagePackageWorker:
    return StagePackageWorker(tmp_path, stage)


def test_all_stage_paths_are_created_under_stage_root(tmp_path: Path) -> None:
    for stage in STAGES:
        worker = make_worker(tmp_path, stage)
        assert worker.root == tmp_path / "workbuddy" / stage
        directories = (
            worker.inbox, worker.processing, worker.results, worker.archive, worker.failed
        )
        assert all(path.is_dir() for path in directories)


def test_discover_ready_filters_symlinks_and_sorts(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    names = (
        "b.ready", "a.ready", "x.txt", ".hidden.ready",
        "bad/name.ready", "bad?.ready", "empty.ready",
    )
    for name in names:
        if "/" in name:
            continue
        (worker.results / name).mkdir()
    (worker.results / "link.ready").symlink_to(worker.results / "a.ready", target_is_directory=True)
    assert [path.name for path in worker.discover_ready()] == ["a.ready", "b.ready", "empty.ready"]


def test_process_once_success_archives_package(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    (worker.results / "task-1.ready").mkdir()
    seen = []
    outcomes = worker.process_once(lambda stage, path: seen.append((stage, path.name)))
    assert outcomes[0].status == "success"
    assert outcomes[0].task_id == "task-1"
    assert seen == [("research", "task-1")]
    assert (worker.archive / "task-1").is_dir()


def test_handler_failure_moves_package_to_failed(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    (worker.results / "task.ready").mkdir()
    outcomes = worker.process_once(lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert outcomes[0].status == "failed"
    assert outcomes[0].error == "boom"
    assert (worker.failed / "task").is_dir()


def test_claim_conflict_does_not_overwrite(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    source = worker.results / "task.ready"
    source.mkdir()
    destination = worker.processing / "task"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        worker.claim(source)
    assert source.is_dir()
    assert destination.is_dir()
    assert list(destination.iterdir()) == []


def test_finish_conflict_does_not_overwrite(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    package = worker.processing / "task"
    package.mkdir()
    destination = worker.archive / "task"
    destination.mkdir()
    (destination / "keep").touch()
    with pytest.raises(FileExistsError):
        worker.finish(package, success=True)
    assert package.is_dir() and (destination / "keep").exists()


def test_paths_must_be_direct_children_and_symlink_is_rejected(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = worker.results / "escape.ready"
    link.symlink_to(outside, target_is_directory=True)
    assert link not in worker.discover_ready()
    with pytest.raises(ValueError):
        worker.claim(worker.results / "../outside")


def test_process_once_finish_conflict_records_outcome_and_preserves_state(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    (worker.results / "task-1.ready").mkdir()
    archive_destination = worker.archive / "task-1"
    archive_destination.mkdir()
    (archive_destination / "keep").touch()
    handler_calls: list[tuple[str, str]] = []
    outcomes = worker.process_once(
        lambda stage, path: handler_calls.append((stage, path.name))
    )
    assert len(outcomes) == 1
    assert outcomes[0].task_id == "task-1"
    assert outcomes[0].status == "finish_conflict"
    assert outcomes[0].error is not None
    assert "task-1" in outcomes[0].error
    assert handler_calls == [("research", "task-1")]
    assert (archive_destination / "keep").exists()
    assert archive_destination.is_dir()
    assert (worker.processing / "task-1").is_dir()
    assert not (worker.failed / "task-1").exists()


def test_process_once_finish_conflict_continues_to_next_package(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    (worker.results / "alpha.ready").mkdir()
    (worker.results / "beta.ready").mkdir()
    archive_destination = worker.archive / "alpha"
    archive_destination.mkdir()
    handler_calls: list[str] = []
    outcomes = worker.process_once(
        lambda stage, path: handler_calls.append(path.name)
    )
    by_task = {outcome.task_id: outcome for outcome in outcomes}
    assert set(by_task) == {"alpha", "beta"}
    assert by_task["alpha"].status == "finish_conflict"
    assert by_task["beta"].status == "success"
    assert handler_calls == ["alpha", "beta"]
    assert (worker.archive / "alpha").is_dir()
    assert (worker.archive / "beta").is_dir()
    assert (worker.processing / "alpha").is_dir()


def test_process_once_finish_conflict_propagates_non_fileexists_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path)
    (worker.results / "task.ready").mkdir()
    handler_calls: list[str] = []

    def boom(package: Path, success: bool) -> Path:
        raise PermissionError(13, "permission denied", str(package))

    monkeypatch.setattr(worker, "finish", boom)
    with pytest.raises(PermissionError):
        worker.process_once(lambda stage, path: handler_calls.append(path.name))
    assert handler_calls == ["task"]
    assert (worker.processing / "task").is_dir()


def test_recover_once_resumes_crash_residue_without_automatic_stealing(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    residue = worker.processing / "interrupted"
    residue.mkdir()
    (residue / "payload.json").write_text("{}")
    seen: list[tuple[str, str]] = []

    assert worker.process_once(lambda stage, path: seen.append((stage, path.name))) == ()
    assert residue.is_dir()

    outcomes = worker.recover_once(
        lambda stage, path: seen.append((stage, path.name))
    )

    assert outcomes == (StagePackageOutcome("interrupted", "success", None),)
    assert seen == [("research", "interrupted")]
    assert (worker.archive / "interrupted" / "payload.json").is_file()
    assert not residue.exists()


def test_recover_once_ignores_invalid_and_symlink_residue(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").touch()
    (worker.processing / "linked").symlink_to(outside, target_is_directory=True)
    (worker.processing / "bad name").mkdir()
    (worker.processing / "regular-file").touch()
    seen: list[str] = []

    assert worker.recover_once(lambda stage, path: seen.append(path.name)) == ()
    assert seen == []
    assert (outside / "keep").is_file()
    assert (worker.processing / "linked").is_symlink()
    assert (worker.processing / "bad name").is_dir()
    assert (worker.processing / "regular-file").is_file()


@pytest.mark.parametrize("destination_name", ["archive", "failed"])
def test_recover_once_conflict_does_not_overwrite(
    tmp_path: Path, destination_name: str
) -> None:
    worker = make_worker(tmp_path)
    residue = worker.processing / "task"
    residue.mkdir()
    destination = getattr(worker, destination_name) / "task"
    destination.mkdir()
    (destination / "keep").touch()

    if destination_name == "archive":
        outcomes = worker.recover_once(lambda *_: None)
        assert outcomes[0].status == "finish_conflict"
    else:
        outcomes = worker.recover_once(
            lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert outcomes[0].status == "failed"
        assert outcomes[0].error is not None
        assert "finish failed" in outcomes[0].error

    assert residue.is_dir()
    assert (destination / "keep").is_file()


def test_recover_once_failure_does_not_block_later_safe_residue(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    (worker.processing / "alpha").mkdir()
    (worker.processing / "beta").mkdir()
    (worker.failed / "alpha").mkdir()
    seen: list[str] = []

    def handler(stage: str, path: Path) -> None:
        seen.append(path.name)
        if path.name == "alpha":
            raise RuntimeError("boom")

    outcomes = worker.recover_once(handler)

    assert [outcome.task_id for outcome in outcomes] == ["alpha", "beta"]
    assert [outcome.status for outcome in outcomes] == ["failed", "success"]
    assert seen == ["alpha", "beta"]
    assert (worker.processing / "alpha").is_dir()
    assert (worker.archive / "beta").is_dir()


def test_stale_discovery_loser_records_conflict_and_processes_later_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    winner = make_worker(tmp_path)
    loser = make_worker(tmp_path)
    alpha = winner.results / "alpha.ready"
    beta = winner.results / "beta.ready"
    alpha.mkdir()
    beta.mkdir()
    stale_discovery = (alpha, beta)
    loser_seen: list[str] = []
    loser_outcomes: tuple[StagePackageOutcome, ...] = ()

    monkeypatch.setattr(loser, "discover_ready", lambda: stale_discovery)

    def winner_handler(stage: str, path: Path) -> None:
        nonlocal loser_outcomes
        if path.name == "alpha":
            loser_outcomes = loser.process_once(
                lambda loser_stage, loser_path: loser_seen.append(loser_path.name)
            )

    winner.process_once(winner_handler)

    assert [outcome.status for outcome in loser_outcomes] == [
        "claim_conflict",
        "success",
    ]
    assert loser_seen == ["beta"]
    assert (winner.archive / "alpha").is_dir()
    assert (winner.archive / "beta").is_dir()


def test_handler_lock_blocks_recovery_until_handler_returns(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    recovering_worker = make_worker(tmp_path)
    (worker.results / "task.ready").mkdir()
    recovery_calls: list[str] = []
    recovery_outcomes: tuple[StagePackageOutcome, ...] = ()

    def handler(stage: str, path: Path) -> None:
        nonlocal recovery_outcomes
        recovery_outcomes = recovering_worker.recover_once(
            lambda recovery_stage, recovery_path: recovery_calls.append(
                recovery_path.name
            )
        )

    assert worker.process_once(handler)[0].status == "success"
    assert recovery_calls == []
    assert len(recovery_outcomes) == 1
    assert recovery_outcomes[0].status == "active"


def test_recover_skips_explicitly_locked_package_then_recovers_it(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    residue = worker.processing / "task"
    residue.mkdir()
    lock_fd = worker._acquire_package_lock(residue)
    calls: list[str] = []

    try:
        outcomes = worker.recover_once(
            lambda stage, path: calls.append(path.name)
        )
        assert outcomes[0].status == "active"
        assert calls == []
        assert residue.is_dir()
    finally:
        os.close(lock_fd)

    assert worker.recover_once(lambda stage, path: calls.append(path.name))[0].status == "success"
    assert calls == ["task"]


def test_recovery_lock_is_released_after_finish_conflict(tmp_path: Path) -> None:
    worker = make_worker(tmp_path)
    residue = worker.processing / "task"
    residue.mkdir()
    conflict = worker.archive / "task"
    conflict.mkdir()

    assert worker.recover_once(lambda *_: None)[0].status == "finish_conflict"
    conflict.rmdir()

    assert worker.recover_once(lambda *_: None)[0].status == "success"
    assert (worker.archive / "task").is_dir()


def test_fifo_lock_is_rejected_without_blocking_or_stopping_process_batch(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    unsafe = worker.results / "alpha.ready"
    unsafe.mkdir()
    os.mkfifo(unsafe / ".workbuddy.lock")
    (worker.results / "beta.ready").mkdir()
    calls: list[str] = []

    outcomes = worker.process_once(lambda stage, path: calls.append(path.name))

    assert [outcome.status for outcome in outcomes] == ["unsafe_package", "success"]
    assert calls == ["beta"]
    assert unsafe.is_dir()
    assert (worker.archive / "beta").is_dir()


def test_fifo_lock_is_rejected_without_blocking_or_stopping_recovery_batch(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path)
    unsafe = worker.processing / "alpha"
    unsafe.mkdir()
    os.mkfifo(unsafe / ".workbuddy.lock")
    (worker.processing / "beta").mkdir()
    calls: list[str] = []

    outcomes = worker.recover_once(lambda stage, path: calls.append(path.name))

    assert [outcome.status for outcome in outcomes] == ["unsafe_residue", "success"]
    assert calls == ["beta"]
    assert unsafe.is_dir()
    assert (worker.archive / "beta").is_dir()
