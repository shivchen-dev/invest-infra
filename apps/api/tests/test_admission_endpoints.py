from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from invest_api.dependencies import get_observation_admission_command_service
from invest_api.main import app


def _body(key: str = "admission-001"):
    return {
        "idempotency_key": key,
        "identity_ok": True,
        "freshness_ok": True,
        "unit_ok": True,
        "internal_cross_check_ok": True,
    }


def test_admission_command_is_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(
        "invest_api.routers.admission.get_settings",
        lambda: SimpleNamespace(stage4d_admission_commands_enabled=False),
    )

    response = client.post(
        f"/api/v1/external-observations/{uuid4()}/admission-decisions",
        json=_body(),
    )

    assert response.status_code == 404
    assert "disabled" in response.json()["detail"]


def test_admission_command_checks_idempotency_header(client, monkeypatch):
    monkeypatch.setattr(
        "invest_api.routers.admission.get_settings",
        lambda: SimpleNamespace(stage4d_admission_commands_enabled=True),
    )
    service = MagicMock()
    app.dependency_overrides[get_observation_admission_command_service] = lambda: service
    try:
        response = client.post(
            f"/api/v1/external-observations/{uuid4()}/admission-decisions",
            headers={"Idempotency-Key": "different-key"},
            json=_body("request-key"),
        )
    finally:
        app.dependency_overrides.pop(get_observation_admission_command_service, None)

    assert response.status_code == 409
    service.decide.assert_not_called()
