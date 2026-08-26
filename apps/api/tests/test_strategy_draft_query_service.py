"""Tests for :class:`StrategyDraftQueryService` and its Pydantic schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_api.application.strategy_drafts import (
    StrategyArtifactReader,
    StrategyAuditRepository,
    StrategyDraftArtifactDecodeError,
    StrategyDraftArtifactHashMismatchError,
    StrategyDraftArtifactReadError,
    StrategyDraftNotFoundError,
    StrategyDraftQueryService,
    StrategyDraftRepository,
    StrategyDraftView,
)
from invest_api.schemas.strategy_drafts import (
    SourceRefResponse,
    StrategyDraftAuditSummaryResponse,
    StrategyDraftResponse,
)
from invest_domain.strategy import (
    SourceRef,
    StrategyAudit,
    StrategyAuditVerdict,
    StrategyDraft,
)

DRAFT_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
HASH = "a" * 64
OTHER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
CREATED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
AUDITED = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)
STRATEGY: dict[str, Any] = {
    "schema_version": "1.0.0",
    "strategy_key": "sector-strength",
    "version": "1.0.0",
    "name": "Sector strength",
    "rules": ["rank-by-breadth"],
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def bytes_for(obj: dict[str, Any] = STRATEGY) -> bytes:
    return json.dumps(obj).encode("utf-8")


def make_draft(
    *,
    artifact_hash: str | None = None,
    artifact_ref: str = "sector-strength/strategy.json",
    source_refs: tuple[SourceRef, ...] = (
        SourceRef(ref="https://m.toutiao.com/is/fslPVWFTKSY/", content_hash=HASH),
    ),
) -> StrategyDraft:
    return StrategyDraft.create(
        strategy_key="sector-strength",
        proposed_version="1.0.0",
        artifact_ref=artifact_ref,
        artifact_hash=artifact_hash if artifact_hash is not None else sha(bytes_for()),
        source_refs=source_refs,
        validation_result={"status": "ok"},
        draft_id=DRAFT_ID,
        created_at=CREATED,
    )


def build_service(
    *,
    draft: StrategyDraft | None = None,
    artifact_bytes: bytes | None = None,
    reader_raises: BaseException | None = None,
) -> tuple[StrategyDraftQueryService, MagicMock, MagicMock, MagicMock]:
    repo = MagicMock(spec=StrategyDraftRepository)
    audit_repo = MagicMock(spec=StrategyAuditRepository)
    reader = MagicMock(spec=StrategyArtifactReader)
    repo.get_by_id.return_value = draft
    audit_repo.list_by_draft.return_value = []
    if reader_raises is not None:
        reader.read_bytes.side_effect = reader_raises
    else:
        reader.read_bytes.return_value = (
            artifact_bytes if artifact_bytes is not None else bytes_for()
        )
    return (
        StrategyDraftQueryService(
            repository=repo,
            audit_repository=audit_repo,
            artifact_reader=reader,
        ),
        repo,
        audit_repo,
        reader,
    )


def test_happy_path_returns_view_with_verified_payload():
    draft = make_draft(source_refs=(
        SourceRef(ref="a", content_hash=HASH),
        SourceRef(ref="b", content_hash=OTHER),
    ))
    service, repo, audit_repo, reader = build_service(draft=draft)

    view = service.get_draft(DRAFT_ID)

    assert isinstance(view, StrategyDraftView)
    assert view.draft_id == DRAFT_ID
    assert view.strategy_key == "sector-strength"
    assert view.proposed_version == "1.0.0"
    assert view.artifact_hash == draft.artifact_hash
    assert view.strategy == STRATEGY
    assert len(view.source_refs) == 2
    assert view.source_refs[1].content_hash == OTHER
    assert dict(view.validation_result) == {"status": "ok"}
    assert view.created_at == CREATED
    repo.get_by_id.assert_called_once_with(DRAFT_ID)
    audit_repo.list_by_draft.assert_called_once_with(DRAFT_ID)
    reader.read_bytes.assert_called_once_with(draft.artifact_ref)


def test_happy_path_maps_audits_in_repository_order():
    service, _, audit_repo, _ = build_service(draft=make_draft())
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    second_id = UUID("22222222-2222-4222-8222-222222222222")
    audit_repo.list_by_draft.return_value = [
        StrategyAudit.create(
            draft_id=DRAFT_ID,
            artifact_hash=HASH,
            agentoa_task_id="task-first",
            auditor_agent_id="raa",
            verdict=StrategyAuditVerdict.CHANGES_REQUIRED,
            findings=[],
            limitations=[],
            report_ref="audit/first.json",
            report_hash=OTHER,
            audited_at=AUDITED,
            audit_id_factory=lambda: first_id,
            clock=lambda: AUDITED,
        ),
        StrategyAudit.create(
            draft_id=DRAFT_ID,
            artifact_hash=OTHER,
            agentoa_task_id="task-second",
            auditor_agent_id="raa",
            verdict=StrategyAuditVerdict.PASS,
            findings=[],
            limitations=[],
            report_ref="audit/second.json",
            report_hash=HASH,
            audited_at=CREATED,
            audit_id_factory=lambda: second_id,
            clock=lambda: CREATED,
        ),
    ]

    view = service.get_draft(DRAFT_ID)

    assert [summary.audit_id for summary in view.audit_summaries] == [first_id, second_id]
    assert view.audit_summaries[0].artifact_hash == HASH
    assert view.audit_summaries[0].verdict == "changes_required"
    assert view.audit_summaries[0].audited_at == AUDITED


def test_public_view_recursively_redacts_internal_paths_without_changing_hash():
    strategy = {
        "task_source": r"Z:\workbuddy\strategy\inbox\task.ready",
        "nested": {
            "host_path": "/srv/private/input.json",
            "source_url": "https://example.test/a/b",
            "description": "Use the latest available business data",
            "values": [r"C:\private\file.json", "relative/business-label"],
        },
    }
    raw = bytes_for(strategy)
    draft = make_draft(artifact_hash=sha(raw))
    service, _, _, _ = build_service(draft=draft, artifact_bytes=raw)

    view = service.get_draft(DRAFT_ID)

    assert view.artifact_hash == sha(raw)
    assert "task_source" not in view.strategy
    assert "host_path" not in view.strategy["nested"]
    assert view.strategy["nested"]["source_url"] == "https://example.test/a/b"
    assert view.strategy["nested"]["description"] == "Use the latest available business data"
    assert view.strategy["nested"]["values"] == [
        "[internal path redacted]",
        "relative/business-label",
    ]


def test_missing_draft_raises_not_found_without_calling_reader():
    service, _, audit_repo, reader = build_service(draft=None)

    with pytest.raises(StrategyDraftNotFoundError) as exc_info:
        service.get_draft(DRAFT_ID)

    assert exc_info.value.draft_id == DRAFT_ID
    assert "strategy-engineering" not in str(exc_info.value)
    reader.read_bytes.assert_not_called()
    audit_repo.list_by_draft.assert_not_called()


def test_hash_mismatch_raises_dedicated_error_when_bytes_tampered():
    draft = make_draft(artifact_hash=HASH)
    service, _, _, _ = build_service(draft=draft, artifact_bytes=b'{"different": "payload"}')

    with pytest.raises(StrategyDraftArtifactHashMismatchError):
        service.get_draft(DRAFT_ID)


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
    draft = make_draft(artifact_hash=sha(bad_bytes))
    service, _, _, _ = build_service(draft=draft, artifact_bytes=bad_bytes)

    with pytest.raises(StrategyDraftArtifactDecodeError):
        service.get_draft(DRAFT_ID)


@pytest.mark.parametrize(
    "leak,forbidden",
    [
        pytest.param(
            OSError("missing strategy-engineering-sector-strength-20260815-0001/strategy.json"),
            "strategy-engineering-sector-strength",
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
    draft = make_draft()
    service, _, _, _ = build_service(draft=draft, reader_raises=leak)

    with pytest.raises(StrategyDraftArtifactReadError) as exc_info:
        service.get_draft(DRAFT_ID)

    assert exc_info.value.__cause__ is leak
    assert forbidden not in str(exc_info.value)


def test_view_is_frozen_and_excludes_artifact_ref():
    service, _, _, _ = build_service(draft=make_draft())
    view = service.get_draft(DRAFT_ID)

    assert set(StrategyDraftView.__dataclass_fields__) == {
        "draft_id", "strategy_key", "proposed_version", "artifact_hash",
        "strategy", "source_refs", "validation_result", "created_at",
        "audit_summaries",
    }
    assert view.audit_summaries == ()
    with pytest.raises(FrozenInstanceError):
        view.strategy_key = "tampered"  # type: ignore[misc]


def test_response_schema_carries_verified_payload_and_hides_artifact_ref():
    service, _, _, _ = build_service(draft=make_draft())
    response = StrategyDraftResponse.from_view(service.get_draft(DRAFT_ID))

    declared = set(StrategyDraftResponse.model_fields)
    assert "artifact_ref" not in declared
    assert "host_path" not in declared
    assert "raw_artifact_bytes" not in declared

    payload = json.loads(response.model_dump_json())
    assert "artifact_ref" not in payload
    assert "host_path" not in payload

    assert response.draft_id == DRAFT_ID
    assert response.strategy == STRATEGY
    assert isinstance(response.source_refs[0], SourceRefResponse)
    assert response.audit_summaries == []
    assert all(
        isinstance(s, StrategyDraftAuditSummaryResponse)
        for s in response.audit_summaries
    )


__all__ = [
    "test_decode_failures_raise_decode_error",
    "test_hash_mismatch_raises_dedicated_error_when_bytes_tampered",
    "test_happy_path_returns_view_with_verified_payload",
    "test_missing_draft_raises_not_found_without_calling_reader",
    "test_reader_failure_translates_to_sanitized_error",
    "test_response_schema_carries_verified_payload_and_hides_artifact_ref",
    "test_view_is_frozen_and_excludes_artifact_ref",
]
