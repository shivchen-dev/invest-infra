"""Mock tests for ``SqlAlchemyStrategyDraftRepository`` (Slice 0)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.strategy import SourceRef, StrategyDraft
from invest_storage.models import StrategyDraftRow
from invest_storage.repositories import (
    SqlAlchemyStrategyDraftRepository,
    StrategyDraftConflictError,
)
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Session

_STRATEGY_KEY = "sector-strength"
_PROPOSED_VERSION = "1.0.0"
_VALID_HASH = "a" * 64
_OTHER_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_FROZEN_CREATED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
_FROZEN_DRAFT_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


def _draft(
    *,
    strategy_key: str = _STRATEGY_KEY,
    proposed_version: str = _PROPOSED_VERSION,
    artifact_hash: str = _VALID_HASH,
    source_refs: tuple[SourceRef, ...] = (
        SourceRef(ref="source-document", content_hash=_VALID_HASH),
    ),
    validation_result: dict[str, Any] | None = None,
    draft_id: UUID | None = None,
) -> StrategyDraft:
    return StrategyDraft.create(
        strategy_key=strategy_key,
        proposed_version=proposed_version,
        artifact_ref="strategy.json",
        artifact_hash=artifact_hash,
        source_refs=source_refs,
        validation_result=validation_result if validation_result is not None else {"status": "ok"},
        draft_id=draft_id or _FROZEN_DRAFT_ID,
        created_at=_FROZEN_CREATED_AT,
    )


def _row(draft: StrategyDraft) -> MagicMock:
    row = MagicMock(spec=StrategyDraftRow)
    row.draft_id = draft.draft_id
    row.strategy_key = draft.strategy_key
    row.proposed_version = draft.proposed_version
    row.artifact_ref = draft.artifact_ref
    row.artifact_hash = draft.artifact_hash
    row.source_refs = [{"ref": i.ref, "content_hash": i.content_hash} for i in draft.source_refs]
    row.validation_result = dict(draft.validation_result)
    row.created_at = draft.created_at
    return row


def _repo() -> tuple[SqlAlchemyStrategyDraftRepository, MagicMock]:
    session = MagicMock(spec=Session)
    session.scalars.return_value.first.return_value = None
    return SqlAlchemyStrategyDraftRepository(session), session


class InsertTests(unittest.TestCase):
    def test_add_inserts_row_and_returns_draft(self) -> None:
        repo, session = _repo()
        draft = _draft()

        result = repo.add(draft)

        self.assertEqual(result, draft)
        session.add.assert_called_once()
        persisted = session.add.call_args.args[0]
        self.assertIsInstance(persisted, StrategyDraftRow)
        for attr in ("draft_id", "strategy_key", "proposed_version",
                     "artifact_ref", "artifact_hash", "created_at"):
            self.assertEqual(getattr(persisted, attr), getattr(draft, attr))
        expected_refs = [{"ref": i.ref, "content_hash": i.content_hash} for i in draft.source_refs]
        self.assertEqual(persisted.source_refs, expected_refs)
        self.assertEqual(persisted.validation_result, dict(draft.validation_result))

    def test_add_rejects_non_strategy_draft(self) -> None:
        repo, session = _repo()
        with self.assertRaises(TypeError):
            repo.add({"draft_id": uuid4()})  # type: ignore[arg-type]
        session.add.assert_not_called()

    def test_add_is_idempotent_when_pair_and_hash_match(self) -> None:
        repo, session = _repo()
        draft = _draft()
        session.scalars.return_value.first.return_value = _row(draft)

        self.assertEqual(repo.add(draft), draft)
        session.add.assert_not_called()

    def test_add_ignores_other_fields_when_pair_and_hash_match(self) -> None:
        repo, session = _repo()
        draft = _draft()
        existing = _row(draft)
        existing.source_refs = [{"ref": "different-source", "content_hash": _VALID_HASH}]
        existing.validation_result = {"status": "different"}
        session.scalars.return_value.first.return_value = existing

        result = repo.add(draft)

        # Same pair + hash → no conflict; existing row's values win.
        self.assertEqual(result.source_refs[0].ref, "different-source")
        self.assertEqual(result.validation_result, {"status": "different"})
        session.add.assert_not_called()

    def test_add_raises_conflict_when_same_pair_different_hash(self) -> None:
        repo, session = _repo()
        draft = _draft()
        existing = _row(draft)
        existing.artifact_hash = _OTHER_HASH
        session.scalars.return_value.first.return_value = existing

        with self.assertRaises(StrategyDraftConflictError):
            repo.add(draft)
        session.add.assert_not_called()

    def test_add_raises_conflict_when_same_hash_different_pair(self) -> None:
        repo, session = _repo()
        draft = _draft()
        existing = _row(draft)
        existing.strategy_key = "other-key"
        existing.proposed_version = "2.0.0"
        first, second = MagicMock(), MagicMock()
        first.first.return_value = None
        second.first.return_value = existing
        session.scalars.side_effect = [first, second]

        with self.assertRaises(StrategyDraftConflictError):
            repo.add(draft)
        session.add.assert_not_called()


class ReadTests(unittest.TestCase):
    """Mock tests for the read paths."""

    def test_get_by_id_returns_existing_draft(self) -> None:
        repo, session = _repo()
        draft = _draft(
            source_refs=(
                SourceRef(ref="src-a", content_hash=_VALID_HASH),
                SourceRef(ref="src-b", content_hash=_OTHER_HASH),
            ),
            validation_result={"status": "ok", "checks": {"schema": True}},
        )
        session.get.return_value = _row(draft)

        result = repo.get_by_id(draft.draft_id)

        self.assertEqual(result, draft)
        self.assertEqual(len(result.source_refs), 2)
        self.assertEqual(result.source_refs[0].ref, "src-a")
        self.assertEqual(result.source_refs[1].content_hash, _OTHER_HASH)
        session.get.assert_called_once_with(StrategyDraftRow, draft.draft_id)

    def test_get_by_id_returns_none_when_absent(self) -> None:
        repo, session = _repo()
        session.get.return_value = None
        self.assertIsNone(repo.get_by_id(uuid4()))

    def test_get_by_artifact_hash_returns_existing(self) -> None:
        repo, session = _repo()
        draft = _draft()
        session.scalars.return_value.first.return_value = _row(draft)
        self.assertEqual(repo.get_by_artifact_hash(draft.artifact_hash), draft)

    def test_get_by_artifact_hash_returns_none_when_absent(self) -> None:
        repo, _ = _repo()
        self.assertIsNone(repo.get_by_artifact_hash(_VALID_HASH))

    def test_get_by_strategy_key_proposed_version_returns_existing(self) -> None:
        repo, session = _repo()
        draft = _draft()
        session.scalars.return_value.first.return_value = _row(draft)
        self.assertEqual(
            repo.get_by_strategy_key_proposed_version(
                draft.strategy_key, draft.proposed_version,
            ),
            draft,
        )

    def test_get_by_strategy_key_proposed_version_returns_none_when_absent(self) -> None:
        repo, _ = _repo()
        self.assertIsNone(
            repo.get_by_strategy_key_proposed_version(_STRATEGY_KEY, _PROPOSED_VERSION),
        )


class MetadataTests(unittest.TestCase):
    def test_strategy_drafts_table_metadata(self) -> None:
        table = StrategyDraftRow.__table__
        self.assertEqual((table.name, table.schema), ("strategy_drafts", "analytics"))
        self.assertEqual(
            {c.name for c in table.columns},
            {"draft_id", "strategy_key", "proposed_version", "artifact_ref",
             "artifact_hash", "source_refs", "validation_result", "created_at"},
        )
        unique = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
        self.assertEqual(
            unique,
            {"uq_strategy_drafts_strategy_key_proposed_version",
             "uq_strategy_drafts_artifact_hash"},
        )
        check_sql = {c.name: str(c.sqltext) for c in table.constraints
                     if isinstance(c, CheckConstraint)}
        self.assertEqual(
            set(check_sql),
            {"ck_strategy_drafts_strategy_key_nonblank",
             "ck_strategy_drafts_proposed_version_nonblank",
             "ck_strategy_drafts_artifact_ref_nonblank",
             "ck_strategy_drafts_artifact_hash_len64",
             "ck_strategy_drafts_source_refs_array",
             "ck_strategy_drafts_validation_result_object"},
        )
        self.assertIn("~ '^[0-9a-f]{64}$'", check_sql["ck_strategy_drafts_artifact_hash_len64"])
        self.assertIn(
            "jsonb_array_length(source_refs) > 0",
            check_sql["ck_strategy_drafts_source_refs_array"],
        )
        index = next(
            i for i in table.indexes if i.name == "ix_strategy_drafts_strategy_key_created_at"
        )
        self.assertEqual([c.name for c in index.columns], ["strategy_key", "created_at"])
        self.assertIsNone(table.c.source_refs.default)


if __name__ == "__main__":
    unittest.main()
