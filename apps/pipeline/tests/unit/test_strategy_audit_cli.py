from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from invest_pipeline.strategy_audit_cli import ingest_audit, run

DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
AUDIT_ID = UUID("22222222-2222-4222-8222-222222222222")
ARTIFACT_HASH = "a" * 64
TASK_ID = "tsk_75cab57292fb4e66"
AGENT_ID = "agt_da9c59be9add6176"


class Draft:
    draft_id = DRAFT_ID
    artifact_hash = ARTIFACT_HASH


class DraftRepo:
    def get_by_id(self, draft_id):
        return Draft() if draft_id == DRAFT_ID else None


class AuditRepo:
    def __init__(self) -> None:
        self.items = []

    def add(self, audit):
        for item in self.items:
            if (item.draft_id, item.artifact_hash, item.agentoa_task_id) == (
                audit.draft_id,
                audit.artifact_hash,
                audit.agentoa_task_id,
            ):
                return item
        self.items.append(audit)
        return audit


class Uow:
    def __init__(self, audits: AuditRepo | None = None) -> None:
        self.strategy_drafts = DraftRepo()
        self.strategy_audits = audits or AuditRepo()
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self):
        self.commits += 1


def _files(tmp_path: Path) -> tuple[Path, Path, str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    report = tmp_path / "audit.md"
    report_bytes = b"# Independent audit\n\nChanges required.\n"
    report.write_bytes(report_bytes)
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    payload = {
        "schema_version": 1,
        "draft_id": str(DRAFT_ID),
        "artifact_hash": ARTIFACT_HASH,
        "agentoa_task_id": TASK_ID,
        "auditor": "Research Audit Agent",
        "auditor_agent_id": AGENT_ID,
        "verdict": "changes_required",
        "findings": [{"code": "DATA-001", "message": "口径不可复现"}],
        "limitations": ["未执行回测"],
        "report_ref": "reports/audit.md",
        "report_hash": report_hash,
        "audited_at": "2026-08-26T15:20:00Z",
    }
    audit = tmp_path / "audit.json"
    audit_bytes = json.dumps(payload, ensure_ascii=False).encode()
    audit.write_bytes(audit_bytes)
    return audit, report, hashlib.sha256(audit_bytes).hexdigest(), report_hash


def _invoke(tmp_path: Path, *, audits: AuditRepo | None = None, audit_id: UUID = AUDIT_ID):
    audit, report, audit_hash, report_hash = _files(tmp_path)
    uow = Uow(audits)
    result = ingest_audit(
        audit_json_file=audit,
        report_file=report,
        expected_draft_id=str(DRAFT_ID),
        expected_artifact_hash=ARTIFACT_HASH,
        expected_agentoa_task_id=TASK_ID,
        expected_auditor_agent_id=AGENT_ID,
        expected_audit_json_sha256=audit_hash,
        expected_report_sha256=report_hash,
        uow_factory=lambda: uow,
        audit_id_factory=lambda: audit_id,
        clock=lambda: datetime(2026, 8, 26, 15, 30, tzinfo=UTC),
    )
    return result, uow, audit, report


def test_ingests_bound_audit_and_commits(tmp_path: Path) -> None:
    result, uow, _, _ = _invoke(tmp_path)
    stored = uow.strategy_audits.items[0]
    assert result == {
        "audit_id": str(AUDIT_ID),
        "draft_id": str(DRAFT_ID),
        "artifact_hash": ARTIFACT_HASH,
        "agentoa_task_id": TASK_ID,
        "verdict": "changes_required",
        "idempotent": False,
    }
    assert stored.audited_at == datetime(2026, 8, 26, 15, 20, tzinfo=UTC)
    assert stored.report_ref == "reports/audit.md"
    assert uow.commits == 1


def test_repeated_ingestion_is_idempotent(tmp_path: Path) -> None:
    repo = AuditRepo()
    first, _, _, _ = _invoke(tmp_path / "first", audits=repo)
    second, _, _, _ = _invoke(
        tmp_path / "second", audits=repo,
        audit_id=UUID("33333333-3333-4333-8333-333333333333"),
    )
    assert first["audit_id"] == second["audit_id"]
    assert second["idempotent"] is True
    assert len(repo.items) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1"),
        ("draft_id", "33333333-3333-4333-8333-333333333333"),
        ("artifact_hash", "b" * 64),
        ("agentoa_task_id", "tsk_wrong"),
        ("auditor_agent_id", "agt_wrong"),
        ("report_hash", "b" * 64),
        ("report_ref", "../audit.md"),
        ("audited_at", "2026-08-26T15:20:00"),
    ],
)
def test_rejects_contract_or_binding_mismatch(tmp_path: Path, field: str, value: object) -> None:
    audit, report, _, report_hash = _files(tmp_path)
    payload = json.loads(audit.read_bytes())
    payload[field] = value
    data = json.dumps(payload).encode()
    audit.write_bytes(data)
    with pytest.raises((TypeError, ValueError)):
        ingest_audit(
            audit, report, str(DRAFT_ID), ARTIFACT_HASH, TASK_ID, AGENT_ID,
            hashlib.sha256(data).hexdigest(), report_hash, lambda: Uow()
        )


@pytest.mark.parametrize("change", ["missing", "unknown"])
def test_rejects_non_exact_json_shape(tmp_path: Path, change: str) -> None:
    audit, report, _, report_hash = _files(tmp_path)
    payload = json.loads(audit.read_bytes())
    payload.pop("auditor") if change == "missing" else payload.update(extra="no")
    data = json.dumps(payload).encode()
    audit.write_bytes(data)
    with pytest.raises(ValueError):
        ingest_audit(
            audit, report, str(DRAFT_ID), ARTIFACT_HASH, TASK_ID, AGENT_ID,
            hashlib.sha256(data).hexdigest(), report_hash, lambda: Uow()
        )


def test_rejects_byte_hash_report_name_and_missing_draft(tmp_path: Path) -> None:
    audit, report, audit_hash, report_hash = _files(tmp_path)
    with pytest.raises(ValueError):
        ingest_audit(
            audit, report, str(DRAFT_ID), ARTIFACT_HASH, TASK_ID, AGENT_ID,
            "0" * 64, report_hash, lambda: Uow()
        )
    payload = json.loads(audit.read_bytes())
    payload["report_ref"] = "reports/other.md"
    data = json.dumps(payload).encode()
    audit.write_bytes(data)
    with pytest.raises(ValueError):
        ingest_audit(
            audit, report, str(DRAFT_ID), ARTIFACT_HASH, TASK_ID, AGENT_ID,
            hashlib.sha256(data).hexdigest(), report_hash, lambda: Uow()
        )
    uow = Uow()
    uow.strategy_drafts = DraftRepo()
    uow.strategy_drafts.get_by_id = lambda _draft_id: None
    fresh_audit, fresh_report, fresh_audit_hash, fresh_report_hash = _files(tmp_path / "fresh")
    with pytest.raises(ValueError):
        ingest_audit(
            fresh_audit, fresh_report, str(DRAFT_ID), ARTIFACT_HASH, TASK_ID, AGENT_ID,
            fresh_audit_hash, fresh_report_hash, lambda: uow
        )


def test_run_redacts_failures_and_emits_safe_json(tmp_path: Path) -> None:
    audit, report, audit_hash, report_hash = _files(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    kwargs = dict(
        audit_json_file=audit, report_file=report, expected_draft_id=str(DRAFT_ID),
        expected_artifact_hash=ARTIFACT_HASH, expected_agentoa_task_id=TASK_ID,
        expected_auditor_agent_id=AGENT_ID, expected_audit_json_sha256=audit_hash,
        expected_report_sha256=report_hash, uow_factory=lambda: Uow(),
        audit_id_factory=lambda: AUDIT_ID,
    )
    assert run(stdout=out, stderr=err, **kwargs) == 0
    assert set(json.loads(out.getvalue())) == {
        "audit_id", "draft_id", "artifact_hash", "agentoa_task_id", "verdict", "idempotent"
    }
    assert run(stdout=out, stderr=err, **(kwargs | {"audit_json_file": "/secret/audit"})) == 1
    assert err.getvalue() == "error: strategy audit ingestion failed\n"
    assert "/secret" not in err.getvalue()
