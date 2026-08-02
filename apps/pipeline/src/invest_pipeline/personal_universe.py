"""PersonalUniverse value object and YAML loader (PR-2A thin slice).

This module loads the personal ETF universe from
``config/personal-universe.yaml`` and exposes it as a frozen value
object. The increment is intentionally narrow: it loads, validates, and
hashes the configuration. It does **not** resolve the universe against
``core.instruments``, schedule runs, drive Dagster assets, or mutate any
database state. Those concerns belong to PR-2B and later increments.

Validation contract
-------------------

* ``version`` is a positive integer (``>= 1``). Booleans are rejected
  because :class:`bool` is a subclass of :class:`int` in Python and
  would otherwise be accepted silently.
* ``groups`` is a mapping of ``group_name -> list[symbol]``. The group
  name must be a non-empty string; the symbol list is preserved as
  written, with validation deferred to per-symbol checks.
* ``enabled_groups`` is a non-empty list of group names that must all
  exist in ``groups``.
* Each symbol must be a string of exactly six ASCII digits. Symbols
  with the wrong length, non-string entries, or non-digit characters
  cause a :class:`PersonalUniverseSymbolError` listing **every**
  offending entry together with its group — the loader never silently
  drops invalid symbols.
* Duplicates are deduplicated in declaration order but do not raise:
  the loader treats duplicate valid symbols as the user saying the same
  symbol appears in multiple groups.

Output contract
---------------

The returned :class:`PersonalUniverse` is a frozen dataclass with three
fields:

* ``version`` - the validated schema version.
* ``symbols`` - a deterministically sorted, deduplicated tuple of the
  union of all enabled-group symbols.
* ``content_hash`` - a stable SHA-256 hex digest over the canonical
  normalized content (see below).

Canonical content hash
----------------------

The hash is computed over a canonical JSON document that captures the
file's semantic content. Group entries and ``enabled_groups`` are
sorted, and per-group symbol lists are sorted and deduplicated. The
hash never includes the current time, environment, or file path, so a
file with the same logical content always hashes to the same digest
even if the YAML author reorders groups or changes quoting.

Errors
------

All failures raise :class:`PersonalUniverseError` (a subclass of
:class:`ValueError`) or one of its more specific subclasses. Each
message identifies the offending field, group, or symbol so operators
can fix the YAML without re-running the loader.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

_SYMBOL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{6}$")


class PersonalUniverseError(ValueError):
    """Base class for every PersonalUniverse configuration failure.

    Subclasses below tag the failure (version, group, symbol) so callers
    can react programmatically without parsing free text. The base
    class is itself a :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still works.
    """


class PersonalUniverseVersionError(PersonalUniverseError):
    """``version`` is missing or not a positive integer."""


class PersonalUniverseStructureError(PersonalUniverseError):
    """``groups`` or ``enabled_groups`` are missing or not a mapping/list."""


class PersonalUniverseGroupError(PersonalUniverseError):
    """``enabled_groups`` references a group that does not exist."""


class PersonalUniverseSymbolError(PersonalUniverseError):
    """One or more symbols are not six-digit strings."""


@dataclass(frozen=True, slots=True)
class PersonalUniverse:
    """A validated, frozen snapshot of ``config/personal-universe.yaml``.

    Attributes
    ----------
    version:
        The schema version declared in the YAML; a positive integer.
    symbols:
        Deterministic sorted tuple of deduplicated six-digit symbols
        collected from the enabled groups.
    content_hash:
        Stable SHA-256 hex digest over the canonical normalized content
        of the YAML. The hash never includes the file path, current
        time, or environment variables.
    """

    version: int
    symbols: tuple[str, ...]
    content_hash: str


def load_personal_universe(path: Path) -> PersonalUniverse:
    """Load, validate, and hash a personal-universe YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the YAML configuration. The file must be a
        regular file readable as UTF-8.

    Returns
    -------
    PersonalUniverse
        A frozen value object exposing ``version``, ``symbols`` (sorted
        deduplicated tuple), and ``content_hash`` (stable SHA-256 hex
        digest).

    Raises
    ------
    PersonalUniverseError
        Subclass detailed in the module docstring. The base class is a
        :class:`ValueError`.
    """
    if not path.exists():
        raise PersonalUniverseError(f"personal-universe file not found: {path}")
    if not path.is_file():
        raise PersonalUniverseError(f"personal-universe path is not a file: {path}")

    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if not isinstance(loaded, Mapping):
        raise PersonalUniverseStructureError(
            "personal-universe root must be a mapping with keys version, groups, enabled_groups"
        )

    version = _validate_version(loaded.get("version"))
    groups = _validate_groups(loaded.get("groups"))
    enabled_groups = _validate_enabled_groups(loaded.get("enabled_groups"))

    missing = sorted(set(enabled_groups) - set(groups))
    if missing:
        joined = ", ".join(missing)
        raise PersonalUniverseGroupError(f"enabled_groups references unknown group(s): {joined}")

    symbols = _collect_symbols(groups, enabled_groups)
    content_hash = _compute_content_hash(version, groups, enabled_groups)

    return PersonalUniverse(
        version=version,
        symbols=symbols,
        content_hash=content_hash,
    )


def _validate_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PersonalUniverseVersionError(
            f"version must be a positive integer, got {type(value).__name__}: {value!r}"
        )
    if value < 1:
        raise PersonalUniverseVersionError(f"version must be >= 1, got {value}")
    return value


def _validate_groups(value: object) -> dict[str, tuple[object, ...]]:
    if not isinstance(value, Mapping):
        raise PersonalUniverseStructureError(
            "groups must be a mapping from group name to list of symbols"
        )
    out: dict[str, tuple[object, ...]] = {}
    for group_name, symbols in value.items():
        if not isinstance(group_name, str) or not group_name:
            raise PersonalUniverseStructureError(
                f"group names must be non-empty strings, got {group_name!r}"
            )
        if not isinstance(symbols, list):
            raise PersonalUniverseStructureError(
                f"groups[{group_name!r}] must be a list of six-digit symbols, "
                f"got {type(symbols).__name__}"
            )
        out[group_name] = tuple(symbols)
    return out


def _validate_enabled_groups(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) == 0:
        raise PersonalUniverseStructureError(
            "enabled_groups must be a non-empty list of group names"
        )
    for name in value:
        if not isinstance(name, str) or not name:
            raise PersonalUniverseStructureError(
                f"enabled_groups entries must be non-empty strings, got {name!r}"
            )
    return tuple(value)


def _collect_symbols(
    groups: Mapping[str, tuple[object, ...]],
    enabled_groups: tuple[str, ...],
) -> tuple[str, ...]:
    seen: set[str] = set()
    invalid: list[tuple[str, str]] = []

    for group_name in enabled_groups:
        for raw_symbol in groups[group_name]:
            if not isinstance(raw_symbol, str) or not _SYMBOL_PATTERN.fullmatch(raw_symbol):
                invalid.append((repr(raw_symbol), group_name))
                continue
            if raw_symbol in seen:
                continue
            seen.add(raw_symbol)

    if invalid:
        details = ", ".join(f"{symbol_repr} (group={group})" for symbol_repr, group in invalid)
        raise PersonalUniverseSymbolError(
            f"invalid symbol(s) in groups: {details}; "
            f"each symbol must be a string of exactly six digits"
        )

    if not seen:
        raise PersonalUniverseError(
            "personal-universe has no symbols after applying enabled_groups; "
            "every enabled group is empty"
        )

    return tuple(sorted(seen))


def _compute_content_hash(
    version: int,
    groups: Mapping[str, tuple[object, ...]],
    enabled_groups: tuple[str, ...],
) -> str:
    canonical = {
        "enabled_groups": sorted(set(enabled_groups)),
        "groups": sorted(
            (
                (group_name, sorted(set(group_symbols)))
                for group_name, group_symbols in groups.items()
            ),
            key=lambda pair: pair[0],
        ),
        "version": version,
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest


__all__ = [
    "PersonalUniverse",
    "PersonalUniverseError",
    "PersonalUniverseGroupError",
    "PersonalUniverseStructureError",
    "PersonalUniverseSymbolError",
    "PersonalUniverseVersionError",
    "load_personal_universe",
]
