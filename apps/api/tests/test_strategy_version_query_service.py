"""Tests for :class:`StrategyVersionQueryService` and its Pydantic schema (Slice 1A)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_api.application.strategy_drafts import StrategyArtifactReader
from invest_api.application.strategy_versions import (
    StrategyVersionArtifactDecodeError,
    StrategyVersionArtifactHashMismatchError,
    StrategyVersionArtifactReadError,
    StrategyVersionNotFoundError,
    StrategyVersionQueryService,
    StrategyVersionRepository,
    StrategyVersionView,
)
from invest_api.schemas.strategy_versions import StrategyVersionResponse
from invest_domain.strategy import StrategyVersion

STRATEGY_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
AUDIT_ID = UUID("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff")
HASH = "a" * 64
OTHER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
APPROVED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
ACTIVATED = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)
STRATEGY: dict[str, Any] = {
    "schema_version": "strategy-proposal/1.0",
    "strategy_key": "sector-strength-ranking",
    "name": "Sector strength ranking",
    "rules": ["rank-by-breadth"],
}

GOVERNANCE_FIELDS: tuple[str, ...] = (
    "artifact_ref",
    "decision_ref",
    "decision_hash",
    "decided_by_agent_id",
    "source_hashes",
    "audit_id",
    "strategy_id",
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def bytes_for(obj: dict[str, Any] = STRATEGY) -> bytes:
    return json.dumps(obj).encode("utf-8")


def make_version(
    *,
    strategy_key: str = "sector-strength-ranking",
    version: str = "2.0.0",
    artifact_ref: str = "sector-strength-ranking/2.0.0/strategy.json",
    artifact_hash: str | None = None,
    approved_at: datetime = APPROVED,
    activated_at: datetime | None = ACTIVATED,
    strategy_id: UUID = STRATEGY_ID,
) -> StrategyVersion:
    return StrategyVersion.create(
        strategy_key=strategy_key,
        version=version,
        artifact_ref=artifact_ref,
        artifact_hash=artifact_hash if artifact_hash is not None else sha(bytes_for()),
        source_hashes=(HASH,),
        decision_ref="agentoa/decisions/sector-strength-v2.json",
        decision_hash=OTHER,
        decided_by_agent_id="cia-final",
        audit_id=AUDIT_ID,
        approved_at=approved_at,
        activated_at=activated_at,
        strategy_id=strategy_id,
        created_at=approved_at,
    )


def build_service(
    *,
    active: StrategyVersion | None = None,
    artifact_bytes: bytes | None = None,
    reader_raises: BaseException | None = None,
) -> tuple[StrategyVersionQueryService, MagicMock, MagicMock]:
    repo = MagicMock(spec=StrategyVersionRepository)
    reader = MagicMock(spec=StrategyArtifactReader)
    repo.get_active.return_value = active
    if reader_raises is not None:
        reader.read_bytes.side_effect = reader_raises
    else:
        reader.read_bytes.return_value = (
            artifact_bytes if artifact_bytes is not None else bytes_for()
        )
    return (
        StrategyVersionQueryService(
            repository=repo,
            artifact_reader=reader,
        ),
        repo,
        reader,
    )


def test_happy_path_returns_active_view_with_verified_payload():
    version = make_version()
    service, repo, reader = build_service(active=version)

    view = service.get_active("sector-strength-ranking")

    assert isinstance(view, StrategyVersionView)
    assert view.strategy_key == "sector-strength-ranking"
    assert view.version == "2.0.0"
    assert view.active is True
    assert view.artifact_hash == version.artifact_hash
    assert dict(view.strategy) == STRATEGY
    assert view.approved_at == APPROVED
    assert view.activated_at == ACTIVATED
    repo.get_active.assert_called_once_with("sector-strength-ranking")
    reader.read_bytes.assert_called_once_with(version.artifact_ref)


def test_view_envelope_excludes_governance_metadata():
    version = make_version()
    service, _, _ = build_service(active=version)

    view = service.get_active("sector-strength-ranking")

    assert set(StrategyVersionView.__dataclass_fields__) == {
        "strategy_key",
        "version",
        "active",
        "artifact_hash",
        "strategy",
        "approved_at",
        "activated_at",
    }
    envelope = {
        field.name: getattr(view, field.name) for field in dataclasses.fields(view)
    }
    envelope_json = json.dumps(envelope, default=str)
    for forbidden in GOVERNANCE_FIELDS:
        assert forbidden not in envelope_json


def test_view_preserves_complete_strategy_json_with_authored_path_like_content():
    strategy = {
        "schema_version": "strategy-proposal/1.0",
        "rules": [
            {
                "id": "R-A1",
                "reference_marker": r"Z:\workbuddy\strategy\inbox\fixture.json",
                "absolute_url": "https://example.test/source",
                "windows_path": r"C:\workbuddy\fixture.json",
                "narrative": "treat /srv/private/source.json as untrusted",
            },
        ],
        "nested": {
            "artifact_ref": "sector-strength-ranking/2.0.0/strategy.json",
            "host_path": "/srv/private/input.json",
            "values": [
                {"label": "internal", "host_path": "/srv/private/x.json"},
                "relative/business-label",
            ],
        },
    }
    raw = bytes_for(strategy)
    version = make_version(artifact_hash=sha(raw))
    service, _, _ = build_service(active=version, artifact_bytes=raw)

    view = service.get_active("sector-strength-ranking")

    assert view.artifact_hash == sha(raw)
    assert dict(view.strategy) == strategy
    assert (
        view.strategy["rules"][0]["reference_marker"]
        == r"Z:\workbuddy\strategy\inbox\fixture.json"
    )
    assert view.strategy["nested"]["artifact_ref"] == "sector-strength-ranking/2.0.0/strategy.json"
    assert view.strategy["nested"]["host_path"] == "/srv/private/input.json"
    assert view.strategy["nested"]["values"][0]["host_path"] == "/srv/private/x.json"
    assert view.strategy["nested"]["values"][1] == "relative/business-label"
    view_dict = dict(view.strategy)
    assert view_dict.pop("nested")["host_path"] == "/srv/private/input.json"


def test_missing_active_raises_not_found_without_calling_reader():
    service, _, reader = build_service(active=None)

    with pytest.raises(StrategyVersionNotFoundError) as exc_info:
        service.get_active("missing-key")

    assert exc_info.value.strategy_key == "missing-key"
    reader.read_bytes.assert_not_called()


def test_activated_at_none_raises_not_found():
    service, _, reader = build_service(
        active=make_version(activated_at=None),
    )

    with pytest.raises(StrategyVersionNotFoundError):
        service.get_active("sector-strength-ranking")

    reader.read_bytes.assert_not_called()


def test_hash_mismatch_raises_dedicated_error_when_bytes_tampered():
    version = make_version(artifact_hash=HASH)
    service, _, _ = build_service(active=version, artifact_bytes=b'{"different": "payload"}')

    with pytest.raises(StrategyVersionArtifactHashMismatchError):
        service.get_active("sector-strength-ranking")


@pytest.mark.parametrize(
    "bad_bytes",
    [
        pytest.param(b"\xff\xfe not utf-8", id="invalid-utf8"),
        pytest.param(b"{not-json", id="malformed-json"),
        pytest.param(b"[1, 2, 3]", id="json-array"),
        pytest.param(b'"just a string"', id="json-string"),
        pytest.param(b"42", id="json-number"),
        pytest.param(b"null", id="json-null"),
    ],
)
def test_decode_failures_raise_decode_error(bad_bytes: bytes):
    version = make_version(artifact_hash=sha(bad_bytes))
    service, _, _ = build_service(active=version, artifact_bytes=bad_bytes)

    with pytest.raises(StrategyVersionArtifactDecodeError):
        service.get_active("sector-strength-ranking")


@pytest.mark.parametrize(
    "leak,forbidden",
    [
        pytest.param(
            OSError("missing sector-strength-ranking/2.0.0/strategy.json"),
            "sector-strength-ranking/2.0.0",
            id="artifact-ref",
        ),
        pytest.param(
            OSError("cannot read /srv/secrets/strategy.json: permission denied"),
            "/srv/secrets/strategy.json",
            id="host-path",
        ),
        pytest.param(
            OSError("connection failed: postgres://user:hunter2@host/db"),
            "hunter2",
            id="credential",
        ),
        pytest.param(
            OSError("ENOSYS: native strategy loader unavailable"),
            "native strategy loader",
            id="raw-os-error",
        ),
        pytest.param(
            RuntimeError("storage backend offline"),
            "storage backend offline",
            id="runtime-error",
        ),
    ],
)
def test_reader_failure_translates_to_sanitized_error(
    leak: BaseException, forbidden: str
):
    version = make_version()
    service, _, _ = build_service(active=version, reader_raises=leak)

    with pytest.raises(StrategyVersionArtifactReadError) as exc_info:
        service.get_active("sector-strength-ranking")

    assert exc_info.value.__cause__ is leak
    assert forbidden not in str(exc_info.value)


def test_view_is_frozen_and_cannot_be_tampered():
    version = make_version()
    service, _, _ = build_service(active=version)

    view = service.get_active("sector-strength-ranking")

    with pytest.raises(FrozenInstanceError):
        view.strategy_key = "tampered"  # type: ignore[misc]


def test_top_level_strategy_mapping_is_immutable_but_nested_content_is_preserved():
    version = make_version()
    service, _, _ = build_service(active=version)

    view = service.get_active("sector-strength-ranking")

    with pytest.raises(TypeError):
        view.strategy["added"] = "x"  # type: ignore[index]
    assert dict(view.strategy) == STRATEGY


def test_response_schema_carries_verified_payload_and_hides_envelope_metadata():
    version = make_version()
    service, _, _ = build_service(active=version)

    response = StrategyVersionResponse.from_view(service.get_active("sector-strength-ranking"))

    declared = set(StrategyVersionResponse.model_fields)
    for forbidden in GOVERNANCE_FIELDS:
        assert forbidden not in declared
    payload = json.loads(response.model_dump_json())
    for forbidden in GOVERNANCE_FIELDS:
        assert forbidden not in payload
    assert response.strategy_key == "sector-strength-ranking"
    assert response.version == "2.0.0"
    assert response.active is True
    assert response.schema_version == "strategy-proposal/1.0"
    assert response.artifact_hash == version.artifact_hash
    assert response.strategy == STRATEGY
    assert response.approved_at == APPROVED
    assert response.activated_at == ACTIVATED


def test_response_schema_preserves_authored_strategy_payload_unchanged():
    strategy = {
        "schema_version": "strategy-proposal/1.0",
        "rules": [{"id": "R-A1", "source_marker": r"C:\workbuddy\fixture.json"}],
        "nested": {"artifact_ref": "x/y.json", "host_path": "/srv/p.json"},
    }
    raw = bytes_for(strategy)
    version = make_version(artifact_hash=sha(raw))
    service, _, _ = build_service(active=version, artifact_bytes=raw)

    response = StrategyVersionResponse.from_view(service.get_active("sector-strength-ranking"))

    assert response.schema_version == "strategy-proposal/1.0"
    assert response.strategy == strategy
    assert response.strategy["rules"][0]["source_marker"] == r"C:\workbuddy\fixture.json"
    assert response.strategy["nested"]["artifact_ref"] == "x/y.json"
    assert response.strategy["nested"]["host_path"] == "/srv/p.json"


def test_response_schema_omits_schema_version_when_json_root_omits_it():
    strategy = {"name": "no schema version key here"}
    raw = bytes_for(strategy)
    version = make_version(artifact_hash=sha(raw))
    service, _, _ = build_service(active=version, artifact_bytes=raw)

    response = StrategyVersionResponse.from_view(service.get_active("sector-strength-ranking"))

    assert response.schema_version is None
    assert response.strategy == strategy


__all__ = [
    "test_activated_at_none_raises_not_found",
    "test_decode_failures_raise_decode_error",
    "test_hash_mismatch_raises_dedicated_error_when_bytes_tampered",
    "test_missing_active_raises_not_found_without_calling_reader",
    "test_response_schema_carries_verified_payload_and_hides_envelope_metadata",
    "test_response_schema_omits_schema_version_when_json_root_omits_it",
    "test_response_schema_preserves_authored_strategy_payload_unchanged",
    "test_top_level_strategy_mapping_is_immutable_but_nested_content_is_preserved",
    "test_view_envelope_excludes_governance_metadata",
    "test_view_is_frozen_and_cannot_be_tampered",
    "test_view_preserves_complete_strategy_json_with_authored_path_like_content",
    "test_reader_failure_translates_to_sanitized_error",
]
