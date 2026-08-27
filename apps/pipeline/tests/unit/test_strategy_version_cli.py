"""Behavioral and safety contracts for the StrategyVersion CLI.

The ``publish`` subcommand accepts the decision file, its reference,
and a trusted SHA-256 anchor. It reads the file once, verifies the
anchor before parsing or service invocation, and delegates every
cross-aggregate binding plus the approver allowlist check to
:class:`StrategyGovernanceService`. ``activate`` and ``get-active``
are unchanged from prior behavior.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_pipeline.config import get_settings
from invest_pipeline.strategy_version_cli import (
    activate_version,
    build_parser,
    get_active_view,
    main,
    publish_version,
    run,
)

DRAFT_ID = UUID("11111111-1111-4111-8111-111111111111")
AUDIT_ID = UUID("22222222-2222-4222-8222-222222222222")
STRATEGY_ID = UUID("33333333-3333-4333-8333-333333333333")
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
_ENV_ALIAS = "INVEST_PIPELINE_STRATEGY_APPROVER_AGENT_IDS"


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
        decision: object,
        decision_ref: str,
        decision_hash: str,
    ) -> object:
        self.publish_calls.append(
            {
                "decision": decision,
                "decision_ref": decision_ref,
                "decision_hash": decision_hash,
            }
        )
        assert self.publish_return is not None, "publish_return must be set"
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
    decision_path: Path, decision_hash: str | None = None, **overrides: object
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "decision_json_file": decision_path,
        "decision_ref": DECISION_REF,
        "expected_decision_sha256": decision_hash if decision_hash is not None else "0" * 64,
    }
    kwargs.update(overrides)
    return kwargs


def test_publish_returns_bounded_view_when_anchor_matches(tmp_path: Path) -> None:
    service = FakeService()
    service.publish_return = _build_stored()
    decision_path, decision_hash = _write_decision(
        tmp_path / "secret_home_user", _decision_payload()
    )

    result = publish_version(
        service=service, **_publish_kwargs(decision_path, decision_hash)
    )

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
    assert set(call) == {"decision", "decision_ref", "decision_hash"}
    assert call["decision_ref"] == DECISION_REF
    assert call["decision_hash"] == decision_hash
    assert call["decision"].decided_by_agent_id == APPROVER_AGENT_ID
    assert call["decision"].decision == "approve"
    assert call["decision"].draft_id == DRAFT_ID
    assert call["decision"].audit_id == AUDIT_ID
    assert call["decision"].artifact_hash == ARTIFACT_HASH
    dumped = json.dumps(result)
    assert "Approve strategy v1" not in dumped
    assert "secret_home_user" not in dumped
    assert "decision.json" not in dumped


@pytest.mark.parametrize(
    "scenario",
    [
        "wrong_hash", "symlink", "bad_json", "unknown_field", "missing_field",
        "bad_uuid", "bad_time", "naive_time", "non_approve",
    ],
)
def test_publish_rejects_invalid_inputs(tmp_path: Path, scenario: str) -> None:
    """Each malformed input must raise before the service is called."""
    service = FakeService()
    parent = tmp_path / scenario
    if scenario == "wrong_hash":
        decision_path, _ = _write_decision(parent, _decision_payload())
        anchor = "0" * 64
    elif scenario == "symlink":
        real = parent / "real"
        real.mkdir(parents=True, exist_ok=True)
        real_decision, real_hash = _write_decision(real, _decision_payload())
        link = parent / "link.json"
        link.symlink_to(real_decision)
        decision_path, anchor = link, real_hash
    elif scenario == "bad_json":
        parent.mkdir(parents=True, exist_ok=True)
        decision_path = parent / "decision.json"
        decision_path.write_bytes(b"\xff\xfe")
        anchor = hashlib.sha256(b"\xff\xfe").hexdigest()
    elif scenario == "unknown_field":
        decision_path, anchor = _write_decision(
            parent, _decision_payload(extra="nope")
        )
    elif scenario == "missing_field":
        payload = _decision_payload()
        del payload["statement"]
        decision_path, anchor = _write_decision(parent, payload)
    elif scenario == "bad_uuid":
        decision_path, anchor = _write_decision(
            parent, _decision_payload(draft_id="not-a-uuid")
        )
    elif scenario == "bad_time":
        decision_path, anchor = _write_decision(
            parent, _decision_payload(decided_at="not-a-datetime")
        )
    elif scenario == "naive_time":
        decision_path, anchor = _write_decision(
            parent, _decision_payload(decided_at="2026-08-26T12:00:00")
        )
    else:  # non_approve
        decision_path, anchor = _write_decision(
            parent, _decision_payload(decision="reject")
        )

    with pytest.raises((TypeError, ValueError)):
        publish_version(
            service=service, **_publish_kwargs(decision_path, anchor)
        )
    assert service.publish_calls == []


def test_publish_mismatching_anchor_rejects_before_service(tmp_path: Path) -> None:
    """Trusted-hash mismatch must raise before any service invocation."""
    service = FakeService()
    service.publish_return = _build_stored()
    decision_path, _ = _write_decision(tmp_path / "decision", _decision_payload())

    with pytest.raises(ValueError, match="integrity"):
        publish_version(
            service=service, **_publish_kwargs(decision_path, "0" * 64)
        )
    assert service.publish_calls == []


def test_run_publish_redacts_failures_and_emits_safe_json(tmp_path: Path) -> None:
    service = FakeService()
    service.publish_return = _build_stored()
    decision_path, decision_hash = _write_decision(
        tmp_path / "decision", _decision_payload()
    )
    out, err = io.StringIO(), io.StringIO()

    assert (
        run(
            "publish",
            stdout=out,
            stderr=err,
            service=service,
            **_publish_kwargs(decision_path, decision_hash),
        )
        == 0
    )
    assert set(json.loads(out.getvalue())) == VIEW_KEYS

    bad_kwargs = _publish_kwargs(Path("/secret/decision.json"))
    assert run("publish", stdout=out, stderr=err, service=service, **bad_kwargs) == 1
    assert err.getvalue() == "error: strategy version operation failed\n"
    assert "/secret" not in err.getvalue()
    assert "secret" not in err.getvalue()
    assert "Traceback" not in err.getvalue()


def test_parser_publish_requires_three_arguments(tmp_path: Path) -> None:
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
    ]
    args = parser.parse_args(base)
    assert args.command == "publish"
    assert args.decision_json_file == decision_path
    assert args.decision_ref == DECISION_REF
    assert args.expected_decision_sha256 == "0" * 64

    for missing in (
        [
            "publish", "--decision-ref", DECISION_REF,
            "--expected-decision-sha256", "0" * 64,
        ],
        [
            "publish", "--decision-json-file", str(decision_path),
            "--expected-decision-sha256", "0" * 64,
        ],
        ["publish", "--decision-json-file", str(decision_path), "--decision-ref", DECISION_REF],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(missing)


@pytest.mark.parametrize(
    "removed_flag",
    [
        "--expected-draft-id",
        "--expected-audit-id",
        "--expected-strategy-key",
        "--expected-version",
        "--expected-artifact-hash",
        "--expected-approver-agent-id",
    ],
)
def test_parser_publish_rejects_removed_legacy_arguments(
    tmp_path: Path, removed_flag: str
) -> None:
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
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(base + [removed_flag, "x"])


@pytest.fixture
def _isolated_settings(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.delenv(_ENV_ALIAS, raising=False)
    yield monkeypatch
    get_settings.cache_clear()


def _patch_storage_stack(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
) -> type:
    """Stub the storage layer and return a StrategyGovernanceService stub."""

    monkeypatch.setattr(
        "invest_storage.database.build_engine",
        lambda _url: MagicMock(name="Engine"),
    )
    monkeypatch.setattr(
        "invest_storage.database.session_factory",
        lambda _engine: MagicMock(name="Factory"),
    )
    monkeypatch.setattr(
        "invest_storage.unit_of_work.SqlAlchemyUnitOfWork",
        lambda _factory: MagicMock(name="Uow"),
    )

    class CapturingService:
        def __init__(self, *, uow_factory, authorized_approver_agent_ids, clock=None):
            captured["uow_factory"] = uow_factory
            captured["authorized_approver_agent_ids"] = authorized_approver_agent_ids
            captured["clock"] = clock

        def publish_approved_version(self, *, decision, decision_ref, decision_hash):
            stored = _build_stored()
            object.__setattr__(stored, "decision_hash", decision_hash)
            return stored

    monkeypatch.setattr(
        "invest_pipeline.strategy_version_cli.StrategyGovernanceService",
        CapturingService,
    )
    return CapturingService


def test_main_publish_wires_configured_approver_allowlist(
    tmp_path: Path, _isolated_settings: pytest.MonkeyPatch
) -> None:
    _isolated_settings.setenv(_ENV_ALIAS, json.dumps(["alpha", "beta"]))
    captured: dict[str, object] = {}
    _patch_storage_stack(_isolated_settings, captured)
    decision_path, decision_hash = _write_decision(
        tmp_path / "decision", _decision_payload()
    )

    rc = main(
        [
            "publish",
            "--decision-json-file",
            str(decision_path),
            "--decision-ref",
            DECISION_REF,
            "--expected-decision-sha256",
            decision_hash,
        ]
    )

    assert rc == 0
    assert captured["authorized_approver_agent_ids"] == ("alpha", "beta")


def test_main_publish_passes_empty_allowlist_fail_closed(
    tmp_path: Path, _isolated_settings: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_storage_stack(_isolated_settings, captured)
    decision_path, decision_hash = _write_decision(
        tmp_path / "decision", _decision_payload()
    )

    rc = main(
        [
            "publish",
            "--decision-json-file",
            str(decision_path),
            "--decision-ref",
            DECISION_REF,
            "--expected-decision-sha256",
            decision_hash,
        ]
    )

    assert rc == 0
    assert captured["authorized_approver_agent_ids"] == ()


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


@pytest.mark.parametrize("argv", [[], ["activate"], ["get-active"]])
def test_parser_requires_command_or_core_subcommand_args(argv: list[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)
