"""Behavioral and safety contracts for the StrategyVersion CLI."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from invest_pipeline.strategy_version_cli import (
    activate_version,
    build_parser,
    get_active_view,
    publish_version,
    run,
)

DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
AUDIT_ID = UUID("22222222-2222-4222-8222-222222222222")
STRATEGY_ID = UUID("33333333-3333-4333-8333-333333333333")
OTHER_DRAFT_ID = UUID("44444444-4444-4444-8444-444444444444")
OTHER_AUDIT_ID = UUID("55555555-5555-4555-8555-555555555555")
ARTIFACT_HASH = "a" * 64
DECISION_REF = "decisions/2026/08/sample.json"
STRATEGY_KEY = "sector-strength"
PROPOSED_VERSION = "v1"
APPROVER_AGENT_ID = "cia:approver:alpha"
APPROVED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 26, 12, 5, tzinfo=UTC)
ACTIVATED_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
VIEW_KEYS = frozenset(
    {
        "strategy_id",
        "key",
        "version",
        "artifact_ref",
        "artifact_hash",
        "decision_ref",
        "decision_hash",
        "audit_id",
        "approved_at",
        "activated_at",
        "created_at",
    }
)


class FakeService:
    def __init__(self) -> None:
        self.publish_calls: list[dict[str, object]] = []
        self.activate_calls: list[dict[str, object]] = []
        self.get_active_calls: list[str] = []
        self.publish_return: object | None = None
        self.activate_return: object | None = None
        self.get_active_return: object | None = None

    def publish_approved_version(
        self,
        *,
        draft_id: UUID,
        audit_id: UUID,
        expected_strategy_key: str,
        expected_version: str,
        decision: object,
        decision_ref: str,
        decision_hash: str,
    ) -> object:
        self.publish_calls.append(
            {
                "draft_id": draft_id,
                "audit_id": audit_id,
                "expected_strategy_key": expected_strategy_key,
                "expected_version": expected_version,
                "decision": decision,
                "decision_ref": decision_ref,
                "decision_hash": decision_hash,
            }
        )
        assert self.publish_return is not None, "publish_return must be set"
        # Mirror StrategyGovernanceService: the stored aggregate carries the
        # decision_hash the CLI asked to bind, not a fabricated one.
        object.__setattr__(self.publish_return, "decision_hash", decision_hash)
        return self.publish_return

    def activate_version(
        self,
        *,
        strategy_id: UUID,
        version: str,
        at: datetime | None = None,
    ) -> object:
        self.activate_calls.append({"strategy_id": strategy_id, "version": version, "at": at})
        assert self.activate_return is not None, "activate_return must be set"
        return self.activate_return

    def get_active_version(self, strategy_key: str) -> object | None:
        self.get_active_calls.append(strategy_key)
        return self.get_active_return


def _build_stored(activated_at: datetime | None = None):
    from invest_domain.strategy import StrategyVersion

    return StrategyVersion(
        strategy_id=STRATEGY_ID,
        strategy_key=STRATEGY_KEY,
        version=PROPOSED_VERSION,
        artifact_ref=f"strategies/{STRATEGY_KEY}/{ARTIFACT_HASH}/strategy.json",
        artifact_hash=ARTIFACT_HASH,
        source_hashes=("b" * 64,),
        decision_ref=DECISION_REF,
        decision_hash="d" * 64,
        decided_by_agent_id=APPROVER_AGENT_ID,
        audit_id=AUDIT_ID,
        approved_at=APPROVED_AT,
        activated_at=activated_at,
        created_at=CREATED_AT,
    )


def _decision_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "draft_id": str(DRAFT_ID),
        "artifact_hash": ARTIFACT_HASH,
        "audit_id": str(AUDIT_ID),
        "decision": "approve",
        "decided_by": "Approver Alpha",
        "decided_by_agent_id": APPROVER_AGENT_ID,
        "decided_at": "2026-08-26T12:00:00Z",
        "limitations": ["no backtest"],
        "statement": "Approve strategy v1",
    }
    payload.update(overrides)
    return payload


def _write_decision(parent: Path, payload: dict[str, object]) -> tuple[Path, str]:
    parent.mkdir(parents=True, exist_ok=True)
    decision = parent / "decision.json"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    decision.write_bytes(data)
    return decision, hashlib.sha256(data).hexdigest()


def _publish_kwargs(
    decision_path: Path, decision_hash: str, **overrides: object
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "decision_json_file": decision_path,
        "decision_ref": DECISION_REF,
        "expected_decision_sha256": decision_hash,
        "expected_draft_id": str(DRAFT_ID),
        "expected_audit_id": str(AUDIT_ID),
        "expected_strategy_key": STRATEGY_KEY,
        "expected_version": PROPOSED_VERSION,
        "expected_artifact_hash": ARTIFACT_HASH,
        "expected_approver_agent_id": APPROVER_AGENT_ID,
    }
    kwargs.update(overrides)
    return kwargs


def test_publish_returns_bounded_view_and_binds_arguments(tmp_path: Path) -> None:
    service = FakeService()
    service.publish_return = _build_stored()
    decision_path, decision_hash = _write_decision(
        tmp_path / "secret_home_user", _decision_payload()
    )

    result = publish_version(service=service, **_publish_kwargs(decision_path, decision_hash))

    assert set(result) == VIEW_KEYS
    assert result["strategy_id"] == str(STRATEGY_ID)
    assert result["key"] == STRATEGY_KEY
    assert result["version"] == PROPOSED_VERSION
    assert result["decision_ref"] == DECISION_REF
    assert result["decision_hash"] == decision_hash
    assert result["audit_id"] == str(AUDIT_ID)
    assert result["approved_at"] == APPROVED_AT.isoformat()
    assert result["activated_at"] is None
    assert result["created_at"] == CREATED_AT.isoformat()

    assert len(service.publish_calls) == 1
    call = service.publish_calls[0]
    assert call["draft_id"] == DRAFT_ID
    assert call["audit_id"] == AUDIT_ID
    assert call["expected_strategy_key"] == STRATEGY_KEY
    assert call["expected_version"] == PROPOSED_VERSION
    assert call["decision"].decided_by_agent_id == APPROVER_AGENT_ID
    assert call["decision"].decision == "approve"
    assert call["decision"].draft_id == DRAFT_ID
    assert call["decision"].audit_id == AUDIT_ID
    assert call["decision"].artifact_hash == ARTIFACT_HASH
    assert call["decision_ref"] == DECISION_REF
    assert call["decision_hash"] == decision_hash
    dumped = json.dumps(result)
    assert "Approve strategy v1" not in dumped
    assert "secret_home_user" not in dumped
    assert "decision.json" not in dumped


@pytest.mark.parametrize(
    "scenario",
    [
        "symlink", "bad_json", "unknown_field", "missing_field",
        "bad_uuid", "bad_time", "naive_time", "non_approve", "wrong_hash",
    ],
)
def test_publish_rejects_invalid_inputs(tmp_path: Path, scenario: str) -> None:
    """Each malformed input must raise before the service is called."""
    service = FakeService()
    parent = tmp_path / scenario
    if scenario == "symlink":
        real = parent / "real"
        real.mkdir(parents=True, exist_ok=True)
        real_decision, real_hash = _write_decision(real, _decision_payload())
        link = parent / "link.json"
        link.symlink_to(real_decision)
        decision_path, decision_hash = link, real_hash
    elif scenario == "bad_json":
        parent.mkdir(parents=True, exist_ok=True)
        decision_path = parent / "decision.json"
        bad = b"\xff\xfe"
        decision_path.write_bytes(bad)
        decision_hash = hashlib.sha256(bad).hexdigest()
    elif scenario == "unknown_field":
        payload = _decision_payload(extra="nope")
        decision_path, decision_hash = _write_decision(parent, payload)
    elif scenario == "missing_field":
        payload = _decision_payload()
        del payload["statement"]
        decision_path, decision_hash = _write_decision(parent, payload)
    elif scenario == "bad_uuid":
        payload = _decision_payload(draft_id="not-a-uuid")
        decision_path, decision_hash = _write_decision(parent, payload)
    elif scenario == "bad_time":
        payload = _decision_payload(decided_at="not-a-datetime")
        decision_path, decision_hash = _write_decision(parent, payload)
    elif scenario == "naive_time":
        payload = _decision_payload(decided_at="2026-08-26T12:00:00")
        decision_path, decision_hash = _write_decision(parent, payload)
    elif scenario == "non_approve":
        payload = _decision_payload(decision="reject")
        decision_path, decision_hash = _write_decision(parent, payload)
    else:  # wrong_hash
        decision_path, _ = _write_decision(parent, _decision_payload())
        decision_hash = "0" * 64

    with pytest.raises((TypeError, ValueError)):
        publish_version(
            service=service,
            **_publish_kwargs(decision_path, decision_hash),
        )
    assert service.publish_calls == []


@pytest.mark.parametrize(
    ("expected_arg", "value"),
    [
        ("expected_draft_id", str(OTHER_DRAFT_ID)),
        ("expected_audit_id", str(OTHER_AUDIT_ID)),
        ("expected_artifact_hash", "f" * 64),
        ("expected_approver_agent_id", "cia:approver:rogue"),
    ],
)
def test_publish_rejects_each_expected_binding(
    tmp_path: Path, expected_arg: str, value: object
) -> None:
    """Each expected binding must be verified before the service is called."""
    service = FakeService()
    decision_path, decision_hash = _write_decision(tmp_path / "decision", _decision_payload())
    overrides = {expected_arg: value}

    with pytest.raises((TypeError, ValueError)):
        publish_version(
            service=service,
            **_publish_kwargs(decision_path, decision_hash, **overrides),
        )
    assert service.publish_calls == []


def test_run_redacts_failures_and_emits_safe_json(tmp_path: Path) -> None:
    service = FakeService()
    service.publish_return = _build_stored()
    decision_path, decision_hash = _write_decision(tmp_path / "decision", _decision_payload())
    out, err = io.StringIO(), io.StringIO()

    kwargs = _publish_kwargs(decision_path, decision_hash)
    assert run("publish", stdout=out, stderr=err, service=service, **kwargs) == 0
    assert set(json.loads(out.getvalue())) == VIEW_KEYS

    bad = kwargs | {"decision_json_file": "/secret/decision.json"}
    assert run("publish", stdout=out, stderr=err, service=service, **bad) == 1
    assert err.getvalue() == "error: strategy version operation failed\n"
    assert "/secret" not in err.getvalue()
    assert "secret" not in err.getvalue()
    assert "Traceback" not in err.getvalue()


# === Activate =====================================================


def test_activate_returns_bounded_view_and_forwards_arguments() -> None:
    service = FakeService()
    service.activate_return = _build_stored(activated_at=ACTIVATED_AT)

    result = activate_version(
        service=service,
        strategy_id=str(STRATEGY_ID),
        version=PROPOSED_VERSION,
    )

    assert set(result) == VIEW_KEYS
    assert result["strategy_id"] == str(STRATEGY_ID)
    assert result["activated_at"] == ACTIVATED_AT.isoformat()
    assert len(service.activate_calls) == 1
    assert service.activate_calls[0]["strategy_id"] == STRATEGY_ID
    assert service.activate_calls[0]["version"] == PROPOSED_VERSION

def test_run_activate_redacts_invalid_uuid_and_emits_constant_stderr() -> None:
    service = FakeService()
    out, err = io.StringIO(), io.StringIO()

    rc = run(
        "activate",
        stdout=out,
        stderr=err,
        service=service,
        strategy_id="not-a-uuid",
        version=PROPOSED_VERSION,
    )

    assert rc == 1
    assert err.getvalue() == "error: strategy version operation failed\n"
    assert "not-a-uuid" not in err.getvalue()
    assert "Traceback" not in err.getvalue()
    assert service.activate_calls == []


# === Get-active ===================================================


def test_get_active_returns_view_when_present() -> None:
    service = FakeService()
    service.get_active_return = _build_stored(activated_at=ACTIVATED_AT)

    result = get_active_view(service=service, strategy_key=STRATEGY_KEY)

    assert result is not None
    assert result["key"] == STRATEGY_KEY
    assert service.get_active_calls == [STRATEGY_KEY]


def test_get_active_none_prints_null_and_exits_zero() -> None:
    service = FakeService()
    service.get_active_return = None
    out, err = io.StringIO(), io.StringIO()

    assert (
        run(
            "get-active",
            stdout=out,
            stderr=err,
            service=service,
            strategy_key="absent",
        )
        == 0
    )
    assert out.getvalue().strip() == "null"
    assert service.get_active_calls == ["absent"]


def test_parser_requires_publish_args(tmp_path: Path) -> None:
    parser = build_parser()
    decision_path = tmp_path / "decision.json"
    decision_path.write_bytes(b"{}")
    base = [
        "publish",
        "--decision-json-file",
        str(decision_path),
        "--decision-ref",
        DECISION_REF,
        "--expected-decision-sha256",
        "0" * 64,
        "--expected-draft-id",
        str(DRAFT_ID),
        "--expected-audit-id",
        str(AUDIT_ID),
        "--expected-strategy-key",
        STRATEGY_KEY,
        "--expected-version",
        PROPOSED_VERSION,
        "--expected-artifact-hash",
        ARTIFACT_HASH,
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(base)


@pytest.mark.parametrize("argv", [[], ["activate"], ["get-active"]])
def test_parser_requires_command_or_core_subcommand_args(argv: list[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)
