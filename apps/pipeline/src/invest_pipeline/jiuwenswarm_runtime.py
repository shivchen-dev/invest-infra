"""Historical compatibility root for the retired JiuwenSwarm runner.

The adapter and orchestration services remain dependency-injected and easy to
test. Current plans must not depend on this module for production execution or
acceptance; it remains only to preserve the existing integration boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from invest_domain.research import ResearchPlaybook
from invest_storage.database import build_engine, session_factory
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

from invest_pipeline.adapters.jiuwenswarm import (
    JiuwenSwarmCliGatewayTransport,
    JiuwenSwarmCliSettings,
    JiuwenSwarmGatewayTransport,
    JiuwenSwarmResearchRunner,
    default_python_executable,
)
from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationService,
)
from invest_pipeline.research_run_worker import ResearchRunWorker

__all__ = [
    "build_jiuwenswarm_orchestration_service",
    "build_jiuwenswarm_worker",
]


def build_jiuwenswarm_orchestration_service(
    *,
    database_url: str,
    helper_path: Path,
    workspace: str,
    artifact_root: Path,
    playbook: ResearchPlaybook,
    python_executable: str | None = None,
    mode: str = "default",
    timeout_seconds: float = 900.0,
    idle_timeout_seconds: float = 120.0,
    adapter_version: str = "jiuwenswarm-adapter-v1",
    transport: JiuwenSwarmGatewayTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ResearchOrchestrationService:
    """Build the retired Jiuwen compatibility orchestrator.

    ``transport`` is an explicit injection seam for deterministic tests.  When
    omitted, the validated CLI transport is constructed and remains the only
    component allowed to invoke the external helper.
    """

    orchestration, _uow_factory = _build_components(
        database_url=database_url,
        helper_path=helper_path,
        workspace=workspace,
        artifact_root=artifact_root,
        playbook=playbook,
        python_executable=python_executable,
        mode=mode,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        adapter_version=adapter_version,
        transport=transport,
        clock=clock,
    )
    return orchestration


def build_jiuwenswarm_worker(
    **kwargs,
) -> ResearchRunWorker:
    """Build the historical compatibility worker for queued ResearchRun rows."""

    orchestration, uow_factory = _build_components(**kwargs)
    return ResearchRunWorker(uow_factory=uow_factory, orchestration=orchestration)


def _build_components(**kwargs):
    playbook = kwargs["playbook"]
    if not isinstance(playbook, ResearchPlaybook):
        raise TypeError("playbook must be a ResearchPlaybook")
    transport = kwargs.get("transport")
    if transport is None:
        transport = JiuwenSwarmCliGatewayTransport(
            settings=JiuwenSwarmCliSettings(
                helper_path=kwargs["helper_path"],
                workspace=kwargs["workspace"],
                artifact_root=kwargs["artifact_root"],
                python_executable=kwargs.get("python_executable") or default_python_executable(),
                mode=kwargs.get("mode", "default"),
                timeout_seconds=kwargs.get("timeout_seconds", 900.0),
                idle_timeout_seconds=kwargs.get("idle_timeout_seconds", 120.0),
            )
        )
    engine = build_engine(kwargs["database_url"])
    database_sessions = session_factory(engine)

    def uow_factory():
        return SqlAlchemyUnitOfWork(database_sessions)

    orchestration = ResearchOrchestrationService(
        runner=JiuwenSwarmResearchRunner(
            transport=transport,
            adapter_version=kwargs.get("adapter_version", "jiuwenswarm-adapter-v1"),
        ),
        playbook=playbook,
        uow_factory=uow_factory,
        clock=kwargs.get("clock") or (lambda: datetime.now(UTC)),
    )
    return orchestration, uow_factory
