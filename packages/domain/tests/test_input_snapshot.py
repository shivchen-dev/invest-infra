"""Tests for the ``input_snapshot`` bounded context."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

from invest_domain.input_snapshot import InputSnapshot
from invest_domain.input_snapshot.models import InputSnapshot as DirectInputSnapshot


_UUID_A = UUID("11111111-1111-4111-8111-111111111111")
_UUID_B = UUID("22222222-2222-4222-8222-222222222222")
_UUID_C = UUID("33333333-3333-4333-8333-333333333333")
_UUID_D = UUID("44444444-4444-4444-8444-444444444444")


_FIXED_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_FIXED_CREATED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def _fixed_id_factory() -> UUID:
    return _FIXED_ID


def _fixed_now_factory() -> datetime:
    return _FIXED_CREATED_AT


def _expected_hash(sorted_uuids: tuple[UUID, ...]) -> str:
    """Mirror of the deterministic hash rule used by ``InputSnapshot.create``."""
    return hashlib.sha256(b"".join(entry.bytes for entry in sorted_uuids)).hexdigest()


class TestInputSnapshotCreate:
    def test_create_sorts_instrument_ids_by_uuid_bytes(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_D, _UUID_B, _UUID_C, _UUID_A],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.instrument_ids == (_UUID_A, _UUID_B, _UUID_C, _UUID_D)

    def test_create_is_order_independent(self) -> None:
        forward = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A, _UUID_B, _UUID_C, _UUID_D],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        reverse = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_D, _UUID_C, _UUID_B, _UUID_A],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        middle = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_C, _UUID_A, _UUID_D, _UUID_B],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert forward.content_hash == reverse.content_hash == middle.content_hash
        assert forward.instrument_ids == reverse.instrument_ids == middle.instrument_ids

    def test_create_uses_id_and_now_factories(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _FIXED_ID
        assert snapshot.created_at == _FIXED_CREATED_AT

    def test_create_sets_row_count_equal_to_instrument_count(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A, _UUID_B, _UUID_C],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.row_count == 3
        assert snapshot.row_count == len(snapshot.instrument_ids)

    def test_create_computes_deterministic_content_hash(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_B, _UUID_A, _UUID_D, _UUID_C],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.content_hash == _expected_hash(
            (_UUID_A, _UUID_B, _UUID_C, _UUID_D)
        )

    def test_create_content_hash_length_is_64(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A, _UUID_B],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert len(snapshot.content_hash) == 64
        int(snapshot.content_hash, 16)

    def test_create_distinct_inputs_produce_distinct_hashes(self) -> None:
        first = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A, _UUID_B],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_A, _UUID_C],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        third = InputSnapshot.create(
            date(2026, 7, 31),
            [_UUID_B, _UUID_A, _UUID_C],
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash != second.content_hash
        assert first.content_hash != third.content_hash
        assert second.content_hash != third.content_hash

    def test_create_accepts_generator_input(self) -> None:
        def _gen() -> Callable[[], object]:
            def _iter() -> object:
                yield _UUID_C
                yield _UUID_A
                yield _UUID_B
            return _iter()

        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            (entry for entry in (_UUID_C, _UUID_A, _UUID_B)),
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.instrument_ids == (_UUID_A, _UUID_B, _UUID_C)
        assert snapshot.row_count == 3

    def test_create_rejects_empty_instrument_list(self) -> None:
        with pytest.raises(ValueError, match="at least one instrument_id"):
            InputSnapshot.create(
                date(2026, 7, 31),
                [],
                id_factory=_fixed_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_duplicate_instrument_ids(self) -> None:
        with pytest.raises(ValueError, match="duplicates"):
            InputSnapshot.create(
                date(2026, 7, 31),
                [_UUID_A, _UUID_B, _UUID_A],
                id_factory=_fixed_id_factory,
                now_factory=_fixed_now_factory,
            )

    def test_create_rejects_non_uuid_entry(self) -> None:
        with pytest.raises(TypeError, match="UUID instances"):
            InputSnapshot.create(
                date(2026, 7, 31),
                [_UUID_A, "not-a-uuid"],  # type: ignore[list-item]
                id_factory=_fixed_id_factory,
                now_factory=_fixed_now_factory,
            )


class TestInputSnapshotValidation:
    def _valid_kwargs(self) -> dict[str, object]:
        return {
            "id": _FIXED_ID,
            "snapshot_date": date(2026, 7, 31),
            "instrument_ids": (_UUID_A, _UUID_B),
            "content_hash": _expected_hash((_UUID_A, _UUID_B)),
            "row_count": 2,
            "created_at": _FIXED_CREATED_AT,
        }

    def test_direct_construction_accepts_valid_payload(self) -> None:
        snapshot = DirectInputSnapshot(**self._valid_kwargs())  # type: ignore[arg-type]
        assert snapshot.id == _FIXED_ID
        assert snapshot.snapshot_date == date(2026, 7, 31)
        assert snapshot.instrument_ids == (_UUID_A, _UUID_B)
        assert snapshot.row_count == 2

    def test_empty_instrument_ids_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["instrument_ids"] = ()
        kwargs["row_count"] = 0
        with pytest.raises(ValueError, match="must not be empty"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_duplicate_instrument_ids_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["instrument_ids"] = (_UUID_A, _UUID_A)
        kwargs["row_count"] = 2
        kwargs["content_hash"] = _expected_hash((_UUID_A, _UUID_A))
        with pytest.raises(ValueError, match="duplicates"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_row_count_mismatch_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["row_count"] = 3
        with pytest.raises(ValueError, match="row_count"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_negative_row_count_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["instrument_ids"] = (_UUID_A, _UUID_B, _UUID_C, _UUID_D)
        kwargs["row_count"] = -1
        with pytest.raises(ValueError, match="row_count"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_non_tuple_instrument_ids_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["instrument_ids"] = [_UUID_A, _UUID_B]  # type: ignore[assignment]
        with pytest.raises(ValueError, match="must be a tuple"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_non_uuid_entry_in_instrument_ids_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["instrument_ids"] = (_UUID_A, "not-a-uuid")  # type: ignore[arg-type]
        kwargs["row_count"] = 2
        kwargs["content_hash"] = _expected_hash((_UUID_A, _UUID_B))
        with pytest.raises(TypeError, match="UUID instances"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_content_hash_wrong_length_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["content_hash"] = "abcd"
        with pytest.raises(ValueError, match="64"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_content_hash_too_long_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["content_hash"] = "a" * 65
        with pytest.raises(ValueError, match="64"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_non_string_content_hash_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["content_hash"] = 12345  # type: ignore[assignment]
        with pytest.raises(TypeError, match="must be a str"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_naive_created_at_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["created_at"] = datetime(2026, 7, 31, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_non_uuid_id_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["id"] = "not-a-uuid"  # type: ignore[assignment]
        with pytest.raises(TypeError, match="InputSnapshot.id must be a UUID"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_non_date_snapshot_date_is_rejected(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["snapshot_date"] = "2026-07-31"  # type: ignore[assignment]
        with pytest.raises(TypeError, match="must be a date"):
            DirectInputSnapshot(**kwargs)  # type: ignore[arg-type]

    def test_factory_defaults_match_expectations(self) -> None:
        snapshot = InputSnapshot.create(date(2026, 7, 31), [_UUID_A])
        assert isinstance(snapshot.id, UUID)
        assert snapshot.created_at.tzinfo is not None
        assert snapshot.created_at.utcoffset() == timezone.utc.utcoffset(snapshot.created_at)
        assert snapshot.created_at <= datetime.now(timezone.utc)

    def test_repeat_calls_with_different_ids_produce_different_ids(self) -> None:
        first = InputSnapshot.create(date(2026, 7, 31), [_UUID_A])
        second = InputSnapshot.create(date(2026, 7, 31), [_UUID_A])
        assert first.id != second.id
        assert first.content_hash == second.content_hash

    def test_existing_uuid_is_preserved_through_create(self) -> None:
        snapshot = InputSnapshot.create(
            date(2026, 7, 31),
            [uuid4()],
            id_factory=lambda: _UUID_A,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _UUID_A


class TestInputSnapshotPublicReExport:
    def test_package_init_exposes_input_snapshot(self) -> None:
        from invest_domain.input_snapshot import InputSnapshot as Reexported

        assert Reexported is DirectInputSnapshot