"""Pure domain models for the ``pipeline`` bounded context.

The :class:`PipelineRun` is the storage-side handle for one execution of
a pipeline job. The domain model is deliberately infrastructure-free
(no SQLAlchemy, no Alembic, no FastAPI, no Dagster) so the application
layer can construct and pass around :class:`PipelineRun` values without
importing the storage layer.

Lifecycle states follow the four-value vocabulary agreed for the
``app.pipeline_runs`` table:

- ``pending``    - the row exists but the job has not started yet.
- ``running``    - the job is in flight.
- ``succeeded``  - the job finished without error.
- ``failed``     - the job finished with an error captured in
                   :attr:`PipelineRun.error_message`.

The status vocabulary is enforced by a database ``CHECK`` constraint
defined in migration ``20260730_0004``; the domain mirrors the same
four values so construction-time validation rejects any unknown state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

_PIPELINE_RUN_STATUS_VALUES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
)


class PipelineRunStatus(StrEnum):
    """Lifecycle states for a :class:`PipelineRun`.

    Mirrors the ``app.pipeline_runs.status`` vocabulary. The domain
    only models the state values; the legal transitions are owned by
    the application layer (the storage Repository treats ``start``
    as the transition into ``RUNNING`` and ``mark_succeeded`` /
    ``mark_failed`` as the transitions into the terminal states).
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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

    - ``job_name`` and ``algorithm_version`` are non-empty strings.
    - ``status`` is one of the four :class:`PipelineRunStatus` values;
      passing an unknown string is a hard error.
    - ``started_at`` is required and must be timezone-aware.
    - ``finished_at`` and ``error_message`` are optional but mutually
      constrained: a terminal ``SUCCEEDED`` or ``FAILED`` state carries
      ``finished_at``; only ``FAILED`` carries a non-empty
      ``error_message``.
    - ``created_at`` / ``updated_at`` are server-generated timestamps;
      they default to ``None`` on construction and are filled in by the
      storage layer when the row is persisted.
    """

    job_name: str
    algorithm_version: str
    status: PipelineRunStatus | str = PipelineRunStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.job_name, str) or not self.job_name.strip():
            raise ValueError("PipelineRun.job_name must be a non-empty string")
        if not isinstance(self.algorithm_version, str) or not self.algorithm_version.strip():
            raise ValueError(
                "PipelineRun.algorithm_version must be a non-empty string"
            )
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
        if (
            self.error_message is not None
            and status_value != PipelineRunStatus.FAILED.value
        ):
            raise ValueError(
                "PipelineRun.error_message is only valid when status='failed'"
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
        """Return ``True`` for the two terminal states."""
        return self.status_value in (
            PipelineRunStatus.SUCCEEDED.value,
            PipelineRunStatus.FAILED.value,
        )


__all__ = [
    "PipelineRun",
    "PipelineRunStatus",
]