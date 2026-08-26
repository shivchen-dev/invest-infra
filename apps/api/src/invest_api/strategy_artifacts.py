"""Local bounded reader for StrategyDraft logical artifact references.

Implements the ``read_bytes`` shape that
:class:`invest_api.application.strategy_drafts.StrategyArtifactReader`
expects without runtime coupling to the Protocol. Every category of
unsafe ``artifact_ref`` is collapsed to one fixed public message; the
underlying OS exception is preserved on ``__cause__`` for operators.
"""

from __future__ import annotations

from pathlib import Path

READ_ERROR: str = "strategy artifact could not be read"


class StrategyArtifactReadError(RuntimeError):
    """Bounded reader failure; ``str(exc)`` is a fixed safe message."""


class LocalStrategyArtifactReader:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=False)

    def read_bytes(self, artifact_ref: str) -> bytes:
        if not isinstance(artifact_ref, str) or not artifact_ref.strip():
            raise StrategyArtifactReadError(READ_ERROR)
        if "\\" in artifact_ref:
            raise StrategyArtifactReadError(READ_ERROR)
        ref = Path(artifact_ref)
        if ref.is_absolute():
            raise StrategyArtifactReadError(READ_ERROR)
        if any(part == ".." for part in ref.parts):
            raise StrategyArtifactReadError(READ_ERROR)
        try:
            resolved = (self._root / artifact_ref).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise StrategyArtifactReadError(READ_ERROR) from exc
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise StrategyArtifactReadError(READ_ERROR) from None
        if not resolved.is_file():
            raise StrategyArtifactReadError(READ_ERROR)
        try:
            with open(resolved, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise StrategyArtifactReadError(READ_ERROR) from exc


__all__ = [
    "LocalStrategyArtifactReader",
    "READ_ERROR",
    "StrategyArtifactReadError",
]
