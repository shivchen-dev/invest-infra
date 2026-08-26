from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

import pytest
from invest_domain.strategy import StrategyAudit, StrategyAuditVerdict

AUDIT_ID = UUID("57a4b2d4-65cf-44b6-a7e4-7cedf5691a4d")
DRAFT_ID = UUID("f184c306-220c-41f9-8ae8-8f7b540d619c")
HASH = "a" * 64
REPORT_HASH = "b" * 64
NOW = datetime(2026, 8, 26, 15, 20, tzinfo=UTC)


def _kwargs(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "audit_id": AUDIT_ID,
        "draft_id": DRAFT_ID,
        "artifact_hash": HASH,
        "agentoa_task_id": "tsk_75cab57292fb4e66",
        "auditor_agent_id": "agt_da9c59be9add6176",
        "verdict": StrategyAuditVerdict.CHANGES_REQUIRED,
        "findings": ({"code": "DATA_GAP", "details": {"fields": ["volume_ratio"]}},),
        "limitations": ("No historical order-book data",),
        "report_ref": "audit.json",
        "report_hash": REPORT_HASH,
        "audited_at": NOW,
        "created_at": NOW,
    }
    values.update(changes)
    return values


def test_create_is_deterministic_and_deeply_freezes_findings() -> None:
    finding = {"code": "DATA_GAP", "details": {"fields": ["volume_ratio"]}}
    audit = StrategyAudit.create(
        draft_id=DRAFT_ID,
        artifact_hash=HASH,
        agentoa_task_id="tsk_75cab57292fb4e66",
        auditor_agent_id="agt_da9c59be9add6176",
        verdict="changes_required",
        findings=[finding],
        limitations=[" No historical order-book data "],
        report_ref=" reports/audit.json ",
        report_hash=REPORT_HASH,
        audit_id_factory=lambda: AUDIT_ID,
        clock=lambda: NOW,
    )

    finding["details"]["fields"].append("turnover")  # type: ignore[index,union-attr]
    assert audit.audit_id == AUDIT_ID
    assert audit.verdict is StrategyAuditVerdict.CHANGES_REQUIRED
    assert audit.findings[0]["details"]["fields"] == ("volume_ratio",)
    assert isinstance(audit.findings[0], MappingProxyType)
    assert audit.limitations == ("No historical order-book data",)
    assert audit.report_ref == "reports/audit.json"


@pytest.mark.parametrize("verdict", ["pass", "changes_required", "reject"])
def test_accepts_only_contract_verdicts(verdict: str) -> None:
    assert StrategyAudit(**_kwargs(verdict=verdict)).verdict.value == verdict


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audit_id", UUID(int=0)),
        ("draft_id", UUID(int=0)),
        ("artifact_hash", "A" * 64),
        ("agentoa_task_id", " "),
        ("agentoa_task_id", "tsk_bad/path"),
        ("auditor_agent_id", ""),
        ("auditor_agent_id", "agt_bad\nidentity"),
        ("verdict", "approved"),
        ("limitations", ("",)),
        ("report_ref", "/tmp/audit.json"),
        ("report_ref", "../audit.json"),
        ("report_hash", "bad"),
        ("audited_at", datetime(2026, 8, 26)),
        ("created_at", datetime(2026, 8, 26)),
    ],
)
def test_rejects_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        StrategyAudit(**_kwargs(**{field: value}))


@pytest.mark.parametrize(
    "findings",
    ["not-a-sequence", ({1: "non-string-key"},), ({"bad": object()},), ({"bad": float("nan")},)],
)
def test_findings_must_be_structured_json_content(findings: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        StrategyAudit(**_kwargs(findings=findings))


def test_aggregate_is_immutable() -> None:
    audit = StrategyAudit(**_kwargs())
    with pytest.raises(FrozenInstanceError):
        audit.verdict = StrategyAuditVerdict.PASS  # type: ignore[misc]
    with pytest.raises(TypeError):
        audit.findings[0]["code"] = "changed"  # type: ignore[index]
