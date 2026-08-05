"""Stage 4A-0 PR-04 safe YAML loader for the custom-strategy channel.

This module is the **only** place in the invest-infra stack that reads
custom-strategy YAML from disk. It deliberately relies on
:func:`yaml.safe_load` (no Python tag execution, no ``!!python/`` tags,
no ``!!python/object`` instantiation) and delegates all semantic
validation to :func:`invest_domain.candidate_pool.parse_custom_strategy_mapping`
so the domain never has to know that the input came from a file.

The loader is intentionally tiny:

* Validate the path (file exists, is a file, readable as UTF-8).
* Run :func:`yaml.safe_load` and ensure the root is a mapping.
* Pass the mapping straight to the domain mapping parser; every
  per-field rule (factor allow-list, operator allow-list, weight
  sum, top-N bounds, etc.) is enforced there.
* Hash the validated strategy so the audit block of the channel
  result can be reproduced from the loader's output without re-reading
  the file.

The slice ships **no** persistence, no :class:`Dagster` asset, no
database access and no execution semantics beyond the YAML
deserialisation. Plan §5.4 forbids arbitrary expression execution in
custom strategies, and the loader's only escape hatch is
:func:`yaml.safe_load`; :class:`yaml.YAMLError` and the
:class:`InvalidCustomStrategyError` raised by the domain parser are
the only failure modes.

Errors
------

All failures raise :class:`CustomStrategyLoaderError` (a subclass of
:class:`ValueError`) or one of its more specific subclasses. Each
message identifies the offending field or file so operators can fix
the YAML or the loader's argument without re-running the channel.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from invest_domain.candidate_pool import (
    CustomStrategy,
    parse_custom_strategy_mapping,
)


class CustomStrategyLoaderError(ValueError):
    """Base class for every custom-strategy loader failure.

    Inherits from :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still treats loader failures as
    validation-time errors. Subclasses tag the failure so callers can
    react programmatically without parsing free text.
    """


class CustomStrategyLoaderFileError(CustomStrategyLoaderError):
    """Raised when the supplied path is missing, a directory, or unreadable."""


class CustomStrategyLoaderStructureError(CustomStrategyLoaderError):
    """Raised when ``yaml.safe_load`` cannot produce a mapping root."""


@dataclass(frozen=True, slots=True)
class LoadedCustomStrategy:
    """The loader's return shape: the validated strategy and its file identity.

    The file identity (path + content hash) is the auditable
    counterpart to the strategy's :attr:`CustomStrategy.parameter_hash`
    so the caller can persist ``"loaded from {path} with
    {content_hash}"`` without re-reading the file.
    """

    strategy: CustomStrategy
    source_path: Path
    content_hash: str


def load_custom_strategy(path: Path) -> LoadedCustomStrategy:
    """Load, validate, and hash a custom-strategy YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the YAML configuration. The file must be a
        regular file readable as UTF-8.

    Returns
    -------
    LoadedCustomStrategy
        Frozen value object exposing the validated :class:`CustomStrategy`
        alongside the source ``path`` and a stable ``content_hash``
        digest of the YAML bytes.

    Raises
    ------
    CustomStrategyLoaderFileError
        ``path`` does not exist, is a directory, or cannot be read as
        UTF-8.
    CustomStrategyLoaderStructureError
        :func:`yaml.safe_load` produced something other than a mapping,
        or :class:`yaml.YAMLError` was raised.
    InvalidCustomStrategyError
        The mapping failed any of the domain validation rules (unknown
        top-level keys, unknown factor, unknown operator, weights not
        summing to 1, …). The exception comes from the domain
        unchanged so the loader's callers can react programmatically.
    """
    if not path.exists():
        raise CustomStrategyLoaderFileError(
            f"custom-strategy file not found: {path}"
        )
    if not path.is_file():
        raise CustomStrategyLoaderFileError(
            f"custom-strategy path is not a file: {path}"
        )

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise CustomStrategyLoaderFileError(
            f"custom-strategy file is not readable: {path} ({exc})"
        ) from exc

    content_hash = _compute_content_hash(raw_bytes)

    try:
        loaded = yaml.safe_load(raw_bytes.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise CustomStrategyLoaderStructureError(
            f"custom-strategy YAML is not parseable: {path} ({exc})"
        ) from exc
    except UnicodeDecodeError as exc:
        raise CustomStrategyLoaderFileError(
            f"custom-strategy file is not valid UTF-8: {path} ({exc})"
        ) from exc

    if not isinstance(loaded, Mapping):
        raise CustomStrategyLoaderStructureError(
            f"custom-strategy root must be a mapping, got "
            f"{type(loaded).__name__} in {path}"
        )

    strategy = parse_custom_strategy_mapping(loaded)

    return LoadedCustomStrategy(
        strategy=strategy,
        source_path=path,
        content_hash=content_hash,
    )


def _compute_content_hash(raw_bytes: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw_bytes).hexdigest()


__all__ = [
    "CustomStrategyLoaderError",
    "CustomStrategyLoaderFileError",
    "CustomStrategyLoaderStructureError",
    "LoadedCustomStrategy",
    "load_custom_strategy",
]
