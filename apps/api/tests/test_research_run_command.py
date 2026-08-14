from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from invest_api.dependencies import get_research_run_command_service
from invest_api.main import app
from invest_domain.research.research_run import ResearchRun


class _Service:
    def queue(self, *, case_id, evidence_pack_id, playbook):
        return (
            ResearchRun.create(
                case_id=case_id,
                evidence_pack_id=evidence_pack_id,
                runner_key="jiuwenswarm-runner-v1",
                playbook_key=playbook.playbook_key,
            ),
            False,
        )


def test_queue_research_run_command_returns_queued_run() -> None:
    service = _Service()
    app.dependency_overrides[get_research_run_command_service] = lambda: service
    client = TestClient(app)
    case_id = UUID("22222222-2222-4222-8222-222222222222")
    pack_id = UUID("33333333-3333-4333-8333-333333333333")

    try:
        response = client.post(
            f"/api/v1/research-cases/{case_id}/runs",
            json={
                "evidence_pack_id": str(pack_id),
                "playbook_key": "etf_medium_term_assessment",
                "playbook_version": "v0.1.0",
            },
        )
    finally:
        app.dependency_overrides.pop(get_research_run_command_service, None)

    assert response.status_code == 201
    body = response.json()
    assert body["run"]["status"] == "queued"
    assert body["run"]["case_id"] == str(case_id)
    assert body["idempotent"] is False
