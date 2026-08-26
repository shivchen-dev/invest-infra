"""Public-domain tests for :mod:`invest_domain.strategy.draft`.

These tests cover the pure-domain ``StrategyDraft`` tracer and its
``SourceRef`` companion. The slice corresponds to ``StrategyDraft``
registration under the candidate-strategies MVP plan v1.0 (Slice 0):

- ``StrategyDraft`` carries the immutable envelope of a pending
  strategy registration: stable identity, target key/version, immutable
  ``strategy.json`` reference and SHA-256, original source-material
  references, deterministic validation result, and registration
  timestamp.
- ``SourceRef`` captures one upstream business-material reference and its
  SHA-256.

Tests only exercise the publicly exported interface. No storage,
migration, API, CLI, StrategyAudit, StrategyVersion, AgentOA, extraction
or source files are pulled in here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest
from invest_domain.strategy.draft import SourceRef, StrategyDraft

_VALID_HASH = "a" * 64
_OTHER_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_FROZEN_CREATED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
_DRAFT_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


def _source_ref(ref: str = "source-document", content_hash: str = _VALID_HASH) -> SourceRef:
    return SourceRef(ref=ref, content_hash=content_hash)


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "strategy_key": "sector-strength",
        "proposed_version": "1.0.0",
        "artifact_ref": "strategy.json",
        "artifact_hash": _VALID_HASH,
        "source_refs": (_source_ref(),),
        "validation_result": {"status": "ok"},
        "draft_id": _DRAFT_ID,
        "created_at": _FROZEN_CREATED_AT,
    }
    base.update(overrides)
    return base


def test_source_ref_happy_construction() -> None:
    ref = SourceRef(ref="source-document", content_hash=_VALID_HASH)
    assert ref.ref == "source-document"
    assert ref.content_hash == _VALID_HASH


def test_source_ref_trims_ref() -> None:
    ref = SourceRef(ref="  source-document  ", content_hash=_VALID_HASH)
    assert ref.ref == "source-document"


def test_source_ref_rejects_uppercase_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        SourceRef(ref="doc", content_hash=_OTHER_HASH.upper())


def test_source_ref_rejects_blank_ref() -> None:
    with pytest.raises(ValueError, match="ref"):
        SourceRef(ref="   ", content_hash=_VALID_HASH)


def test_source_ref_rejects_non_string_ref() -> None:
    with pytest.raises(TypeError, match="ref"):
        SourceRef(ref=123, content_hash=_VALID_HASH)  # type: ignore[arg-type]


def test_source_ref_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        SourceRef(ref="doc", content_hash="not-a-hash")


def test_source_ref_rejects_short_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        SourceRef(ref="doc", content_hash="abcd")


def test_source_ref_rejects_non_hex_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        SourceRef(ref="doc", content_hash="g" * 64)


def test_source_ref_is_frozen() -> None:
    ref = SourceRef(ref="doc", content_hash=_VALID_HASH)
    with pytest.raises(FrozenInstanceError):
        ref.ref = "other"  # type: ignore[misc]


def test_strategy_draft_happy_construction() -> None:
    draft = StrategyDraft(**_kwargs())
    assert draft.draft_id == _DRAFT_ID
    assert draft.strategy_key == "sector-strength"
    assert draft.proposed_version == "1.0.0"
    assert draft.artifact_ref == "strategy.json"
    assert draft.artifact_hash == _VALID_HASH
    assert draft.source_refs == (_source_ref(),)
    assert dict(draft.validation_result) == {"status": "ok"}
    assert draft.created_at == _FROZEN_CREATED_AT


def test_strategy_draft_create_uses_injectable_factories() -> None:
    fixed_id = UUID("11111111-2222-3333-4444-555555555555")
    fixed_now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)

    def id_factory() -> UUID:
        return fixed_id

    def clock() -> datetime:
        return fixed_now

    draft = StrategyDraft.create(
        strategy_key="sector-strength",
        proposed_version="1.0.0",
        artifact_ref="strategy.json",
        artifact_hash=_VALID_HASH,
        source_refs=(_source_ref(),),
        validation_result={"status": "ok"},
        draft_id_factory=id_factory,
        clock=clock,
    )
    assert draft.draft_id == fixed_id
    assert draft.created_at == fixed_now


def test_strategy_draft_create_generates_default_id_and_time() -> None:
    draft = StrategyDraft.create(
        strategy_key="tdx-native-tools",
        proposed_version="1.0.0",
        artifact_ref="strategy.json",
        artifact_hash=_VALID_HASH,
        source_refs=(_source_ref(),),
        validation_result={},
    )
    assert isinstance(draft.draft_id, UUID)
    assert isinstance(draft.created_at, datetime)
    assert draft.created_at.tzinfo is not None
    assert draft.created_at.tzinfo.utcoffset(draft.created_at) is not None


def test_strategy_draft_create_accepts_iterable_source_refs() -> None:
    draft = StrategyDraft.create(
        strategy_key="sector-strength",
        proposed_version="1.0.0",
        artifact_ref="strategy.json",
        artifact_hash=_VALID_HASH,
        source_refs=[_source_ref()],
        validation_result={},
    )
    assert isinstance(draft.source_refs, tuple)
    assert draft.source_refs == (_source_ref(),)


def test_strategy_draft_trims_text_fields() -> None:
    draft = StrategyDraft(**_kwargs(
        strategy_key="  sector-strength  ",
        proposed_version="  1.0.0  ",
        artifact_ref="  strategy.json  ",
    ))
    assert draft.strategy_key == "sector-strength"
    assert draft.proposed_version == "1.0.0"
    assert draft.artifact_ref == "strategy.json"


def test_strategy_draft_stores_validation_result_as_immutable_mapping() -> None:
    payload: dict[str, Any] = {"status": "ok"}
    draft = StrategyDraft(**_kwargs(validation_result=payload))
    assert isinstance(draft.validation_result, MappingProxyType)
    assert isinstance(draft.validation_result, Mapping)
    # Mutating the original input must not leak into the aggregate's
    # outer mapping (shallow-copy contract).
    payload["status"] = "tampered"
    payload["new"] = "added"
    assert draft.validation_result["status"] == "ok"
    assert "new" not in draft.validation_result


def test_strategy_draft_validation_result_is_read_only() -> None:
    draft = StrategyDraft(**_kwargs())
    with pytest.raises(TypeError):
        draft.validation_result["new"] = "value"  # type: ignore[index]


def test_strategy_draft_accepts_mapping_subclass() -> None:
    class _CustomMapping(Mapping):
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def __getitem__(self, key: str) -> Any:
            return self._data[key]

        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    payload = _CustomMapping({"status": "ok"})
    draft = StrategyDraft(**_kwargs(validation_result=payload))
    assert draft.validation_result["status"] == "ok"


def test_strategy_draft_rejects_nil_uuid() -> None:
    with pytest.raises(ValueError, match="draft_id"):
        StrategyDraft(**_kwargs(draft_id=UUID(int=0)))


def test_strategy_draft_rejects_non_uuid() -> None:
    with pytest.raises(TypeError, match="draft_id"):
        StrategyDraft(**_kwargs(draft_id="not-a-uuid"))  # type: ignore[arg-type]


def test_strategy_draft_rejects_blank_strategy_key() -> None:
    with pytest.raises(ValueError, match="strategy_key"):
        StrategyDraft(**_kwargs(strategy_key="   "))


def test_strategy_draft_rejects_blank_proposed_version() -> None:
    with pytest.raises(ValueError, match="proposed_version"):
        StrategyDraft(**_kwargs(proposed_version="  "))


def test_strategy_draft_rejects_blank_artifact_ref() -> None:
    with pytest.raises(ValueError, match="artifact_ref"):
        StrategyDraft(**_kwargs(artifact_ref="\t"))


def test_strategy_draft_rejects_invalid_artifact_hash_length() -> None:
    with pytest.raises(ValueError, match="artifact_hash"):
        StrategyDraft(**_kwargs(artifact_hash="abc"))


def test_strategy_draft_rejects_non_hex_artifact_hash() -> None:
    bad = "z" * 64
    with pytest.raises(ValueError, match="artifact_hash"):
        StrategyDraft(**_kwargs(artifact_hash=bad))


def test_strategy_draft_rejects_uppercase_artifact_hash() -> None:
    with pytest.raises(ValueError, match="artifact_hash"):
        StrategyDraft(**_kwargs(artifact_hash=_OTHER_HASH.upper()))


def test_strategy_draft_rejects_empty_source_refs() -> None:
    with pytest.raises(ValueError, match="source_refs"):
        StrategyDraft(**_kwargs(source_refs=()))


def test_strategy_draft_rejects_list_source_refs() -> None:
    with pytest.raises(TypeError, match="source_refs"):
        StrategyDraft(**_kwargs(source_refs=[_source_ref()]))  # type: ignore[arg-type]


def test_strategy_draft_rejects_bare_source_ref() -> None:
    with pytest.raises(TypeError, match="source_refs"):
        StrategyDraft(**_kwargs(source_refs=_source_ref()))  # type: ignore[arg-type]


def test_strategy_draft_rejects_non_source_ref_entries() -> None:
    with pytest.raises(TypeError, match="source_refs"):
        StrategyDraft(**_kwargs(source_refs=("not-a-source-ref",)))  # type: ignore[arg-type]


def test_strategy_draft_rejects_non_mapping_validation_result() -> None:
    with pytest.raises(TypeError, match="validation_result"):
        StrategyDraft(**_kwargs(validation_result=[("k", "v")]))  # type: ignore[arg-type]


def test_strategy_draft_rejects_naive_created_at() -> None:
    naive = _FROZEN_CREATED_AT.replace(tzinfo=None)
    with pytest.raises(ValueError, match="created_at"):
        StrategyDraft(**_kwargs(created_at=naive))


def test_strategy_draft_rejects_non_datetime_created_at() -> None:
    with pytest.raises(TypeError, match="created_at"):
        StrategyDraft(**_kwargs(created_at="2026-08-26T12:00:00Z"))  # type: ignore[arg-type]


def test_strategy_draft_is_frozen() -> None:
    draft = StrategyDraft(**_kwargs())
    with pytest.raises(FrozenInstanceError):
        draft.strategy_key = "tampered"  # type: ignore[misc]


def test_strategy_draft_accepts_multiple_source_refs() -> None:
    draft = StrategyDraft(**_kwargs(source_refs=(
        _source_ref(ref="article-a", content_hash=_VALID_HASH),
        _source_ref(ref="article-b", content_hash=_OTHER_HASH),
    )))
    assert len(draft.source_refs) == 2
    assert draft.source_refs[0].ref == "article-a"
    assert draft.source_refs[1].ref == "article-b"