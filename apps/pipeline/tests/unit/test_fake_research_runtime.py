"""Gate 3 Slice E runtime-builder tests.

Focused unit tests use :func:`pytest.MonkeyPatch` to replace the
SQLAlchemy engine / session factory and the :class:`SqlAlchemyUnitOfWork`
class so the builders can be exercised without a live database. The
tests prove the builder wires the :class:`FakeResearchRunner` and
:class:`ResearchPlaybook` into the
:class:`ResearchOrchestrationService` and that injected
``clock`` / ``raise_exc`` parameters are preserved end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from invest_domain.research import ResearchPlaybook
from invest_pipeline import fake_research_runtime as runtime
from invest_pipeline.adapters.jiuwenswarm import (
    JiuwenSwarmRemoteFailureError,
)
from invest_pipeline.fake_research_runner import (
    DEFAULT_FAKE_RUNNER_ADAPTER_VERSION,
    FAKE_RUNNER_KEY,
    FakeResearchRunner,
)
from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationService,
)
from invest_pipeline.research_run_worker import ResearchRunWorker

_PLAYBOOK = ResearchPlaybook(
    playbook_key="etf_medium_term_assessment",
    playbook_version="v0.1.0",
)


class _FakeEngine:
    """Stand-in for a SQLAlchemy ``Engine`` — never used by the builders."""


class _FakeSessionFactory:
    """Stand-in for a SQLAlchemy ``sessionmaker`` — never used by the builders."""


class _FakeUoW:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` capturing constructor calls."""

    instances: list[_FakeSessionFactory] = []

    def __init__(self, sessions: _FakeSessionFactory) -> None:
        type(self).instances.append(sessions)


@pytest.fixture
def patched_storage(monkeypatch: pytest.MonkeyPatch) -> _FakeSessionFactory:
    """Replace SQLAlchemy construction seams with in-memory fakes.

    Returns the fake ``sessionmaker`` so tests can assert that
    :func:`fake_research_runtime._build_components` threaded it through
    the :class:`SqlAlchemyUnitOfWork` factory untouched.
    """

    session_maker = _FakeSessionFactory()
    _FakeUoW.instances = []

    monkeypatch.setattr(runtime, "build_engine", lambda _url: _FakeEngine())
    monkeypatch.setattr(
        runtime,
        "session_factory",
        lambda _engine: session_maker,
    )
    monkeypatch.setattr(runtime, "SqlAlchemyUnitOfWork", _FakeUoW)
    return session_maker


class TestOrchestrationServiceBuilder:
    """``build_fake_research_orchestration_service`` wires the Fake runner."""

    def test_returns_orchestration_service_with_fake_runner(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
        )

        assert isinstance(service, ResearchOrchestrationService)
        assert isinstance(service._runner, FakeResearchRunner)
        assert service._runner.runner_key == FAKE_RUNNER_KEY
        assert service._runner.adapter_version == DEFAULT_FAKE_RUNNER_ADAPTER_VERSION
        assert service._playbook == _PLAYBOOK

    def test_orchestration_uow_factory_uses_fake_uow(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
        )

        uow = service._uow_factory()

        assert isinstance(uow, _FakeUoW)
        assert _FakeUoW.instances == [patched_storage]

    def test_orchestration_default_clock_is_timezone_aware_utc(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
        )

        sample = service._clock()

        assert isinstance(sample, datetime)
        assert sample.tzinfo is not None
        assert sample.tzinfo.utcoffset(sample) is not None
        assert sample.tzinfo.utcoffset(sample).total_seconds() == 0.0

    def test_orchestration_preserves_injected_clock(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        fixed = datetime(2026, 3, 6, 7, 6, tzinfo=UTC)

        def clock() -> datetime:
            return fixed

        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
            clock=clock,
        )

        assert service._clock is clock
        assert service._clock() == fixed

    def test_orchestration_propagates_raise_exc_to_runner(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        failure = JiuwenSwarmRemoteFailureError("injected by test")

        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
            raise_exc=failure,
        )

        assert service._runner.raise_exc is failure

    def test_orchestration_happy_path_when_raise_exc_is_none(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        service = runtime.build_fake_research_orchestration_service(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
            raise_exc=None,
        )

        assert service._runner.raise_exc is None

    def test_orchestration_rejects_blank_database_url(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        with pytest.raises(ValueError, match="database_url"):
            runtime.build_fake_research_orchestration_service(
                database_url="",
                playbook=_PLAYBOOK,
            )

    def test_orchestration_rejects_non_playbook(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        with pytest.raises(TypeError, match="playbook"):
            runtime.build_fake_research_orchestration_service(
                database_url="sqlite+pysqlite:///:memory:",
                playbook=object(),  # type: ignore[arg-type]
            )


class TestWorkerBuilder:
    """``build_fake_research_worker`` wires a Fake-runner worker."""

    def test_returns_worker_with_orchestration_and_uow_factory(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        worker = runtime.build_fake_research_worker(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
        )

        assert isinstance(worker, ResearchRunWorker)
        assert isinstance(worker.orchestration, ResearchOrchestrationService)
        assert isinstance(worker.orchestration._runner, FakeResearchRunner)

        uow = worker.uow_factory()
        assert isinstance(uow, _FakeUoW)
        assert _FakeUoW.instances == [patched_storage]

    def test_worker_preserves_injected_clock_and_failure(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        fixed = datetime(2026, 3, 6, 7, 6, tzinfo=UTC)
        failure = JiuwenSwarmRemoteFailureError("worker failure")

        worker = runtime.build_fake_research_worker(
            database_url="sqlite+pysqlite:///:memory:",
            playbook=_PLAYBOOK,
            clock=lambda: fixed,
            raise_exc=failure,
        )

        assert worker.orchestration._clock() == fixed
        assert worker.orchestration._runner.raise_exc is failure
        assert worker.orchestration._playbook == _PLAYBOOK

    def test_worker_rejects_non_playbook(
        self, patched_storage: _FakeSessionFactory
    ) -> None:
        with pytest.raises(TypeError, match="playbook"):
            runtime.build_fake_research_worker(
                database_url="sqlite+pysqlite:///:memory:",
                playbook="not-a-playbook",  # type: ignore[arg-type]
            )


def test_module_exports_documented_public_seams() -> None:
    """The module advertises the two builders the spec requires."""

    assert hasattr(runtime, "build_fake_research_orchestration_service")
    assert hasattr(runtime, "build_fake_research_worker")
    assert "build_fake_research_orchestration_service" in runtime.__all__
    assert "build_fake_research_worker" in runtime.__all__


def test_module_does_not_import_jiuwensarm() -> None:
    """The runtime builder must not depend on the retired JiuwenSwarm adapter."""

    module_globals: dict[str, Any] = vars(runtime)
    forbidden = (
        "JiuwenSwarmResearchRunner",
        "JiuwenSwarmCliGatewayTransport",
        "JiuwenSwarmGatewayTransport",
        "build_jiuwenswarm_orchestration_service",
        "build_jiuwenswarm_worker",
    )
    leaked = [name for name in forbidden if name in module_globals]
    assert leaked == []