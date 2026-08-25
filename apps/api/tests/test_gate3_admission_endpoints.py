"""Gate 3 Slice B — server-side admission verification.

The endpoint under test is
``POST /api/v1/external-observations/{observation_id}/admission-decisions``,
which is the public seam for the Stage 4D observation-admission command
behind the ``stage4d_admission_commands_enabled`` feature flag. The
production write flag is left at its default (``False``) by these
tests; the contract is exercised by monkeypatching
``invest_api.routers.admission.get_settings`` to return an enabled
settings object and by overriding
``get_observation_admission_command_service`` with a ``MagicMock`` so
no real database is touched.

Slice B hardens the seam:

* the request schema exposes only the idempotency key — no verification
  booleans can be supplied by the HTTP caller;
* the router delegates only ``observation_id`` and ``idempotency_key``
  to the application service (never constructs
  :class:`AdmissionVerification` from HTTP input);
* the application service computes identity / freshness / unit /
  internal cross-check / conflict from the loaded
  :class:`ExternalObservation`, an injectable clock, and the
  repository's recent observations;
* the existing default-deny and Idempotency-Key mismatch paths remain
  green.

The decision matrix and the response / error contract proven here:

* successful response serialization for the four admission decisions
  (``admitted``, ``corroborated``, ``rejected``, ``conflict``);
* the ``idempotent=True`` response path and the delegation contract
  (the service is called with only ``observation_id`` and
  ``idempotency_key``);
* service :class:`LookupError` mapping to HTTP 404;
* service :class:`ValueError` mapping to HTTP 409;
* :class:`Idempotency-Key` header mismatch mapping to HTTP 409 *and*
  short-circuiting the service call entirely;
* OpenAPI keeps the endpoint POST-only, references the
  ``AdmissionDecisionRequest`` / ``AdmissionDecisionResponse``
  schemas, and exposes only ``idempotency_key`` on the request body;
* the request schema silently ignores the removed verification
  booleans rather than 422-ing on them.

The default-deny (feature flag off) behaviour is already covered by
``test_admission_endpoints.py::test_admission_command_is_disabled_by_default``
so this slice reuses the existing assertion rather than duplicating
it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.application.admission import (
    AdmissionCommandResult,
    ObservationAdmissionCommandService,
)
from invest_api.dependencies import get_observation_admission_command_service
from invest_api.main import app
from invest_domain.integration import AdmissionStatus, ExternalObservation

ADMISSION_PATH_TEMPLATE = "/api/v1/external-observations/{observation_id}/admission-decisions"

OBSERVED_AT = datetime(2026, 8, 14, 10, tzinfo=UTC)
AS_OF = date(2026, 8, 14)
BUSINESS_TODAY = date(2026, 8, 14)


@pytest.fixture()
def enabled_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip the Stage 4D feature flag on for the duration of a test.

    The production write flag remains default-deny at runtime; this
    fixture only enables the seam so the contract can be proven end
    to end without the database.
    """

    monkeypatch.setattr(
        "invest_api.routers.admission.get_settings",
        lambda: SimpleNamespace(stage4d_admission_commands_enabled=True),
    )


@pytest.fixture()
def admission_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a mock :class:`ObservationAdmissionCommandService`.

    Overrides :func:`invest_api.dependencies.get_observation_admission_command_service`
    so the admission router receives a ``MagicMock`` that quacks like
    the application service. Endpoint tests configure return values
    and side effects on ``admission_service.decide``; the service-level
    behaviour is owned by
    :class:`TestObservationAdmissionCommandServiceServerSideVerification`
    which constructs the real service against an in-memory repository.
    """

    mock = MagicMock(name="ObservationAdmissionCommandService")
    app.dependency_overrides[get_observation_admission_command_service] = lambda: mock
    try:
        yield mock
    finally:
        app.dependency_overrides.pop(get_observation_admission_command_service, None)


def _observation(
    *,
    status: AdmissionStatus,
    reason: str,
    observation_id: UUID | None = None,
) -> ExternalObservation:
    """Build a minimal :class:`ExternalObservation` carrying admission metadata."""

    return ExternalObservation(
        observation_id=observation_id or uuid4(),
        run_id=uuid4(),
        observed_at=OBSERVED_AT,
        as_of=AS_OF,
        source_uri="https://example.test/run-1/observation.json",
        producer="workbuddy",
        payload={"score": 1},
        admission_status=status,
        metadata={"admission": {"reason": reason}},
    )


def _body(*, idempotency_key: str = "admission-001") -> dict[str, object]:
    """Build a request body honouring the minimal schema (idempotency key only)."""

    return {"idempotency_key": idempotency_key}


class TestAdmissionDecisionContract:
    """Response shape and decision-matrix coverage for the gated endpoint."""

    @pytest.mark.parametrize(
        ("status_value", "reason"),
        [
            (AdmissionStatus.ADMITTED, "all admission checks passed"),
            (
                AdmissionStatus.CORROBORATED,
                "external observation corroborated; internal check pending",
            ),
            (AdmissionStatus.REJECTED, "identity, freshness, or unit check failed"),
            (AdmissionStatus.CONFLICT, "conflicting verification facts"),
        ],
    )
    def test_admitted_response_serializes_each_decision(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
        status_value: AdmissionStatus,
        reason: str,
    ) -> None:
        observation = _observation(status=status_value, reason=reason)
        admission_service.decide.return_value = AdmissionCommandResult(observation, False)

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation.observation_id),
            json=_body(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "observation_id": str(observation.observation_id),
            "admission_status": status_value.value,
            "reason": reason,
            "idempotent": False,
        }

    def test_idempotent_response_path_returns_true_and_delegates_only_idempotency_key(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
    ) -> None:
        observation = _observation(
            status=AdmissionStatus.ADMITTED,
            reason="all admission checks passed",
        )
        admission_service.decide.return_value = AdmissionCommandResult(observation, True)

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation.observation_id),
            json=_body(idempotency_key="repeat-key"),
            headers={"Idempotency-Key": "repeat-key"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["idempotent"] is True
        assert body["observation_id"] == str(observation.observation_id)
        assert body["admission_status"] == AdmissionStatus.ADMITTED.value
        # Delegation contract: the service receives ONLY the path UUID
        # and the idempotency key. No AdmissionVerification is ever
        # constructed from the HTTP request body.
        admission_service.decide.assert_called_once_with(
            observation.observation_id,
            idempotency_key="repeat-key",
        )

    def test_lookup_error_maps_to_404(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
    ) -> None:
        observation_id = uuid4()
        admission_service.decide.side_effect = LookupError("ExternalObservation not found")

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation_id),
            json=_body(),
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "ExternalObservation not found"}

    def test_value_error_maps_to_409(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
    ) -> None:
        observation_id = uuid4()
        admission_service.decide.side_effect = ValueError(
            "observation admission has already been decided",
        )

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation_id),
            json=_body(),
        )

        assert response.status_code == 409
        assert response.json() == {
            "detail": "observation admission has already been decided",
        }

    def test_idempotency_header_mismatch_short_circuits_before_service_call(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
    ) -> None:
        observation_id = uuid4()

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation_id),
            headers={"Idempotency-Key": "header-key"},
            json=_body(idempotency_key="body-key"),
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Idempotency-Key mismatch"}
        admission_service.decide.assert_not_called()

    def test_legacy_verification_booleans_in_request_body_are_silently_ignored(
        self,
        client: TestClient,
        admission_service: MagicMock,
        enabled_settings: None,
    ) -> None:
        """Removed fields cannot drive the decision.

        The HTTP schema drops ``identity_ok`` / ``freshness_ok`` /
        ``unit_ok`` / ``internal_cross_check_ok`` / ``conflict_detected``
        from the public surface; if a legacy caller still sends them,
        FastAPI/Pydantic ignore the extras and the service receives
        only the path UUID and the idempotency key.
        """

        observation = _observation(
            status=AdmissionStatus.REJECTED,
            reason="identity, freshness, or unit check failed",
        )
        admission_service.decide.return_value = AdmissionCommandResult(observation, False)
        legacy_body: dict[str, object] = {
            "idempotency_key": "admission-legacy",
            "identity_ok": False,
            "freshness_ok": False,
            "unit_ok": False,
            "internal_cross_check_ok": False,
            "conflict_detected": True,
            "rules_version": "client-supplied/0.0",
            "decided_by": "rogue-caller",
            "reason": "client-tried-to-set",
        }

        response = client.post(
            ADMISSION_PATH_TEMPLATE.format(observation_id=observation.observation_id),
            json=legacy_body,
        )

        assert response.status_code == 200
        admission_service.decide.assert_called_once_with(
            observation.observation_id,
            idempotency_key="admission-legacy",
        )


class TestAdmissionDecisionOpenAPI:
    """The OpenAPI surface keeps the endpoint POST-only with the contract schemas."""

    def test_admission_path_declares_only_post(self) -> None:
        path = app.openapi()["paths"][ADMISSION_PATH_TEMPLATE]

        assert set(path) == {"post"}

    def test_admission_post_references_request_and_response_schemas(self) -> None:
        operation = app.openapi()["paths"][ADMISSION_PATH_TEMPLATE]["post"]

        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert request_schema["$ref"].endswith("AdmissionDecisionRequest")

        responses = operation["responses"]
        assert "200" in responses
        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "AdmissionDecisionResponse"
        )
        # FastAPI surfaces 422 validation errors via HTTPValidationError.
        assert "422" in responses
        assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "HTTPValidationError"
        )

    def test_admission_schemas_are_registered_under_components(self) -> None:
        schemas = app.openapi()["components"]["schemas"]

        assert "AdmissionDecisionRequest" in schemas
        assert "AdmissionDecisionResponse" in schemas

    def test_admission_request_schema_only_exposes_idempotency_key(self) -> None:
        """Public OpenAPI surface must not leak server-side verification booleans."""

        schema = app.openapi()["components"]["schemas"]["AdmissionDecisionRequest"]
        properties = set(schema["properties"])

        assert properties == {"idempotency_key"}
        for forbidden in (
            "identity_ok",
            "freshness_ok",
            "unit_ok",
            "internal_cross_check_ok",
            "conflict_detected",
            "rules_version",
            "decided_by",
            "reason",
        ):
            assert forbidden not in properties


# ---------------------------------------------------------------------------
# Service-level tests — prove the application service computes verification
# facts on the server from the loaded observation + recent observations.
# ---------------------------------------------------------------------------


_AUTO_INSTRUMENT: object = object()


class _InMemoryObservationRepository:
    """In-memory adapter satisfying ``ObservationRepository`` for service tests."""

    def __init__(self, observations: Iterable[ExternalObservation]) -> None:
        self._observations: list[ExternalObservation] = list(observations)

    def get_by_id(self, observation_id: UUID) -> ExternalObservation | None:
        for observation in self._observations:
            if observation.observation_id == observation_id:
                return observation
        return None

    def list_recent(
        self,
        *,
        status: AdmissionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExternalObservation]:
        items = [
            observation
            for observation in self._observations
            if status is None or observation.admission_status == status
        ]
        return items[offset : offset + limit]

    def save_admission(self, observation: ExternalObservation) -> ExternalObservation:
        for index, existing in enumerate(self._observations):
            if existing.observation_id == observation.observation_id:
                self._observations[index] = observation
                return observation
        self._observations.append(observation)
        return observation


def _pending_observation(
    *,
    observation_id: UUID | None = None,
    as_of: date = AS_OF,
    instrument_id: UUID | None | object = _AUTO_INSTRUMENT,
    symbol: str | None = "510050",
    payload: dict[str, Any] | None = None,
    run_id: UUID | None = None,
) -> ExternalObservation:
    """Build a pending observation that, by default, passes every server check.

    Tests override individual fields to model missing identity, missing
    unit / definition, future or stale ``as_of`` etc. By default a fresh
    ``instrument_id`` is generated; pass ``instrument_id=None`` explicitly
    to model an observation with no instrument binding.
    """

    resolved_instrument: UUID | None = (
        uuid4() if instrument_id is _AUTO_INSTRUMENT else instrument_id
    )
    resolved_payload = (
        dict(payload) if payload is not None else {"unit": "1.0", "definition": "value"}
    )
    return ExternalObservation(
        observation_id=observation_id or uuid4(),
        run_id=run_id or uuid4(),
        observed_at=OBSERVED_AT,
        as_of=as_of,
        source_uri="https://example.test/run-1/observation.json",
        producer="workbuddy",
        payload=resolved_payload,
        symbol=symbol,
        instrument_id=resolved_instrument,
    )


def _peer(
    *,
    observation_id: UUID,
    instrument_id: UUID,
    as_of: date,
    payload: dict[str, Any],
    symbol: str = "510050",
) -> ExternalObservation:
    return ExternalObservation(
        observation_id=observation_id,
        run_id=uuid4(),
        observed_at=OBSERVED_AT,
        as_of=as_of,
        source_uri=f"https://example.test/run-1/peer-{observation_id}.json",
        producer="workbuddy",
        payload=payload,
        symbol=symbol,
        instrument_id=instrument_id,
    )


def _service(
    observations: Iterable[ExternalObservation],
    *,
    clock: Callable[[], date] = lambda: BUSINESS_TODAY,
) -> ObservationAdmissionCommandService:
    return ObservationAdmissionCommandService(
        _InMemoryObservationRepository(observations),
        clock=clock,
    )


class TestObservationAdmissionCommandServiceServerSideVerification:
    """The service computes verification facts on the server."""

    def test_admit_when_all_checks_pass_and_peer_corroborates(self) -> None:
        instrument_id = uuid4()
        payload = {"unit": "1.0", "definition": "value"}
        pending = _pending_observation(
            instrument_id=instrument_id,
            payload=payload,
        )
        peer = _peer(
            observation_id=uuid4(),
            instrument_id=instrument_id,
            as_of=pending.as_of,
            payload=payload,
        )

        result = _service([pending, peer]).decide(
            pending.observation_id,
            idempotency_key="idem-key-1",
        )

        assert result.idempotent is False
        assert result.observation.admission_status == AdmissionStatus.ADMITTED
        admission = result.observation.metadata["admission"]
        assert admission["status"] == "admitted"
        assert admission["rules_version"] == "observation-admission/1.0"
        assert admission["decided_by"] == "system"
        assert admission["idempotency_key"] == "idem-key-1"
        assert admission["checks"] == {
            "identity_ok": True,
            "freshness_ok": True,
            "unit_ok": True,
            "internal_cross_check_ok": True,
            "conflict_detected": False,
        }

    def test_corroborate_when_no_peer_matches(self) -> None:
        pending = _pending_observation()

        result = _service([pending]).decide(
            pending.observation_id,
            idempotency_key="idem-key-2",
        )

        assert result.observation.admission_status == AdmissionStatus.CORROBORATED
        admission = result.observation.metadata["admission"]
        assert admission["checks"]["internal_cross_check_ok"] is None
        assert admission["checks"]["conflict_detected"] is False

    def test_conflict_when_peer_has_different_payload(self) -> None:
        instrument_id = uuid4()
        pending = _pending_observation(
            instrument_id=instrument_id,
            payload={"unit": "1.0", "definition": "value"},
        )
        peer = _peer(
            observation_id=uuid4(),
            instrument_id=instrument_id,
            as_of=pending.as_of,
            payload={"unit": "1.0", "definition": "different"},
        )

        result = _service([pending, peer]).decide(
            pending.observation_id,
            idempotency_key="idem-key-3",
        )

        assert result.observation.admission_status == AdmissionStatus.CONFLICT
        admission = result.observation.metadata["admission"]
        assert admission["checks"]["conflict_detected"] is True
        assert admission["checks"]["internal_cross_check_ok"] is False

    def test_conflict_takes_precedence_when_matching_peers_disagree(self) -> None:
        """A conflicting peer wins over an identical peer in the same scan.

        ``_resolve_internal_check`` must inspect every matching peer
        (same ``instrument_id`` + ``as_of``) before deciding, so a
        diverging payload surfaces as ``AdmissionStatus.CONFLICT`` even
        when an identical peer also exists in ``list_recent()``.
        """

        instrument_id = uuid4()
        payload = {"unit": "1.0", "definition": "value"}
        pending = _pending_observation(
            instrument_id=instrument_id,
            payload=payload,
        )
        identical_peer = _peer(
            observation_id=uuid4(),
            instrument_id=instrument_id,
            as_of=pending.as_of,
            payload=payload,
        )
        conflicting_peer = _peer(
            observation_id=uuid4(),
            instrument_id=instrument_id,
            as_of=pending.as_of,
            payload={"unit": "1.0", "definition": "diverging"},
        )

        result = _service(
            [pending, identical_peer, conflicting_peer],
        ).decide(
            pending.observation_id,
            idempotency_key="idem-key-conflict-precedence",
        )

        assert result.observation.admission_status == AdmissionStatus.CONFLICT
        admission = result.observation.metadata["admission"]
        assert admission["checks"]["conflict_detected"] is True
        assert admission["checks"]["internal_cross_check_ok"] is False

    def test_reject_when_instrument_id_missing(self) -> None:
        pending = _pending_observation(instrument_id=None)

        result = _service([pending]).decide(
            pending.observation_id,
            idempotency_key="idem-key-5",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        admission = result.observation.metadata["admission"]
        assert admission["checks"]["identity_ok"] is False
        assert admission["decided_by"] == "system"
        assert admission["rules_version"] == "observation-admission/1.0"

    def test_reject_when_symbol_is_missing(self) -> None:
        pending = _pending_observation(symbol=None)

        result = _service([pending]).decide(
            pending.observation_id,
            idempotency_key="idem-key-6",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        assert result.observation.metadata["admission"]["checks"]["identity_ok"] is False

    def test_reject_when_unit_missing(self) -> None:
        pending = _pending_observation(payload={"definition": "value"})

        result = _service([pending]).decide(
            pending.observation_id,
            idempotency_key="idem-key-7",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        assert result.observation.metadata["admission"]["checks"]["unit_ok"] is False

    def test_reject_when_definition_missing(self) -> None:
        pending = _pending_observation(payload={"unit": "1.0"})

        result = _service([pending]).decide(
            pending.observation_id,
            idempotency_key="idem-key-8",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        assert result.observation.metadata["admission"]["checks"]["unit_ok"] is False

    def test_reject_when_as_of_is_in_future(self) -> None:
        pending = _pending_observation(as_of=date(2026, 8, 16))

        result = _service(
            [pending],
            clock=lambda: BUSINESS_TODAY,
        ).decide(
            pending.observation_id,
            idempotency_key="idem-key-9",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        assert result.observation.metadata["admission"]["checks"]["freshness_ok"] is False

    def test_reject_when_as_of_is_too_stale(self) -> None:
        # Business today is 2026-08-14; as_of is 13 days earlier → outside the window.
        pending = _pending_observation(as_of=date(2026, 8, 1))

        result = _service(
            [pending],
            clock=lambda: BUSINESS_TODAY,
        ).decide(
            pending.observation_id,
            idempotency_key="idem-key-10",
        )

        assert result.observation.admission_status == AdmissionStatus.REJECTED
        assert result.observation.metadata["admission"]["checks"]["freshness_ok"] is False

    def test_freshness_passes_at_window_boundary(self) -> None:
        # Exactly seven calendar days before today still passes the window.
        pending = _pending_observation(as_of=BUSINESS_TODAY)

        result = _service(
            [pending],
            clock=lambda: BUSINESS_TODAY,
        ).decide(
            pending.observation_id,
            idempotency_key="idem-key-11",
        )

        assert result.observation.metadata["admission"]["checks"]["freshness_ok"] is True

    def test_idempotent_returns_existing_observation_when_key_matches(self) -> None:
        instrument_id = uuid4()
        payload = {"unit": "1.0", "definition": "value"}
        pending = _pending_observation(
            instrument_id=instrument_id,
            payload=payload,
        )
        peer = _peer(
            observation_id=uuid4(),
            instrument_id=instrument_id,
            as_of=pending.as_of,
            payload=payload,
        )
        service = _service([pending, peer])

        first = service.decide(pending.observation_id, idempotency_key="repeat-key")
        assert first.idempotent is False
        assert first.observation.admission_status == AdmissionStatus.ADMITTED

        second = service.decide(pending.observation_id, idempotency_key="repeat-key")

        assert second.idempotent is True
        assert second.observation is first.observation

    def test_terminal_state_rejects_subsequent_attempts(self) -> None:
        already_admitted = _pending_observation()
        final = replace(already_admitted, admission_status=AdmissionStatus.ADMITTED)
        service = _service([final])

        with pytest.raises(ValueError, match="already been decided"):
            service.decide(
                already_admitted.observation_id,
                idempotency_key="idem-key-12",
            )

    def test_raises_lookup_when_observation_missing(self) -> None:
        service = _service([])

        with pytest.raises(LookupError, match="not found"):
            service.decide(uuid4(), idempotency_key="idem-key-13")


__all__ = [
    "ADMISSION_PATH_TEMPLATE",
    "TestAdmissionDecisionContract",
    "TestAdmissionDecisionOpenAPI",
    "TestObservationAdmissionCommandServiceServerSideVerification",
    "admission_service",
    "enabled_settings",
]
