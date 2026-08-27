"""Public-domain tests for :mod:`invest_domain.strategy.version`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest
from invest_domain import strategy as strategy_pkg
from invest_domain.strategy import (
    DECISION_APPROVE,
    StrategyApprovalError,
    StrategyDecision,
    StrategyDecisionError,
    StrategyVersion,
    StrategyVersionAlreadyActiveError,
    StrategyVersionConflictError,
    StrategyVersionNotFoundError,
)

_HASH = "a" * 64
_HASH2 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_T = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
_SID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
_AID = UUID("22222222-bbbb-4ccc-8ddd-eeeeeeeeeeee")
_DID = UUID("11111111-2222-3333-4444-555555555555")
_OID = "agt_da9c59be9add6176"


def _dk(**o):
    d = {"schema_version": 1, "draft_id": _DID, "artifact_hash": _HASH,
         "audit_id": _AID, "decision": "approve", "decided_by": "human",
         "decided_by_agent_id": _OID, "decided_at": _T,
         "limitations": ("No historical data",), "statement": "Approve."}
    d.update(o)
    return d


def _vk(**o):
    d = {"strategy_id": _SID, "strategy_key": "sector-strength", "version": "1.0.0",
         "artifact_ref": "strategy.json", "artifact_hash": _HASH,
         "source_hashes": (_HASH, _HASH2), "decision_ref": "d.json",
         "decision_hash": _HASH, "decided_by_agent_id": _OID, "audit_id": _AID,
         "approved_at": _T, "activated_at": None, "created_at": _T}
    d.update(o)
    return d


def _vc(source_hashes=(_HASH,), **o):
    return StrategyVersion.create(strategy_key="sector-strength",
        version="1.0.0", artifact_ref="strategy.json", artifact_hash=_HASH,
        source_hashes=source_hashes, decision_ref="d.json", decision_hash=_HASH,
        decided_by_agent_id=_OID, audit_id=_AID, approved_at=_T, **o)


def test_decision_happy_construction():
    d = StrategyDecision(**_dk())
    assert d.schema_version == 1 and d.decision == "approve"
    assert d.draft_id == _DID and d.audit_id == _AID
    assert d.decided_at == _T
    assert d.limitations == ("No historical data",)


@pytest.mark.parametrize("raw", [False, True])
def test_decision_from_mapping_accepts_typed_and_raw_json_values(raw):
    payload = _dk()
    if raw:
        payload.update(
            draft_id=str(_DID),
            audit_id=str(_AID),
            decided_at=_T.isoformat(),
            limitations=["No historical data"],
        )

    decision = StrategyDecision.from_mapping(payload)

    assert decision.draft_id == _DID and decision.audit_id == _AID
    assert decision.decided_at == _T


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft_id", "not-a-uuid"),
        ("audit_id", "not-a-uuid"),
        ("decided_at", "not-a-datetime"),
        ("decided_at", "2026-08-27T09:00:00"),
    ],
)
def test_decision_from_mapping_rejects_bad_raw_values(field, value):
    with pytest.raises((TypeError, ValueError, StrategyDecisionError)):
        StrategyDecision.from_mapping(_dk(**{field: value}))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {**_dk(), "unknown": True},
        {key: value for key, value in _dk().items() if key != "statement"},
    ],
)
def test_decision_from_mapping_rejects_invalid_container_or_fields(payload):
    with pytest.raises(StrategyDecisionError):
        StrategyDecision.from_mapping(payload)


def test_version_happy_construction():
    v = StrategyVersion(**_vk(activated_at=_T))
    assert v.strategy_id == _SID and v.audit_id == _AID
    assert v.source_hashes == (_HASH, _HASH2)
    assert v.activated_at == _T


def test_version_create_uses_injectable_hooks():
    fid = UUID("33333333-2222-3333-4444-555555555555")
    fn = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)
    v = _vc(strategy_id_factory=lambda: fid, clock=lambda: fn)
    assert v.strategy_id == fid and v.created_at == fn


def test_version_create_defaults_generate_uuid_and_utc_time():
    v = _vc()
    assert isinstance(v.strategy_id, UUID) and v.strategy_id != UUID(int=0)
    assert isinstance(v.created_at, datetime)
    assert v.created_at.tzinfo is not None


def test_version_create_coerces_iterable_source_hashes_to_tuple():
    v = _vc(source_hashes=[_HASH, _HASH2])
    assert isinstance(v.source_hashes, tuple)
    assert v.source_hashes == (_HASH, _HASH2)


def test_decision_is_frozen():
    with pytest.raises(FrozenInstanceError):
        StrategyDecision(**_dk()).statement = "x"  # type: ignore[misc]


def test_version_is_frozen():
    with pytest.raises(FrozenInstanceError):
        StrategyVersion(**_vk()).strategy_key = "x"  # type: ignore[misc]


@pytest.mark.parametrize(("f", "v"), [
    ("draft_id", UUID(int=0)), ("audit_id", UUID(int=0)),
    ("artifact_hash", _HASH2.upper()), ("artifact_hash", "abc"),
    ("artifact_hash", "g" * 64),
    ("decided_by_agent_id", "agt_bad/path"), ("decided_by_agent_id", ""),
    ("decided_at", _T.replace(tzinfo=None)),
    ("limitations", ("  ",)), ("statement", "   ")])
def test_decision_rejects_invalid_shape(f, v):
    with pytest.raises((TypeError, ValueError, StrategyDecisionError)):
        StrategyDecision(**_dk(**{f: v}))


@pytest.mark.parametrize(("f", "v"), [
    ("strategy_id", UUID(int=0)), ("audit_id", UUID(int=0)),
    ("artifact_hash", _HASH2.upper()), ("artifact_hash", "abc"),
    ("decided_by_agent_id", "agt_bad\nidentity"),
    ("decided_by_agent_id", "-bad"),
    ("approved_at", _T.replace(tzinfo=None)),
    ("source_hashes", ()), ("source_hashes", [_HASH, "short"]),
    ("limitations", ("",))])
def test_version_rejects_invalid_shape(f, v):
    with pytest.raises((TypeError, ValueError, StrategyApprovalError)):
        StrategyVersion(**_vk(**{f: v}))


@pytest.mark.parametrize(("sv", "raises"), [(1, False), (True, True), (2, True)])
def test_decision_schema_version_must_be_int_one(sv, raises):
    if raises:
        with pytest.raises((TypeError, ValueError, StrategyDecisionError)):
            StrategyDecision(**_dk(schema_version=sv))
    else:
        assert StrategyDecision(**_dk(schema_version=sv)).schema_version == 1


@pytest.mark.parametrize("decision", ["approve", "reject", "approved", ""])
def test_decision_field_must_equal_approve(decision):
    if decision == DECISION_APPROVE:
        assert StrategyDecision(**_dk(decision=decision)).decision == "approve"
    else:
        with pytest.raises(StrategyDecisionError):
            StrategyDecision(**_dk(decision=decision))


def test_decision_limitations_must_be_non_string_sequence():
    with pytest.raises(TypeError):
        StrategyDecision(**_dk(limitations="just-a-string"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        StrategyDecision(**_dk(limitations=("blank", "  ")))


def test_version_source_hashes_must_be_nonempty_valid_tuples():
    v = StrategyVersion(**_vk())
    assert isinstance(v.source_hashes, tuple) and len(v.source_hashes) >= 1
    for e in v.source_hashes:
        assert len(e) == 64 and all(c in "0123456789abcdef" for c in e)
    with pytest.raises(TypeError):
        StrategyVersion(**_vk(source_hashes="not-a-sequence"))  # type: ignore[arg-type]


def test_version_activated_at_cannot_precede_approved_at():
    earlier = _T.replace(hour=7)
    with pytest.raises(StrategyApprovalError):
        StrategyVersion(**_vk(activated_at=earlier))
    assert StrategyVersion(**_vk(activated_at=_T)).activated_at == _T
    assert StrategyVersion(**_vk(activated_at=None)).activated_at is None


def test_public_exports_and_error_inheritance():
    assert strategy_pkg.DECISION_APPROVE == "approve"
    assert strategy_pkg.DECISION_SCHEMA_VERSION == 1
    assert strategy_pkg.StrategyDecision is StrategyDecision
    assert strategy_pkg.StrategyVersion is StrategyVersion
    for n in ("DECISION_APPROVE", "DECISION_SCHEMA_VERSION", "StrategyDecision",
              "StrategyDecisionError", "StrategyApprovalError", "StrategyVersion",
              "StrategyVersionConflictError", "StrategyVersionNotFoundError",
              "StrategyVersionAlreadyActiveError"):
        assert n in strategy_pkg.__all__ and hasattr(strategy_pkg, n)
    assert issubclass(StrategyDecisionError, ValueError)
    assert issubclass(StrategyApprovalError, ValueError)
    assert issubclass(StrategyVersionConflictError, RuntimeError)
    assert issubclass(StrategyVersionNotFoundError, LookupError)
    assert issubclass(StrategyVersionAlreadyActiveError, RuntimeError)
