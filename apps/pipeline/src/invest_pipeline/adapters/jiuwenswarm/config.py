"""JiuwenSwarm CLI helper configuration (PR-6 Slice 2).

The Slice 2 subprocess transport invokes a *single* helper CLI invocation:

    python_executable helper_path run \
        --transport gateway \
        --task-file TASK \
        --mode MODE \
        --session-key KEY \
        --workspace WORKSPACE \
        --request-id REQUEST_ID \
        --output-dir DIR \
        --timeout TIMEOUT \
        --idle-timeout IDLE

The settings object freezes the seven explicit fields the contract
requires:

- ``helper_path`` — absolute filesystem path to the gateway helper
  entry point. Operators pin a known helper binary so the transport
  never resolves ``PATH`` or relies on a shell.
- ``workspace`` — operator-supplied workspace identifier forwarded to
  the helper verbatim.
- ``artifact_root`` — directory the transport creates per-request
  artifact subdirectories under. The transport never writes outside
  this root, regardless of request identifier content.
- ``python_executable`` — interpreter the transport uses to launch the
  helper. Defaults to ``sys.executable``; never falls back to a bare
  ``"python"`` lookup.
- ``mode`` — helper protocol mode (for example ``"evidence_only"``);
  forwarded verbatim as ``--mode``.
- ``timeout_seconds`` — wall-clock budget for a single ``subprocess.run``
  call. ``subprocess.run`` consumes this as ``timeout``.
- ``idle_timeout_seconds`` — explicit budget forwarded to the helper as
  ``--idle-timeout``; the helper may finish earlier when the model
  stops streaming. Slice 2 only enforces ``timeout_seconds`` locally.

The settings object is a plain dataclass so the transport never needs
``pydantic_settings`` to load it: the runner is constructed explicitly
by the orchestrator and Slice 2 is intentionally independent of the
rest of the pipeline configuration surface.

The module is pure data plumbing — no IO, no logging, no clock.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TIMEOUT_SECONDS = 120.0
_DEFAULT_IDLE_TIMEOUT_SECONDS = 30.0
_TIMEOUT_FLOOR = 0.0
_TIMEOUT_CEILING = 3600.0


def _validate_timeout(field_name: str, value: float) -> float:
    coerced = float(value)
    if not (_TIMEOUT_FLOOR < coerced <= _TIMEOUT_CEILING):
        raise ValueError(
            f"JiuwenSwarmCliSettings.{field_name} must be in "
            f"({_TIMEOUT_FLOOR}, {_TIMEOUT_CEILING}]; got {value!r}"
        )
    return coerced


def _validate_existing_path(field_name: str, value: Path) -> Path:
    if not isinstance(value, Path):
        raise ValueError(
            f"JiuwenSwarmCliSettings.{field_name} must be a pathlib.Path; "
            f"got {type(value).__name__}"
        )
    text = str(value)
    if not text:
        raise ValueError(f"JiuwenSwarmCliSettings.{field_name} must be non-empty")
    if not value.is_absolute():
        raise ValueError(
            f"JiuwenSwarmCliSettings.{field_name} must be an absolute path; "
            f"got {text!r}"
        )
    return value


def _validate_nonempty_str(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"JiuwenSwarmCliSettings.{field_name} must be a non-blank string"
        )
    return value.strip()


@dataclass(frozen=True, slots=True)
class JiuwenSwarmCliSettings:
    """Redacted, deterministic configuration for the subprocess CLI transport."""

    helper_path: Path
    workspace: str
    artifact_root: Path
    python_executable: str
    mode: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "helper_path", _validate_existing_path("helper_path", self.helper_path)
        )
        object.__setattr__(
            self, "artifact_root",
            _validate_existing_path("artifact_root", self.artifact_root),
        )
        object.__setattr__(
            self, "python_executable",
            _validate_nonempty_str("python_executable", self.python_executable),
        )
        object.__setattr__(
            self, "workspace", _validate_nonempty_str("workspace", self.workspace)
        )
        object.__setattr__(
            self, "mode", _validate_nonempty_str("mode", self.mode)
        )
        object.__setattr__(
            self, "timeout_seconds",
            _validate_timeout("timeout_seconds", self.timeout_seconds),
        )
        object.__setattr__(
            self, "idle_timeout_seconds",
            _validate_timeout("idle_timeout_seconds", self.idle_timeout_seconds),
        )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration."""

        return {
            "helper_path": str(self.helper_path),
            "workspace": self.workspace,
            "artifact_root": str(self.artifact_root),
            "python_executable": self.python_executable,
            "mode": self.mode,
            "timeout_seconds": str(self.timeout_seconds),
            "idle_timeout_seconds": str(self.idle_timeout_seconds),
        }


def default_python_executable() -> str:
    """Return the default interpreter the transport launches the helper with."""

    return sys.executable


__all__ = [
    "JiuwenSwarmCliSettings",
    "default_python_executable",
]
