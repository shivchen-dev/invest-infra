from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, TextIO
from uuid import UUID

from invest_domain.strategy import StrategyAudit

_FIELDS = {
    "schema_version",
    "draft_id",
    "artifact_hash",
    "agentoa_task_id",
    "auditor",
    "auditor_agent_id",
    "verdict",
    "findings",
    "limitations",
    "report_ref",
    "report_hash",
    "audited_at",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path_value: str | Path) -> tuple[Path, bytes]:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("input file unavailable")
    return path, path.read_bytes()


def _json_object(data: bytes) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8", errors="strict"))
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("audit JSON contract mismatch")
    return value


def _aware_iso8601(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise TypeError("audited_at must be an ISO-8601 string")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("audited_at is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("audited_at must be timezone-aware")
    return result


def _safe_report_ref(value: Any, report_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("report_ref is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.name != report_name
    ):
        raise ValueError("report_ref is invalid")
    return value


def ingest_audit(
    audit_json_file: str | Path,
    report_file: str | Path,
    expected_draft_id: str,
    expected_artifact_hash: str,
    expected_agentoa_task_id: str,
    expected_auditor_agent_id: str,
    expected_audit_json_sha256: str,
    expected_report_sha256: str,
    uow_factory: Callable[[], Any],
    *,
    audit_id_factory: Callable[[], UUID] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    audit_path, audit_bytes = _read_regular(audit_json_file)
    report_path, report_bytes = _read_regular(report_file)
    del audit_path
    if _sha(audit_bytes) != expected_audit_json_sha256:
        raise ValueError("audit JSON integrity failure")
    if _sha(report_bytes) != expected_report_sha256:
        raise ValueError("audit report integrity failure")
    payload = _json_object(audit_bytes)
    if payload["schema_version"] != 1:
        raise ValueError("unsupported audit schema")
    try:
        draft_id = UUID(expected_draft_id)
        payload_draft_id = UUID(payload["draft_id"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("draft identity invalid") from exc
    bindings = (
        (payload_draft_id, draft_id),
        (payload["artifact_hash"], expected_artifact_hash),
        (payload["agentoa_task_id"], expected_agentoa_task_id),
        (payload["auditor_agent_id"], expected_auditor_agent_id),
        (payload["report_hash"], expected_report_sha256),
    )
    if any(actual != expected for actual, expected in bindings):
        raise ValueError("audit binding mismatch")
    if not isinstance(payload["auditor"], str) or not payload["auditor"].strip():
        raise ValueError("auditor is invalid")
    report_ref = _safe_report_ref(payload["report_ref"], report_path.name)
    audited_at = _aware_iso8601(payload["audited_at"])
    create_kwargs: dict[str, Any] = {}
    if audit_id_factory is not None:
        create_kwargs["audit_id_factory"] = audit_id_factory
    if clock is not None:
        create_kwargs["clock"] = clock
    with uow_factory() as uow:
        draft = uow.strategy_drafts.get_by_id(draft_id)
        if draft is None or draft.artifact_hash != expected_artifact_hash:
            raise ValueError("strategy draft binding mismatch")
        audit = StrategyAudit.create(
            draft_id=draft_id,
            artifact_hash=expected_artifact_hash,
            agentoa_task_id=expected_agentoa_task_id,
            auditor_agent_id=expected_auditor_agent_id,
            verdict=payload["verdict"],
            findings=payload["findings"],
            limitations=payload["limitations"],
            report_ref=report_ref,
            report_hash=expected_report_sha256,
            audited_at=audited_at,
            **create_kwargs,
        )
        saved = uow.strategy_audits.add(audit)
        uow.commit()
    return {
        "audit_id": str(saved.audit_id),
        "draft_id": str(saved.draft_id),
        "artifact_hash": saved.artifact_hash,
        "agentoa_task_id": saved.agentoa_task_id,
        "verdict": saved.verdict.value,
        "idempotent": saved.audit_id != audit.audit_id,
    }


def run(*, stdout: TextIO | None = None, stderr: TextIO | None = None, **kwargs: Any) -> int:
    try:
        result = ingest_audit(**kwargs)
        (stdout or sys.stdout).write(json.dumps(result, sort_keys=True) + "\n")
        return 0
    except Exception:  # noqa: BLE001
        (stderr or sys.stderr).write("error: strategy audit ingestion failed\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invest_pipeline.strategy_audit_cli")
    for name in ("audit-json-file", "report-file"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in (
        "expected-draft-id",
        "expected-artifact-hash",
        "expected-agentoa-task-id",
        "expected-auditor-agent-id",
        "expected-audit-json-sha256",
        "expected-report-sha256",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    from invest_storage.database import build_engine, session_factory
    from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

    from invest_pipeline.config import get_settings

    engine = build_engine(get_settings().database_url)
    try:
        factory = session_factory(engine)
        return run(**vars(args), uow_factory=lambda: SqlAlchemyUnitOfWork(factory))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
