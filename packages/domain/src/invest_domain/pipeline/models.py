"""Pure domain models for the ``pipeline`` bounded context.

The :class:`PipelineRun` is the storage-side handle for one execution of
a pipeline job. The domain model is deliberately infrastructure-free
(no SQLAlchemy, no Alembic, no FastAPI, no Dagster) so the application
layer can construct and pass around :class:`PipelineRun` values without
importing the storage layer.

Lifecycle states follow the six-value vocabulary agreed for the
``ops.pipeline_runs`` table:

- ``queued``     - the row exists but the job has not started yet.
- ``running``    - the job is in flight.
- ``succeeded``  - the job finished without error.
- ``failed``     - the job finished with an error captured in
                   :attr:`PipelineRun.error_summary`.
- ``partial``    - the job finished with partial success.
- ``cancelled``  - the job was cancelled before completion.

The status vocabulary is enforced by a database ``CHECK`` constraint
defined in migration ``20260731_0001``; the domain mirrors the same
six values so construction-time validation rejects any unknown state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

_PIPELINE_RUN_STATUS_VALUES: tuple[str, ...] = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "partial",
    "cancelled",
)


class PipelineRunStatus(StrEnum):
    """Lifecycle states for a :class:`PipelineRun`.

    Mirrors the ``ops.pipeline_runs.status`` vocabulary. The domain
    only models the state values; the legal transitions are owned by
    the application layer.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


def _ensure_aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"PipelineRun.{field_name} must be a datetime instance, "
            f"got {type(value).__name__}"
        )
    if value.tzinfo is None:
        raise ValueError(
            f"PipelineRun.{field_name} must be timezone-aware; "
            f"naive datetimes are rejected so the storage layer can "
            f"round-trip them through DateTime(timezone=True) without "
            f"losing the UTC anchor"
        )
    return value


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """One execution of a pipeline job.

    Construction-time invariants:

    - ``job_key`` is a non-empty string.
    - ``trigger_type`` is a non-empty string.
    - ``status`` is one of the six :class:`PipelineRunStatus` values;
      passing an unknown string is a hard error.
    - ``queued`` status allows ``started_at=None``.
    - ``running`` status must have ``started_at``.
    - Terminal states (``succeeded``/``failed``/``partial``/``cancelled``)
      must have ``finished_at``.
    - Non-failed states must not carry ``error_summary``.
    - ``algorithm_version`` is optional for ingestion tasks.
    - ``created_at`` / ``updated_at`` are server-generated timestamps;
      they default to ``None`` on construction and are filled in by the
      storage layer when the row is persisted.
    """

    job_key: str
    trigger_type: str
    status: PipelineRunStatus | str = PipelineRunStatus.QUEUED
    dagster_run_id: str | None = None
    partition_key: str | None = None
    algorithm_version: str | None = None
    config_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: str | None = None
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.job_key, str) or not self.job_key.strip():
            raise ValueError("PipelineRun.job_key must be a non-empty string")
        if not isinstance(self.trigger_type, str) or not self.trigger_type.strip():
            raise ValueError("PipelineRun.trigger_type must be a non-empty string")
        status_value = self._status_string(self.status)
        if status_value not in _PIPELINE_RUN_STATUS_VALUES:
            raise ValueError(
                f"PipelineRun.status {status_value!r} is not in the allowed "
                f"vocabulary {_PIPELINE_RUN_STATUS_VALUES}"
            )
        if self.started_at is not None:
            _ensure_aware(self.started_at, field_name="started_at")
        if self.finished_at is not None:
            _ensure_aware(self.finished_at, field_name="finished_at")
            if self.started_at is not None and self.finished_at < self.started_at:
                raise ValueError(
                    f"PipelineRun.finished_at {self.finished_at.isoformat()} "
                    f"must be on or after started_at {self.started_at.isoformat()}"
                )
        if self.created_at is not None:
            _ensure_aware(self.created_at, field_name="created_at")
        if self.updated_at is not None:
            _ensure_aware(self.updated_at, field_name="updated_at")

        # Status-specific validation
        if status_value == PipelineRunStatus.QUEUED.value:
            if self.started_at is not None:
                raise ValueError("PipelineRun with status='queued' must not have started_at")
        elif status_value == PipelineRunStatus.RUNNING.value:
            if self.started_at is None:
                raise ValueError("PipelineRun with status='running' must have started_at")
        elif status_value in (
            PipelineRunStatus.SUCCEEDED.value,
            PipelineRunStatus.FAILED.value,
            PipelineRunStatus.PARTIAL.value,
            PipelineRunStatus.CANCELLED.value,
        ):
            if self.finished_at is None:
                raise ValueError(
                    f"PipelineRun with status='{status_value}' must have finished_at"
                )

        # Error summary only for failed/partial
        if (
            self.error_summary is not None
            and status_value not in (PipelineRunStatus.FAILED.value, PipelineRunStatus.PARTIAL.value)
        ):
            raise ValueError(
                "PipelineRun.error_summary is only valid when status='failed' or 'partial'"
            )

    @staticmethod
    def _status_string(value: Any) -> str:
        if isinstance(value, PipelineRunStatus):
            return value.value
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, str):
            return value
        raise TypeError(
            f"PipelineRun.status must be a PipelineRunStatus or str, "
            f"got {type(value).__name__}"
        )

    @property
    def status_value(self) -> str:
        """Return the canonical string form of :attr:`status`."""
        return self._status_string(self.status)

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` for the terminal states."""
        return self.status_value in (
            PipelineRunStatus.SUCCEEDED.value,
            PipelineRunStatus.FAILED.value,
            PipelineRunStatus.PARTIAL.value,
            PipelineRunStatus.CANCELLED.value,
        )


__all__ = [
    "PipelineRun",
    "PipelineRunStatus",
]
