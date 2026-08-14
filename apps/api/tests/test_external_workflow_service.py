from types import SimpleNamespace
from uuid import uuid4

from invest_api.application.external_workflows import ExternalWorkflowQueryService


class _Runs:
    def __init__(self, run):
        self.run = run

    def list_recent(self, *, limit, offset):
        return [self.run][offset : offset + limit]

    def get_by_id(self, run_id):
        return self.run if run_id == self.run.run_id else None


class _Children:
    def __init__(self, items):
        self.items = items

    def list_by_run(self, run_id, *, limit, offset):
        return self.items[offset : offset + limit]

    def list_recent(self, *, status, limit, offset):
        return self.items[offset : offset + limit]

    def get_by_id(self, artifact_id):
        if self.items and artifact_id == getattr(self.items[0], "artifact_id", None):
            return self.items[0]
        return None


def test_external_workflow_query_service_delegates_read_contract():
    run_id = uuid4()
    run = SimpleNamespace(run_id=run_id)
    artifact = SimpleNamespace(run_id=run_id)
    observation = SimpleNamespace(run_id=run_id)
    service = ExternalWorkflowQueryService(
        run_repository=_Runs(run),
        artifact_repository=_Children([artifact]),
        observation_repository=_Children([observation]),
    )

    assert service.list_runs(limit=10, offset=0) == [run]
    assert service.get_run(run_id) is run
    assert service.list_artifacts(run_id, limit=10, offset=0) == [artifact]
    assert service.list_observations(run_id, limit=10, offset=0) == [observation]
    assert service.list_radar(status=None, limit=10, offset=0) == [observation]
    assert service.get_artifact(uuid4()) is None
