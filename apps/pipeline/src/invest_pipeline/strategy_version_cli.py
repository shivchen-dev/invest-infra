"""Atomic StrategyVersion management CLI + read-only query.

The CLI is the manual interface for :class:`StrategyGovernanceService`
that the candidate-strategies MVP delegated cross-aggregate binding
to. It does not duplicate those rules — every binding check the
service owns is delegated to it — and it never touches a database
directly. ``main`` lazily constructs the engine, the Unit-of-Work
factory, and a service with the per-subcommand authorization
configuration, then dispatches to ``run``.

Subcommands
===========

``publish``
    Parse a strict CIA decision envelope, bind every expected CLI
    argument to either the parsed decision or the stored aggregate,
    and publish an immutable :class:`StrategyVersion` through the
    service.

``activate``
    Flip the activation flag for an existing :class:`StrategyVersion`
    through the service.

``get-active``
    Read-only passthrough returning the currently-active version for
    a strategy key, or ``null`` when none is active.

Output
======

Every successful path emits one bounded JSON line on stdout and a
single constant stderr line on any failure. The view excludes the
strategy body and the host absolute input path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

from invest_domain.strategy import StrategyDecision

from invest_pipeline.strategy_governance import StrategyGovernanceService


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path_value: Path) -> bytes:
    if path_value.is_symlink() or not path_value.is_file():
        raise ValueError("decision file unavailable")
    return path_value.read_bytes()


def _uuid(name: str, value: Any) -> UUID:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string UUID")
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{name} is not a UUID") from exc


def _view(version: Any) -> dict[str, object]:
    activated_at = version.activated_at.isoformat() if version.activated_at else None
    return {
        "strategy_id": str(version.strategy_id),
        "key": version.strategy_key,
        "version": version.version,
        "artifact_ref": version.artifact_ref,
        "artifact_hash": version.artifact_hash,
        "decision_ref": version.decision_ref,
        "decision_hash": version.decision_hash,
        "audit_id": str(version.audit_id),
        "approved_at": version.approved_at.isoformat(),
        "activated_at": activated_at,
        "created_at": version.created_at.isoformat(),
    }


def publish_version(
    *,
    service: StrategyGovernanceService,
    decision_json_file: Path,
    decision_ref: str,
    expected_decision_sha256: str,
    expected_draft_id: str,
    expected_audit_id: str,
    expected_strategy_key: str,
    expected_version: str,
    expected_artifact_hash: str,
    expected_approver_agent_id: str,
) -> dict[str, object]:
    """Publish a CIA-approved StrategyVersion through the service."""
    data = _read_regular(Path(decision_json_file))
    if _sha(data) != expected_decision_sha256:
        raise ValueError("decision JSON integrity failure")
    payload = json.loads(data.decode("utf-8", errors="strict"))
    decision = StrategyDecision.from_mapping(payload)
    expected_draft = UUID(expected_draft_id)
    expected_audit = UUID(expected_audit_id)
    if decision.draft_id != expected_draft:
        raise ValueError("decision draft_id binding mismatch")
    if decision.audit_id != expected_audit:
        raise ValueError("decision audit_id binding mismatch")
    if decision.artifact_hash != expected_artifact_hash:
        raise ValueError("decision artifact_hash binding mismatch")
    if decision.decided_by_agent_id != expected_approver_agent_id:
        raise ValueError("decision approver binding mismatch")
    stored = service.publish_approved_version(
        draft_id=decision.draft_id,
        audit_id=decision.audit_id,
        expected_strategy_key=expected_strategy_key,
        expected_version=expected_version,
        decision=decision,
        decision_ref=decision_ref,
        decision_hash=expected_decision_sha256,
    )
    return _view(stored)


def activate_version(
    *,
    service: StrategyGovernanceService,
    strategy_id: UUID | str,
    version: str,
) -> dict[str, object]:
    """Activate a stored StrategyVersion through the service.

    ``strategy_id`` accepts either a :class:`UUID` (direct handler
    callers, unit tests) or a raw string (the CLI parser never
    pre-converts it, so a malformed UUID raises inside this handler
    and ``run`` redacts it).
    """
    parsed_strategy_id = (
        strategy_id if isinstance(strategy_id, UUID) else _uuid("strategy_id", strategy_id)
    )
    stored = service.activate_version(strategy_id=parsed_strategy_id, version=version)
    return _view(stored)


def get_active_view(
    *,
    service: StrategyGovernanceService,
    strategy_key: str,
) -> dict[str, object] | None:
    """Return the bounded view of the active version, or ``None``."""
    stored = service.get_active_version(strategy_key)
    return _view(stored) if stored is not None else None


def run(
    command: str,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    service: StrategyGovernanceService,
    **kwargs: Any,
) -> int:
    """Dispatch one subcommand; emit one JSON line and return 0/1."""
    try:
        if command == "publish":
            result = publish_version(service=service, **kwargs)
            (stdout or sys.stdout).write(json.dumps(result, sort_keys=True) + "\n")
            return 0
        if command == "activate":
            result = activate_version(service=service, **kwargs)
            (stdout or sys.stdout).write(json.dumps(result, sort_keys=True) + "\n")
            return 0
        if command == "get-active":
            result = get_active_view(service=service, **kwargs)
            (stdout or sys.stdout).write(
                "null\n" if result is None else json.dumps(result, sort_keys=True) + "\n"
            )
            return 0
        raise ValueError(f"unknown command: {command}")
    except Exception:  # noqa: BLE001
        (stderr or sys.stderr).write("error: strategy version operation failed\n")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="invest_pipeline.strategy_version_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pub = subparsers.add_parser("publish")
    pub.add_argument("--decision-json-file", type=Path, required=True)
    pub.add_argument("--decision-ref", required=True)
    pub.add_argument("--expected-decision-sha256", required=True)
    pub.add_argument("--expected-draft-id", required=True)
    pub.add_argument("--expected-audit-id", required=True)
    pub.add_argument("--expected-strategy-key", required=True)
    pub.add_argument("--expected-version", required=True)
    pub.add_argument("--expected-artifact-hash", required=True)
    pub.add_argument("--expected-approver-agent-id", required=True)

    act = subparsers.add_parser("activate")
    act.add_argument("--strategy-id", required=True)
    act.add_argument("--version", required=True)

    ga = subparsers.add_parser("get-active")
    ga.add_argument("--strategy-key", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Construct the service and dispatch to ``run``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from invest_storage.database import build_engine, session_factory
    from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

    from invest_pipeline.config import get_settings

    engine = build_engine(get_settings().database_url)
    try:
        factory = session_factory(engine)

        def uow_factory() -> Any:
            return SqlAlchemyUnitOfWork(factory)

        if args.command == "publish":
            service = StrategyGovernanceService(
                uow_factory=uow_factory,
                authorized_approver_agent_ids=(args.expected_approver_agent_id,),
            )
            payload = {k: v for k, v in vars(args).items() if k != "command"}
            return run("publish", service=service, **payload)
        if args.command == "activate":
            service = StrategyGovernanceService(
                uow_factory=uow_factory,
                authorized_approver_agent_ids=(),
            )
            return run(
                "activate",
                service=service,
                strategy_id=args.strategy_id,
                version=args.version,
            )
        if args.command == "get-active":
            service = StrategyGovernanceService(
                uow_factory=uow_factory,
                authorized_approver_agent_ids=(),
            )
            return run(
                "get-active",
                service=service,
                strategy_key=args.strategy_key,
            )
        raise ValueError(f"unknown command: {args.command}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
