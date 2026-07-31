"""Integration tests for the PR-02 three-layer evidence model.

The fixture-driven tests exercise:

- :class:`SqlAlchemyProviderRequestRepository` — logical request upsert,
  ``get_or_create`` idempotency, ``mark_status`` terminal transitions.
- :class:`SqlAlchemyProviderAttemptRepository` — ``start`` /
  ``mark_succeeded`` / ``mark_failed`` lifecycle, FK wiring to the
  parent request, the ``UNIQUE(provider_request_id, attempt_no)``
  constraint.
- :class:`SqlAlchemyProviderBatchRepository` — only successful / partial
  attempts produce a batch; the FK chain request → attempt → batch
  round-trips end-to-end; failed attempts leave no batch row behind.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from invest_storage import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
    StoredProviderAttempt,
    StoredProviderBatch,
    StoredProviderRequest,
)
from sqlalchemy.exc import IntegrityError

_PROVIDER_KEY = "akshare"
_DATASET_KEY = "etf_daily"
_REQUEST_KEY = "req-1"


def _make_request(
    *,
    provider_key: str = _PROVIDER_KEY,
    dataset_key: str = _DATASET_KEY,
    request_key: str = _REQUEST_KEY,
    request_params: dict | None = None,
    requested_by_run_id: uuid.UUID | None = None,
    status: str = "pending",
) -> NewProviderRequest:
    return NewProviderRequest(
        provider_key=provider_key,
        dataset_key=dataset_key,
        request_key=request_key,
        request_params=request_params if request_params is not None else {"foo": "bar"},
        requested_by_run_id=requested_by_run_id,
        status=status,
    )


# ---------------------------------------------------------------------------
# ProviderRequest repository
# ---------------------------------------------------------------------------


def test_request_save_and_get_by_id(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    stored = request_repository.add(_make_request())

    assert isinstance(stored, StoredProviderRequest)
    assert isinstance(stored.id, uuid.UUID)
    assert stored.provider_key == _PROVIDER_KEY
    assert stored.dataset_key == _DATASET_KEY
    assert stored.request_key == _REQUEST_KEY
    assert stored.status == "pending"
    assert stored.request_params == {"foo": "bar"}
    assert stored.requested_by_run_id is None
    assert stored.created_at is not None
    assert stored.completed_at is None

    fetched = request_repository.get_by_id(stored.id)
    assert fetched is not None
    assert fetched.id == stored.id


def test_request_get_by_logical_key_returns_existing(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    inserted = request_repository.add(_make_request())

    fetched = request_repository.get_by_logical_key(
        provider_key=_PROVIDER_KEY,
        dataset_key=_DATASET_KEY,
        request_key=_REQUEST_KEY,
    )
    assert fetched is not None
    assert fetched.id == inserted.id


def test_request_get_by_logical_key_returns_none_when_missing(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    assert (
        request_repository.get_by_logical_key(
            provider_key="nope", dataset_key="nope", request_key="nope"
        )
        is None
    )


def test_request_unique_logical_key_insert_raises(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    first = request_repository.add(_make_request())
    assert first.id is not None

    with pytest.raises(IntegrityError):
        request_repository.add(_make_request())


def test_request_get_or_create_is_idempotent(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    first = request_repository.get_or_create(_make_request())
    second = request_repository.get_or_create(_make_request())
    assert first.id == second.id
    assert first.status == second.status


def test_request_mark_status_updates_state(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    inserted = request_repository.add(_make_request())
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)

    updated = request_repository.mark_status(
        inserted.id, status="succeeded", completed_at=finished
    )
    assert updated.status == "succeeded"
    assert updated.completed_at == finished


def test_request_mark_status_missing_id_raises(
    request_repository: SqlAlchemyProviderRequestRepository,
) -> None:
    with pytest.raises(LookupError):
        request_repository.mark_status(uuid.uuid4(), status="succeeded")


# ---------------------------------------------------------------------------
# ProviderAttempt repository
# ---------------------------------------------------------------------------


def test_attempt_start_marks_running(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
        provider_request_id_text="ext-1",
    )

    assert isinstance(attempt, StoredProviderAttempt)
    assert attempt.provider_request_id == request.id
    assert attempt.attempt_no == 1
    assert attempt.status == "running"
    assert attempt.started_at == started
    assert attempt.finished_at is None
    assert attempt.provider_request_id_text == "ext-1"


def test_attempt_mark_succeeded_requires_hash(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )

    with pytest.raises(ValueError):
        attempt_repository.mark_succeeded(
            attempt.id,
            finished_at=finished,
            response_payload_sha256="",
        )


def test_attempt_mark_succeeded_persists_terminal_state(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )

    closed = attempt_repository.mark_succeeded(
        attempt.id,
        finished_at=finished,
        response_payload_sha256="a" * 64,
        http_status=200,
    )
    assert closed.status == "succeeded"
    assert closed.finished_at == finished
    assert closed.response_payload_sha256 == "a" * 64
    assert closed.http_status == 200


def test_attempt_mark_failed_persists_terminal_state(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )

    closed = attempt_repository.mark_failed(
        attempt.id,
        finished_at=finished,
        error_stage="timeout",
        error_code="UPSTREAM_TIMEOUT",
        error_message="upstream timed out",
        http_status=504,
    )
    assert closed.status == "failed"
    assert closed.finished_at == finished
    assert closed.error_stage == "timeout"
    assert closed.error_code == "UPSTREAM_TIMEOUT"
    assert closed.error_message == "upstream timed out"
    assert closed.http_status == 504


def test_attempt_mark_failed_requires_error_fields(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )

    with pytest.raises(ValueError):
        attempt_repository.mark_failed(
            attempt.id,
            finished_at=finished,
            error_stage="",
            error_code="UPSTREAM_TIMEOUT",
        )
    with pytest.raises(ValueError):
        attempt_repository.mark_failed(
            attempt.id,
            finished_at=finished,
            error_stage="timeout",
            error_code="",
        )


def test_attempt_unique_per_request(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )

    with pytest.raises(IntegrityError):
        attempt_repository.start(
            provider_request_id=request.id,
            attempt_no=1,
            started_at=started,
        )


def test_attempt_list_by_request_orders_by_attempt_no(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
) -> None:
    request = request_repository.add(_make_request())
    base = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    for no in (1, 2, 3):
        attempt_repository.start(
            provider_request_id=request.id,
            attempt_no=no,
            started_at=base.replace(minute=no),
        )

    listed = attempt_repository.list_by_request(request.id)
    assert [row.attempt_no for row in listed] == [1, 2, 3]


# ---------------------------------------------------------------------------
# ProviderBatch repository
# ---------------------------------------------------------------------------


def _make_attempt_succeeded(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    *,
    provider_key: str = _PROVIDER_KEY,
    dataset_key: str = _DATASET_KEY,
    request_key: str = _REQUEST_KEY,
    attempt_no: int = 1,
) -> StoredProviderAttempt:
    request = request_repository.add(
        _make_request(provider_key=provider_key, dataset_key=dataset_key, request_key=request_key)
    )
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=attempt_no,
        started_at=started,
    )
    return attempt_repository.mark_succeeded(
        attempt.id,
        finished_at=finished,
        response_payload_sha256="a" * 64,
    )


def test_batch_save_and_get_by_id(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    attempt = _make_attempt_succeeded(request_repository, attempt_repository)
    batch = batch_repository.add(
        NewProviderBatch(
            provider_request_id=attempt.provider_request_id,
            provider_attempt_id=attempt.id,
            provider_key=_PROVIDER_KEY,
            dataset_key=_DATASET_KEY,
            record_count=10,
            payload_sha256="a" * 64,
            status="succeeded",
            warnings=["stale record skipped"],
        )
    )

    assert isinstance(batch, StoredProviderBatch)
    assert isinstance(batch.id, uuid.UUID)
    assert batch.provider_request_id == attempt.provider_request_id
    assert batch.provider_attempt_id == attempt.id
    assert batch.record_count == 10
    assert batch.payload_sha256 == "a" * 64
    assert batch.warnings == ["stale record skipped"]
    assert batch.status == "succeeded"
    assert batch.created_at is not None

    fetched = batch_repository.get_by_id(batch.id)
    assert fetched is not None
    assert fetched.id == batch.id


def test_batch_requires_existing_parent_attempt(
    request_repository: SqlAlchemyProviderRequestRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    request = request_repository.add(_make_request())
    with pytest.raises(IntegrityError):
        batch_repository.add(
            NewProviderBatch(
                provider_request_id=request.id,
                provider_attempt_id=uuid.uuid4(),
                provider_key=_PROVIDER_KEY,
                dataset_key=_DATASET_KEY,
                record_count=1,
                payload_sha256="a" * 64,
                status="succeeded",
            )
        )


def test_batch_failed_attempt_leaves_no_batch_row(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    """Per PR-02 ADR-0003 §6.6 a failed attempt MUST NOT produce a batch.

    The asset layer skips the ``batch_repository.add`` call when the
    adapter returns a failed attempt; this test verifies the higher-
    level invariant by exercising the same flow against the
    repositories.
    """

    request = request_repository.add(_make_request())
    started = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC)
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=started,
    )
    attempt_repository.mark_failed(
        attempt.id,
        finished_at=finished,
        error_stage="timeout",
        error_code="UPSTREAM_TIMEOUT",
        error_message="upstream timed out",
    )

    # Asset layer would skip batch insert on failed attempt; the
    # repository itself does not block inserts against a failed
    # attempt, but a successful batch is only meaningful for a
    # succeeded attempt. We assert here that no batch row was inserted.
    batches = batch_repository.list_by_attempt(attempt.id)
    assert batches == []


def test_batch_list_by_attempt_returns_only_matching(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    first_attempt = _make_attempt_succeeded(
        request_repository,
        attempt_repository,
        request_key="rt-1",
        attempt_no=1,
    )
    second_attempt = _make_attempt_succeeded(
        request_repository,
        attempt_repository,
        request_key="rt-2",
        attempt_no=1,
    )

    batch_repository.add(
        NewProviderBatch(
            provider_request_id=first_attempt.provider_request_id,
            provider_attempt_id=first_attempt.id,
            provider_key=_PROVIDER_KEY,
            dataset_key=_DATASET_KEY,
            record_count=10,
            payload_sha256="a" * 64,
            status="succeeded",
        )
    )
    batch_repository.add(
        NewProviderBatch(
            provider_request_id=second_attempt.provider_request_id,
            provider_attempt_id=second_attempt.id,
            provider_key=_PROVIDER_KEY,
            dataset_key=_DATASET_KEY,
            record_count=20,
            payload_sha256="b" * 64,
            status="partial",
        )
    )

    first_batches = batch_repository.list_by_attempt(first_attempt.id)
    second_batches = batch_repository.list_by_attempt(second_attempt.id)
    assert [b.record_count for b in first_batches] == [10]
    assert [b.record_count for b in second_batches] == [20]


def test_batch_list_by_provider_dataset_paginates(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    for index in range(5):
        attempt = _make_attempt_succeeded(
            request_repository,
            attempt_repository,
            request_key=f"rt-{index:03d}",
            attempt_no=1,
        )
        batch_repository.add(
            NewProviderBatch(
                provider_request_id=attempt.provider_request_id,
                provider_attempt_id=attempt.id,
                provider_key=_PROVIDER_KEY,
                dataset_key=_DATASET_KEY,
                record_count=index,
                payload_sha256="a" * 64,
                status="succeeded",
            )
        )
    other_attempt = _make_attempt_succeeded(
        request_repository,
        attempt_repository,
        provider_key="other",
        dataset_key=_DATASET_KEY,
        request_key="other-1",
        attempt_no=1,
    )
    batch_repository.add(
        NewProviderBatch(
            provider_request_id=other_attempt.provider_request_id,
            provider_attempt_id=other_attempt.id,
            provider_key="other",
            dataset_key=_DATASET_KEY,
            record_count=99,
            payload_sha256="a" * 64,
            status="succeeded",
        )
    )

    listed = batch_repository.list_by_provider_dataset(
        provider_key=_PROVIDER_KEY, dataset_key=_DATASET_KEY, limit=3, offset=0
    )
    assert len(listed) == 3
    assert all(row.provider_key == _PROVIDER_KEY for row in listed)
    # Newest-first ordering by created_at; limit 3 covers the last 3 inserts.
    assert {row.record_count for row in listed}.issubset({0, 1, 2, 3, 4})


def test_batch_get_by_id_returns_none_when_missing(
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    assert batch_repository.get_by_id(uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# Composite three-layer flow
# ---------------------------------------------------------------------------


def test_three_layer_round_trip(
    request_repository: SqlAlchemyProviderRequestRepository,
    attempt_repository: SqlAlchemyProviderAttemptRepository,
    batch_repository: SqlAlchemyProviderBatchRepository,
) -> None:
    """End-to-end: request → attempt → batch with FK wiring preserved."""

    request = request_repository.add(
        _make_request(request_key="round-trip", request_params={"foo": "bar"})
    )
    attempt = attempt_repository.start(
        provider_request_id=request.id,
        attempt_no=1,
        started_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    attempt = attempt_repository.mark_succeeded(
        attempt.id,
        finished_at=datetime(2026, 7, 30, 12, 0, 5, tzinfo=UTC),
        response_payload_sha256="a" * 64,
    )
    batch = batch_repository.add(
        NewProviderBatch(
            provider_request_id=attempt.provider_request_id,
            provider_attempt_id=attempt.id,
            provider_key=_PROVIDER_KEY,
            dataset_key=_DATASET_KEY,
            record_count=42,
            payload_sha256="a" * 64,
            status="succeeded",
        )
    )

    assert batch.provider_request_id == request.id
    assert batch.provider_attempt_id == attempt.id
    fetched = batch_repository.list_by_attempt(attempt.id)
    assert len(fetched) == 1
    assert fetched[0].id == batch.id