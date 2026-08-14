"""Composition root for the production JiuwenSwarm research runner.

The adapter and orchestration services remain dependency-injected and easy to
test.  This module is the one explicit production assembly point: SQLAlchemy
UoW, CLI transport, JiuwenSwarm runner, playbook, and lifecycle clock are
wired together here.
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

__all__ = ["build_jiuwenswarm_orchestration_service"]


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
    """Build a production Research orchestrator with a real Jiuwen runner.

    ``transport`` is an explicit injection seam for deterministic tests.  When
    omitted, the validated CLI transport is constructed and remains the only
    component allowed to invoke the external helper.
    """

    if not isinstance(playbook, ResearchPlaybook):
        raise TypeError("playbook must be a ResearchPlaybook")
    if transport is None:
        transport = JiuwenSwarmCliGatewayTransport(
            settings=JiuwenSwarmCliSettings(
                helper_path=helper_path,
                workspace=workspace,
                artifact_root=artifact_root,
                python_executable=python_executable or default_python_executable(),
                mode=mode,
                timeout_seconds=timeout_seconds,
                idle_timeout_seconds=idle_timeout_seconds,
            )
        )

    engine = build_engine(database_url)
    database_sessions = session_factory(engine)
    runner = JiuwenSwarmResearchRunner(
        transport=transport,
        adapter_version=adapter_version,
    )
    return ResearchOrchestrationService(
        runner=runner,
        playbook=playbook,
        uow_factory=lambda: SqlAlchemyUnitOfWork(database_sessions),
        clock=clock or (lambda: datetime.now(UTC)),
    )
