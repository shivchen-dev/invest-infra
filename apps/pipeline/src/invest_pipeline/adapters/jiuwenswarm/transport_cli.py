"""Real subprocess CLI transport for the JiuwenSwarm gateway (PR-6 Slice 2).

The transport invokes the gateway helper through a single fixed-argv
subprocess call:

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

The contract is deliberate:

- ``shell=False`` is required so the argv list reaches the helper
  verbatim; the transport refuses to launch any process whose argv
  could be reinterpreted by a shell.
- The task file is plain prompt text, not a JSON wrapper, so the helper
  can forward it to the model without an extra decode step.
- Each request gets its own artifact directory under ``artifact_root``
  so concurrent runs cannot collide and the artifacts remain on disk
  for postmortem inspection. The transport never deletes artifacts.
- The helper writes its stdout summary as a single JSON object whose
  ``status`` field names one of ``succeeded``, ``timed_out``,
  ``needs_input``, ``failed``, or ``process_error``. The transport
  parses that summary **first**, regardless of returncode: the
  authoritative helper exits ``2`` on ``timed_out`` / ``failed`` and
  expects the caller to honor the JSON ``status`` it emitted. The
  process returncode is then re-checked only for contradictions —
  ``succeeded`` / ``needs_input`` must coincide with ``returncode == 0``;
  ``timed_out`` / ``failed`` / ``process_error`` may carry any
  returncode. ``subprocess.TimeoutExpired`` (the local watchdog)
  always raises :class:`JiuwenSwarmTransportError` with no fabricated
  session id, because the external gateway state is uncertain once
  the helper is reaped.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from invest_pipeline.adapters.jiuwenswarm.codec import (
    JiuwenSwarmAcceptance,
    JiuwenSwarmGatewayRequest,
)
from invest_pipeline.adapters.jiuwenswarm.config import JiuwenSwarmCliSettings
from invest_pipeline.adapters.jiuwenswarm.errors import (
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmTransportError,
)
from invest_pipeline.adapters.jiuwenswarm.prompt import build_prompt_text
from invest_pipeline.adapters.jiuwenswarm.transport import (
    JiuwenSwarmTransportResult,
)

logger = logging.getLogger(__name__)

_STATUS_SUCCEEDED = "succeeded"
_STATUS_TIMED_OUT = "timed_out"
_STATUS_NEEDS_INPUT = "needs_input"
_STATUS_FAILED = "failed"
_STATUS_PROCESS = "process_error"

_TASK_FILENAME = "task.txt"
_RESULT_FILENAME = "result.md"

# Outer timeout safety margin: the local subprocess timeout must be at
# least this much above the helper timeout so the helper has a chance
# to finish and emit a summary before the local process is reaped.
_OUTER_TIMEOUT_SAFETY_MARGIN_SECONDS = 30.0


def _safe_artifact_dir(artifact_root: Path, request_id: str) -> Path:
    """Return the per-request artifact directory, refusing path traversal."""

    if not request_id or not request_id.strip():
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm request.request_id must be a non-blank string"
        )
    if os.sep in request_id or (os.altsep and os.altsep in request_id):
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm request.request_id must not contain a path separator"
        )
    if request_id in (".", "..") or request_id.startswith(".."):
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm request.request_id must not traverse the artifact root"
        )
    root = artifact_root.resolve()
    target = (root / request_id).resolve()
    if root != target and root not in target.parents:
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm request.request_id resolves outside artifact_root"
        )
    return target


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically with the given encoding."""

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _format_float(value: float) -> str:
    """Format ``value`` as a stable decimal string for CLI arguments."""

    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


class JiuwenSwarmCliGatewayTransport:
    """Subprocess transport that invokes the gateway helper CLI.

    The transport is the only Slice 2 path that calls
    :func:`subprocess.run`. The constructor accepts a ``runner``
    callable so unit tests can inject a deterministic fake without
    touching the network or the filesystem beyond ``artifact_root``.
    """

    def __init__(
        self,
        *,
        settings: JiuwenSwarmCliSettings,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        session_key_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        if not isinstance(settings, JiuwenSwarmCliSettings):
            raise TypeError(
                "JiuwenSwarmCliGatewayTransport requires a JiuwenSwarmCliSettings; "
                f"got {type(settings).__name__}"
            )
        if not callable(runner):
            raise TypeError(
                "JiuwenSwarmCliGatewayTransport.runner must be callable"
            )
        if not callable(session_key_factory):
            raise TypeError(
                "JiuwenSwarmCliGatewayTransport.session_key_factory must be callable"
            )
        self._settings = settings
        self._runner = runner
        self._session_key_factory = session_key_factory

    def submit(
        self, request: JiuwenSwarmGatewayRequest
    ) -> JiuwenSwarmTransportResult:
        """Submit one gateway request and return the parsed transport result."""

        if not isinstance(request, JiuwenSwarmGatewayRequest):
            raise JiuwenSwarmTransportError(
                "JiuwenSwarmCliGatewayTransport.submit requires a "
                f"JiuwenSwarmGatewayRequest; got {type(request).__name__}"
            )

        artifact_dir = _safe_artifact_dir(
            self._settings.artifact_root, request.request_id
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)

        task_path = artifact_dir / _TASK_FILENAME
        result_path = artifact_dir / _RESULT_FILENAME

        prompt_text = build_prompt_text(request)
        _atomic_write_text(task_path, prompt_text, encoding="utf-8")

        pre_result_fingerprint = _capture_result_fingerprint(result_path)

        session_key = self._session_key_factory()
        if not isinstance(session_key, str) or not session_key.strip():
            raise JiuwenSwarmTransportError(
                "JiuwenSwarmCliGatewayTransport.session_key_factory must return "
                "a non-blank string"
            )
        session_key = session_key.strip()

        argv = self._build_argv(
            task_path=task_path,
            output_dir=artifact_dir,
            session_key=session_key,
            request_id=request.request_id,
        )

        outer_timeout = (
            self._settings.timeout_seconds + _OUTER_TIMEOUT_SAFETY_MARGIN_SECONDS
        )

        try:
            completed = self._runner(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                timeout=outer_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise JiuwenSwarmTransportError(
                "JiuwenSwarm helper subprocess exceeded the local timeout; "
                "the external gateway state is uncertain and no session id "
                "can be claimed from this attempt"
            ) from exc
        if not isinstance(completed, subprocess.CompletedProcess):
            raise JiuwenSwarmTransportError(
                "JiuwenSwarmCliGatewayTransport.runner must return a "
                "subprocess.CompletedProcess"
            )

        return self._interpret_completed_process(
            completed=completed,
            request_id=request.request_id,
            session_key=session_key,
            result_path=result_path,
            pre_result_fingerprint=pre_result_fingerprint,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_argv(
        self,
        *,
        task_path: Path,
        output_dir: Path,
        session_key: str,
        request_id: str,
    ) -> list[str]:
        return [
            self._settings.python_executable,
            str(self._settings.helper_path),
            "run",
            "--transport",
            "gateway",
            "--task-file",
            str(task_path),
            "--mode",
            self._settings.mode,
            "--session-key",
            session_key,
            "--workspace",
            self._settings.workspace,
            "--request-id",
            request_id,
            "--output-dir",
            str(output_dir),
            "--timeout",
            _format_float(self._settings.timeout_seconds),
            "--idle-timeout",
            _format_float(self._settings.idle_timeout_seconds),
        ]

    def _interpret_completed_process(
        self,
        *,
        completed: subprocess.CompletedProcess,
        request_id: str,
        session_key: str,
        result_path: Path,
        pre_result_fingerprint: tuple[bool, int, int] | None,
    ) -> JiuwenSwarmTransportResult:
        stdout = completed.stdout or ""
        stderr_text = (completed.stderr or "").strip()
        returncode = completed.returncode

        summary = _try_parse_summary(stdout, request_id=request_id)
        if summary is not None:
            status = summary["status"]
            echoed_session_id = summary["session_id"]
            if not echoed_session_id:
                raise JiuwenSwarmTransportError(
                    "JiuwenSwarm helper summary.session_id must be a non-blank string"
                )

            if status in (
                _STATUS_TIMED_OUT,
                _STATUS_FAILED,
                _STATUS_PROCESS,
                _STATUS_NEEDS_INPUT,
            ) and _is_fresh_result_artifact(
                result_path, pre_result_fingerprint
            ):
                raw_payload = _load_result_payload(result_path)
                return JiuwenSwarmTransportResult(
                    request_id=request_id,
                    session_id=echoed_session_id,
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=raw_payload,
                )

            if status == _STATUS_TIMED_OUT:
                return JiuwenSwarmTransportResult(
                    request_id=request_id,
                    session_id=echoed_session_id,
                    acceptance=JiuwenSwarmAcceptance.UNCERTAIN_TIMEOUT,
                    raw_payload=None,
                )
            if status in (_STATUS_FAILED, _STATUS_PROCESS):
                raise JiuwenSwarmTransportError(
                    "JiuwenSwarm helper reported status "
                    f"{status!r}; session_id={echoed_session_id!r}; "
                    f"returncode={returncode}"
                )
            if status in (_STATUS_SUCCEEDED, _STATUS_NEEDS_INPUT):
                if returncode != 0:
                    raise JiuwenSwarmTransportError(
                        "JiuwenSwarm helper reported status "
                        f"{status!r} with contradictory nonzero returncode "
                        f"{returncode}; stderr={stderr_text!r}"
                    )
                if status == _STATUS_SUCCEEDED:
                    raw_payload = _load_result_payload(result_path)
                    return JiuwenSwarmTransportResult(
                        request_id=request_id,
                        session_id=echoed_session_id,
                        acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                        raw_payload=raw_payload,
                    )
                return JiuwenSwarmTransportResult(
                    request_id=request_id,
                    session_id=echoed_session_id,
                    acceptance=JiuwenSwarmAcceptance.REJECTED,
                    raw_payload=None,
                )
            raise JiuwenSwarmTransportError(
                "JiuwenSwarm helper reported unknown status "
                f"{status!r}; session_id={echoed_session_id!r}; "
                f"returncode={returncode}"
            )

        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper produced no valid stdout summary; "
            f"returncode={returncode}; stderr={stderr_text!r}"
        )


def _parse_summary(stdout: str, *, request_id: str) -> dict[str, str]:
    """Parse the helper's stdout summary JSON and validate the identity pair."""

    if not stdout.strip():
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper produced an empty stdout summary"
        )
    try:
        summary_obj = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise JiuwenSwarmTransportError(
            f"JiuwenSwarm helper stdout is not valid JSON: {exc}"
        ) from exc
    if not isinstance(summary_obj, Mapping):
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper stdout summary must be a JSON object"
        )
    status = summary_obj.get("status")
    if not isinstance(status, str) or not status.strip():
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper summary.status must be a non-blank string"
        )
    session_id = summary_obj.get("session_id", "")
    if not isinstance(session_id, str):
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper summary.session_id must be a string"
        )
    echoed_request_id = summary_obj.get("request_id")
    if not isinstance(echoed_request_id, str):
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper summary.request_id must be a string"
        )
    if echoed_request_id != request_id:
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper summary.request_id "
            f"{echoed_request_id!r} does not match request.request_id "
            f"{request_id!r}"
        )
    return {
        "status": status,
        "session_id": session_id,
    }


def _try_parse_summary(
    stdout: str, *, request_id: str
) -> dict[str, str] | None:
    """Parse the helper summary if possible, else return ``None``.

    The transport always consults stdout first regardless of returncode —
    the authoritative helper exits ``2`` for ``timed_out`` / ``failed``
    while still emitting a fully-formed summary, so the dispatch is
    driven by ``status`` and the returncode is only used to detect
    contradictions or the absence of any summary.
    """

    try:
        return _parse_summary(stdout, request_id=request_id)
    except JiuwenSwarmTransportError:
        return None


def _capture_result_fingerprint(
    result_path: Path,
) -> tuple[bool, int, int] | None:
    """Snapshot ``result_path`` for the artifact-first freshness check.

    Returns ``None`` when the path does not exist. Otherwise returns a
    tuple ``(is_symlink, mtime_ns, size)`` derived from :func:`Path.lstat`
    so the fingerprint is well-defined even when the path is a symbolic
    link. The fingerprint alone is **not** evidence of a fresh write;
    callers must additionally confirm the file is a regular non-symlink
    file and that the post-invocation fingerprint differs from the
    pre-invocation one.
    """

    try:
        st = result_path.lstat()
    except (FileNotFoundError, NotADirectoryError, OSError):
        return None
    return (result_path.is_symlink(), st.st_mtime_ns, st.st_size)


def _is_fresh_result_artifact(
    result_path: Path,
    pre_fingerprint: tuple[bool, int, int] | None,
) -> bool:
    """Decide whether ``result_path`` was produced or changed by the
    current helper invocation.

    A result is considered fresh **only** when every condition holds:

    - The current path is a regular non-symlink file (``is_file()`` and
      not a symbolic link). Symlinks and other irregular paths fail
      closed so a hostile or stale link cannot smuggle in an artifact.
    - A post-invocation fingerprint can be captured (the file is
      readable).
    - Either the path was absent before the invocation, or its
      ``(mtime_ns, size)`` differ from the pre-invocation values. This
      rules out an unchanged ``result.md`` left over from a previous
      attempt overriding the helper summary.
    """

    if result_path.is_symlink():
        return False
    if not result_path.is_file():
        return False
    post = _capture_result_fingerprint(result_path)
    if post is None:
        return False
    if pre_fingerprint is None:
        return True
    return (post[1], post[2]) != (pre_fingerprint[1], pre_fingerprint[2])


def _load_result_payload(result_path: Path) -> Mapping[str, Any]:
    """Read ``result.md`` and parse the JSON object the helper produced."""

    if not result_path.is_file():
        raise JiuwenSwarmTransportError(
            "JiuwenSwarm helper reported succeeded but result.md is missing at "
            f"{str(result_path)!r}"
        )
    try:
        text = result_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JiuwenSwarmTransportError(
            f"JiuwenSwarm helper result.md is unreadable: {exc}"
        ) from exc
    if not text.strip():
        raise JiuwenSwarmMalformedResultError(
            "JiuwenSwarm helper result.md is empty"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JiuwenSwarmMalformedResultError(
            f"JiuwenSwarm helper result.md is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise JiuwenSwarmMalformedResultError(
            "JiuwenSwarm helper result.md must decode to a JSON object"
        )
    return MappingProxyType(dict(payload))


__all__ = [
    "JiuwenSwarmCliGatewayTransport",
]
