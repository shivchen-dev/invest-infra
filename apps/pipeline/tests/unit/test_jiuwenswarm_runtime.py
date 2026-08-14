from __future__ import annotations

from pathlib import Path

from invest_domain.research import ResearchPlaybook
from invest_pipeline.adapters.jiuwenswarm import JiuwenSwarmResearchRunner
from invest_pipeline.jiuwenswarm_runtime import (
    build_jiuwenswarm_orchestration_service,
)


class _Transport:
    def submit(self, _request):  # pragma: no cover - assembly test never submits
        raise AssertionError("transport must not be called during assembly")


def test_builds_real_runner_with_injected_transport(tmp_path: Path) -> None:
    playbook = ResearchPlaybook(
        playbook_key="etf_medium_term_assessment",
        playbook_version="v0.1.0",
    )

    service = build_jiuwenswarm_orchestration_service(
        database_url="sqlite+pysqlite:///:memory:",
        helper_path=tmp_path / "helper.py",
        workspace="/runtime/workspace/jiuwenswarm",
        artifact_root=tmp_path / "artifacts",
        playbook=playbook,
        transport=_Transport(),
    )

    assert isinstance(service._runner, JiuwenSwarmResearchRunner)
    assert service._runner.runner_key == "jiuwenswarm-runner-v1"
    assert service._playbook == playbook
