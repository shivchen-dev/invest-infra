"""Real-UoW runtime wiring for the deterministic :class:`FakeResearchRunner`.

This module is the Gate 3 Slice E companion to the retired
:class:`invest_pipeline.jiuwenswarm_runtime` compatibility builder: it
constructs the same SQLAlchemy-backed unit-of-work factory, but plugs
the deterministic Slice D :class:`FakeResearchRunner` (constructed via
:func:`invest_pipeline.fake_research_runner.build_fake_research_runner`)
into :class:`ResearchOrchestrationService` and
:class:`ResearchRunWorker` instead of the external JiuwenSwarm adapter.

The builder is deliberately minimal — no subprocess, network, or
JiuwenSwarm import is required at runtime — and exposes two public
factories that mirror the historical
:func:`invest_pipeline.jiuwenswarm_runtime.build_jiuwenswarm_orchestration_service`
and :func:`invest_pipeline.jiuwenswarm_runtime.build_jiuwenswarm_worker`
shape so callers can swap the runner adapter without rewriting wiring
code.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from invest_domain.research import ResearchPlaybook
from invest_storage.database import build_engine, session_factory
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

from invest_pipeline.fake_research_runner import (
    FakeResearchRunner,
    build_fake_research_runner,
)
from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationService,
)
from invest_pipeline.research_run_worker import ResearchRunWorker

__all__ = [
    "build_fake_research_orchestration_service",
    "build_fake_research_worker",
]


def _default_clock() -> Callable[[], datetime]:
    """Return a timezone-aware UTC clock used when the caller does not inject one."""

    return lambda: datetime.now(UTC)


def _build_components(
    *,
    database_url: str,
    playbook: ResearchPlaybook,
    clock: Callable[[], datetime] | None,
    raise_exc: Exception | None,
) -> tuple[
    ResearchOrchestrationService,
    Callable[[], SqlAlchemyUnitOfWork],
    FakeResearchRunner,
]:
    """Return the orchestration service, UoW factory, and runner built from ``kwargs``.

    Centralises the wiring so both the orchestration-only and the
    worker-returning factories share a single construction path. Tests
    rely on this helper by monkeypatching
    :func:`invest_storage.database.build_engine` /
    :func:`invest_storage.database.session_factory` /
    :class:`invest_storage.unit_of_work.SqlAlchemyUnitOfWork` so a
    live database connection is never required.
    """

    if not isinstance(database_url, str) or not database_url:
        raise ValueError("database_url must be a non-empty string")
    if not isinstance(playbook, ResearchPlaybook):
        raise TypeError("playbook must be a ResearchPlaybook")

    engine = build_engine(database_url)
    database_sessions = session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database_sessions)

    runner = build_fake_research_runner(raise_exc=raise_exc)

    orchestration = ResearchOrchestrationService(
        runner=runner,
        playbook=playbook,
        uow_factory=uow_factory,
        clock=clock if clock is not None else _default_clock(),
    )
    return orchestration, uow_factory, runner


def build_fake_research_orchestration_service(
    *,
    database_url: str,
    playbook: ResearchPlaybook,
    clock: Callable[[], datetime] | None = None,
    raise_exc: Exception | None = None,
) -> ResearchOrchestrationService:
    """Build a :class:`ResearchOrchestrationService` wired to the Fake runner.

    The returned service uses an in-process SQLAlchemy
    :class:`SqlAlchemyUnitOfWork` factory, the supplied ``playbook``,
    and the deterministic :class:`FakeResearchRunner`. ``clock`` and
    ``raise_exc`` are forwarded verbatim so tests can inject a fixed
    clock or a deterministic failure without monkeypatching internals.
    """

    orchestration, _uow_factory, _runner = _build_components(
        database_url=database_url,
        playbook=playbook,
        clock=clock,
        raise_exc=raise_exc,
    )
    return orchestration


def build_fake_research_worker(
    *,
    database_url: str,
    playbook: ResearchPlaybook,
    clock: Callable[[], datetime] | None = None,
    raise_exc: Exception | None = None,
) -> ResearchRunWorker:
    """Build a :class:`ResearchRunWorker` wired to the Fake runner.

    The returned worker shares the SQLAlchemy UoW factory and
    :class:`ResearchOrchestrationService` constructed by
    :func:`_build_components` so a queued :class:`ResearchRun` row can
    be loaded in Tx1 and driven to a terminal state by the Fake
    runner in a single call site.
    """

    orchestration, uow_factory, _runner = _build_components(
        database_url=database_url,
        playbook=playbook,
        clock=clock,
        raise_exc=raise_exc,
    )
    return ResearchRunWorker(uow_factory=uow_factory, orchestration=orchestration)