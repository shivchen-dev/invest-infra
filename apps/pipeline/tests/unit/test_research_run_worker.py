from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_pipeline.research_run_worker import (
    ResearchRunWorker,
    ResearchRunWorkerInputError,
)

_RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
_CASE_ID = UUID("22222222-2222-4222-8222-222222222222")
_PACK_ID = UUID("44444444-4444-4444-8444-444444444444")


def _run() -> ResearchRun:
    return ResearchRun(
        run_id=_RUN_ID,
        case_id=_CASE_ID,
        evidence_pack_id=_PACK_ID,
        runner_key="jiuwenswarm-runner-v1",
        playbook_key="etf_medium_term_assessment",
        status=ResearchRunStatus.QUEUED,
        attempt=1,
    )


@dataclass
class _Runs:
    run: ResearchRun | None

    def get(self, _run_id):
        return self.run

    def list_recent(self, *, limit, offset):
        return [self.run] if self.run is not None else []


@dataclass
class _Uow:
    run: ResearchRun | None
    commits: int = 0

    def __post_init__(self):
        self.research_runs = _Runs(self.run)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self):
        self.commits += 1


class _Orchestration:
    def __init__(self):
        self.calls = []

    def execute(self, run_id):
        self.calls.append(run_id)
        return "outcome"


def test_run_once_delegates_queued_run():
    uow = _Uow(_run())
    orchestration = _Orchestration()
    worker = ResearchRunWorker(lambda: uow, orchestration)

    assert worker.run_once(_RUN_ID) == "outcome"
    assert orchestration.calls == [_RUN_ID]
    assert uow.commits == 1


def test_run_next_returns_none_when_queue_is_empty():
    uow = _Uow(None)
    worker = ResearchRunWorker(lambda: uow, _Orchestration())

    assert worker.run_next() is None
    assert uow.commits == 1


def test_run_once_rejects_non_queued_run():
    run = _run().start(occurred_at=datetime(2026, 8, 14, tzinfo=UTC))
    uow = _Uow(run)
    worker = ResearchRunWorker(lambda: uow, _Orchestration())

    with pytest.raises(ResearchRunWorkerInputError, match="not queued"):
        worker.run_once(_RUN_ID)
