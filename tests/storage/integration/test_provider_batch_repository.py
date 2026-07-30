"""Integration tests for :class:`SqlAlchemyProviderBatchRepository`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from invest_storage import (
    NewProviderBatch,
    SqlAlchemyProviderBatchRepository,
    StoredProviderBatch,
)
from sqlalchemy.exc import IntegrityError

_UNSET = object()


def _make_batch(
    *,
    provider_key: str = "akshare",
    dataset_key: str = "etf_daily",
    request_key: str = "req-1",
    status: str = "succeeded",
    requested_at: datetime | None | object = _UNSET,
    received_at: datetime | None | object = _UNSET,
    payload_sha256: str | None = "a" * 64,
    record_count: int | None = 10,
    request_params: dict | None | object = _UNSET,
    warnings: list | None | object = _UNSET,
    raw_payload_json: dict | None | object = _UNSET,
) -> NewProviderBatch:
    final_requested_at = (
        datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        if requested_at is _UNSET
        else requested_at
    )
    final_received_at = (
        datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
        if received_at is _UNSET
        else received_at
    )
    final_request_params = (
        {"foo": "bar"} if request_params is _UNSET else request_params
    )
    final_warnings = [] if warnings is _UNSET else warnings
    final_payload = {"rows": []} if raw_payload_json is _UNSET else raw_payload_json
    return NewProviderBatch(
        provider_key=provider_key,
        dataset_key=dataset_key,
        request_key=request_key,
        requested_at=final_requested_at,
        received_at=final_received_at,
        status=status,
        payload_sha256=payload_sha256,
        record_count=record_count,
        request_params=final_request_params,
        warnings=final_warnings,
        raw_payload_json=final_payload,
    )


def test_provider_batch_save_and_get_by_id(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    batch = _make_batch()
    stored = batch_repository.add(batch)

    assert isinstance(stored, StoredProviderBatch)
    assert isinstance(stored.id, uuid.UUID)
    assert stored.provider_key == "akshare"
    assert stored.dataset_key == "etf_daily"
    assert stored.request_key == "req-1"
    assert stored.status == "succeeded"
    assert stored.record_count == 10
    assert stored.payload_sha256 == "a" * 64
    assert stored.request_params == {"foo": "bar"}
    assert stored.raw_payload_json == {"rows": []}
    assert stored.warnings == []
    assert stored.created_at is not None
    assert stored.updated_at is not None

    fetched = batch_repository.get_by_id(stored.id)
    assert fetched is not None
    assert fetched.id == stored.id
    assert fetched.provider_key == "akshare"
    assert fetched.dataset_key == "etf_daily"
    assert fetched.request_key == "req-1"


def test_provider_batch_unique_business_key_insert_raises(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    first = _make_batch(provider_key="akshare", dataset_key="etf_daily", request_key="dup")
    inserted = batch_repository.add(first)
    assert inserted.id is not None

    duplicate = _make_batch(provider_key="akshare", dataset_key="etf_daily", request_key="dup")
    with pytest.raises(IntegrityError):
        batch_repository.add(duplicate)


def test_provider_batch_get_by_request_returns_existing(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    inserted = batch_repository.add(
        _make_batch(provider_key="akshare", dataset_key="etf_daily", request_key="abc")
    )

    fetched = batch_repository.get_by_request(
        provider_key="akshare", dataset_key="etf_daily", request_key="abc"
    )
    assert fetched is not None
    assert fetched.id == inserted.id


def test_provider_batch_get_by_request_returns_none_when_missing(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    assert (
        batch_repository.get_by_request(
            provider_key="nope", dataset_key="nope", request_key="nope"
        )
        is None
    )


def test_provider_batch_get_by_id_returns_none_when_missing(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    assert batch_repository.get_by_id(uuid.uuid4()) is None


def test_provider_batch_status_requested_requires_no_payload(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    """A ``status='requested'`` row carries no payload and no SHA-256.

    Mirrors the database CHECK constraint
    ``ck_provider_batches_requested_has_no_payload`` defined in
    migration 0003.
    """

    batch = _make_batch(
        status="requested",
        payload_sha256=None,
        record_count=None,
        raw_payload_json=None,
        received_at=None,
    )
    stored = batch_repository.add(batch)
    assert stored.status == "requested"
    assert stored.payload_sha256 is None
    assert stored.raw_payload_json is None
    assert stored.received_at is None


def test_provider_batch_list_by_provider_dataset_paginates(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    base_time = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    for index in range(7):
        batch = _make_batch(
            provider_key="akshare",
            dataset_key="etf_daily",
            request_key=f"req-{index:03d}",
            requested_at=base_time.replace(minute=index),
        )
        batch_repository.add(batch)
    for index in range(3):
        batch = _make_batch(
            provider_key="tushare",
            dataset_key="etf_daily",
            request_key=f"req-other-{index:03d}",
            requested_at=base_time.replace(minute=index),
        )
        batch_repository.add(batch)

    first = batch_repository.list_by_provider_dataset(
        provider_key="akshare", dataset_key="etf_daily", limit=3, offset=0
    )
    second = batch_repository.list_by_provider_dataset(
        provider_key="akshare", dataset_key="etf_daily", limit=3, offset=3
    )
    third = batch_repository.list_by_provider_dataset(
        provider_key="akshare", dataset_key="etf_daily", limit=3, offset=6
    )

    assert len(first) == 3
    assert len(second) == 3
    assert len(third) == 1
    assert [row.request_key for row in first] == ["req-006", "req-005", "req-004"]
    assert [row.request_key for row in second] == ["req-003", "req-002", "req-001"]
    assert [row.request_key for row in third] == ["req-000"]
    assert all(row.provider_key == "akshare" for row in (*first, *second, *third))
    assert all(row.dataset_key == "etf_daily" for row in (*first, *second, *third))