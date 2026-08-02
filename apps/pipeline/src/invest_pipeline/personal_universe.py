"""PersonalUniverse value object, YAML loader and resolver (PR-2A / PR-2B).

This module covers two narrow increments:

* PR-2A loads the personal ETF universe from
  ``config/personal-universe.yaml`` and exposes it as a frozen value
  object. It loads, validates, and hashes the configuration. It does
  **not** resolve the universe against ``core.instruments``, schedule
  runs, drive Dagster assets, or mutate any database state.
* PR-2B adds a database-free resolver
  (:func:`resolve_personal_universe`) that aligns every
  :attr:`PersonalUniverse.symbols` entry with exactly one ETF
  :class:`Instrument` from ``core.instruments`` via a caller-injected
  lookup. The resolver never touches SQLAlchemy, Dagster, ``Session``
  or any I/O; wiring those concerns in is the job of later
  increments.

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

Resolution contract (PR-2B)
---------------------------

:func:`resolve_personal_universe` takes a :class:`PersonalUniverse`
and an :data:`InstrumentLookup` callable. The callable receives a
symbol and returns zero or more candidate :class:`Instrument` objects
(normally built by a thin adapter on top of
:class:`invest_storage.SqlAlchemyInstrumentRepository`). The resolver:

* only accepts instruments with ``instrument_type == ETF`` and
  ``exchange`` in ``{SSE, SZSE}``;
* requires **exactly one** valid candidate per symbol — ambiguous
  symbols and symbols with no valid candidate are hard errors;
* preserves the order of :attr:`PersonalUniverse.symbols`, which is
  already deterministically sorted and deduplicated;
* returns a :class:`ResolvedPersonalUniverse` whose
  :attr:`~ResolvedPersonalUniverse.instruments` and
  :attr:`~ResolvedPersonalUniverse.instrument_ids` properties are
  ready to feed :func:`invest_domain.input_snapshot.InputSnapshot.create`.

The resolver itself remains free of SQLAlchemy, Dagster, ``Session``
and any I/O concerns. Wiring it to the storage layer and Dagster
assets is left to the increment that actually persists the snapshot
(PR-2C and later).

Errors
------

All failures raise :class:`PersonalUniverseError` (a subclass of
:class:`ValueError`) or one of its more specific subclasses. Each
message identifies the offending field, group, or symbol so operators
can fix the YAML or the underlying ``core.instruments`` data without
re-running the loader.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import yaml
from invest_domain.instruments.models import Instrument, InstrumentType
from invest_domain.shared.values import Exchange

_SYMBOL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{6}$")

_VALID_ETF_EXCHANGES: Final[frozenset[str]] = frozenset(
    {Exchange.SSE.value, Exchange.SZSE.value}
)

InstrumentLookup = Callable[[str], Sequence[Instrument]]
"""Callable injected into :func:`resolve_personal_universe`.

Given a personal-universe symbol, returns the candidate
:class:`Instrument` objects for that symbol — typically all rows in
``core.instruments`` carrying the symbol, regardless of exchange or
``instrument_type``. The resolver is responsible for filtering and
uniqueness; the lookup is a pure projection of the underlying
storage.

The type alias is intentionally structural: any callable matching
``Callable[[str], Sequence[Instrument]]`` qualifies, so test fakes
can stand in for the production
:class:`invest_storage.SqlAlchemyInstrumentRepository`-backed adapter
without inheriting from a base class.
"""


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


class PersonalUniverseResolutionError(PersonalUniverseError):
    """Generic failure resolving a :class:`PersonalUniverse` against instruments.

    The resolver distinguishes four concrete failure modes via the
    subclasses below; this base class exists so callers can catch the
    entire family with a single ``except`` clause without losing the
    per-mode specificity they need for logging or retry logic.
    """


class PersonalUniverseMissingSymbolError(PersonalUniverseResolutionError):
    """Symbol is absent from ``core.instruments``.

    Raised when the injected :data:`InstrumentLookup` returns no
    candidates at all for a symbol that the personal universe
    declares. The error is intentionally distinct from
    :class:`PersonalUniverseInvalidInstrumentError`: *the row is not
    in core.instruments at all* is a different remediation than *the
    row exists but the type / exchange is wrong*.
    """


class PersonalUniverseInvalidInstrumentError(PersonalUniverseResolutionError):
    """Matched candidate is not an ETF on SSE / SZSE.

    Raised when the lookup returns one or more candidates for a symbol
    but none of them satisfy the
    ``instrument_type == ETF`` and ``exchange in {SSE, SZSE}`` filter.
    The exception message lists every rejection reason so operators
    can pinpoint whether the row needs to be re-classified or its
    exchange reconciled with ADR-0004.
    """


class PersonalUniverseAmbiguousSymbolError(PersonalUniverseResolutionError):
    """Symbol matches more than one valid ETF candidate on SSE / SZSE.

    Raised when the lookup returns two or more candidates that
    individually satisfy the ETF + SSE/SZSE filter for the same
    symbol. Resolution is intentionally strict: the personal-universe
    vertical slice requires a one-to-one mapping between a configured
    symbol and a single :class:`Instrument` row, and silently picking
    one of the candidates would break audit trails.
    """


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


@dataclass(frozen=True, slots=True)
class ResolvedPersonalUniverse:
    """A :class:`PersonalUniverse` aligned with ``core.instruments``.

    The resolver produces one :class:`Instrument` per symbol declared in
    :attr:`PersonalUniverse.symbols`. Because the loader already
    deduplicates and sorts the symbol list, the ``instruments`` tuple
    is naturally unique and ordered; ``instrument_ids`` mirrors that
    ordering and is the value ``InputSnapshot.create`` expects.

    Attributes
    ----------
    instruments:
        Tuple of :class:`Instrument` objects, one per configured
        symbol, in the same order as :attr:`PersonalUniverse.symbols`.
        Each entry carries a non-``None`` :class:`InstrumentId` so the
        tuple is ready for ``InputSnapshot.create``.

    Raises
    ------
    PersonalUniverseError
        Subclasses raised during construction are limited to programmer
        errors — missing ``instrument_id`` or duplicate IDs — and never
        surface from :func:`resolve_personal_universe` under normal
        operation.
    """

    instruments: tuple[Instrument, ...]

    def __post_init__(self) -> None:
        if not self.instruments:
            raise PersonalUniverseError(
                "ResolvedPersonalUniverse must contain at least one instrument"
            )
        ids: list[UUID] = []
        for item in self.instruments:
            if item.instrument_id is None:
                raise PersonalUniverseError(
                    f"resolved instrument for symbol {item.symbol!r} on "
                    f"{item.exchange} has no instrument_id; "
                    f"core.instruments must carry a stable UUID for snapshot use"
                )
            ids.append(item.instrument_id.value)
        if len(set(ids)) != len(ids):
            raise PersonalUniverseError(
                "ResolvedPersonalUniverse.instrument_ids must not contain duplicates"
            )

    @property
    def instrument_ids(self) -> tuple[UUID, ...]:
        """Tuple of :class:`InstrumentId` UUIDs aligned with :attr:`instruments`.

        The property is the documented hand-off to
        :func:`invest_domain.input_snapshot.InputSnapshot.create`, which
        rejects duplicates and empty input. Because
        :meth:`__post_init__` guarantees both invariants, callers can
        pass ``resolved.instrument_ids`` straight through.
        """
        return tuple(item.instrument_id.value for item in self.instruments)


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


def resolve_personal_universe(
    universe: PersonalUniverse,
    lookup: InstrumentLookup,
) -> ResolvedPersonalUniverse:
    """Align a :class:`PersonalUniverse` with ``core.instruments``.

    For every symbol in :attr:`PersonalUniverse.symbols` the resolver
    calls ``lookup(symbol)`` and accepts the returned candidates only
    when ``instrument_type == ETF`` and ``exchange`` is one of
    ``{SSE, SZSE}``. Exactly one valid candidate is required; anything
    else raises a :class:`PersonalUniverseResolutionError` subclass.

    The function is deliberately free of SQLAlchemy, Dagster,
    ``Session`` and any I/O concerns. The caller supplies
    :data:`InstrumentLookup`, which is normally a thin adapter on top
    of :class:`invest_storage.SqlAlchemyInstrumentRepository` built
    per-call. The adapter contract is intentionally narrow:

    * ``lookup(symbol)`` returns ``Sequence[Instrument]`` — the
      candidates for that symbol, in any order, across exchanges.
    * An empty sequence means the symbol has no row in
      ``core.instruments`` at all.

    Parameters
    ----------
    universe:
        The validated, frozen personal-universe value object produced
        by :func:`load_personal_universe`. Its ``symbols`` tuple is
        already deduplicated and sorted, so the resolver inherits a
        stable ordering for free.
    lookup:
        Callable returning candidate :class:`Instrument` objects for a
        given symbol. The resolver never caches results between calls
        and never mutates the returned objects.

    Returns
    -------
    ResolvedPersonalUniverse
        Frozen value object whose ``instruments`` and
        ``instrument_ids`` mirror :attr:`PersonalUniverse.symbols` and
        are immediately usable by
        :func:`invest_domain.input_snapshot.InputSnapshot.create`.

    Raises
    ------
    PersonalUniverseMissingSymbolError
        ``lookup`` returned no candidates for the symbol.
    PersonalUniverseInvalidInstrumentError
        ``lookup`` returned one or more candidates, but none satisfied
        the ``ETF + SSE/SZSE`` filter. The message lists every
        rejection reason for the offending candidates.
    PersonalUniverseAmbiguousSymbolError
        ``lookup`` returned two or more candidates that **each**
        satisfied the ``ETF + SSE/SZSE`` filter. The resolver never
        silently picks one of them.
    PersonalUniverseError
        Re-raised if the resolver itself is given a malformed
        universe (empty symbols, non-string entries, …). Callers should
        never trigger this branch because :func:`load_personal_universe`
        already validates those invariants.
    """
    if not universe.symbols:
        raise PersonalUniverseError(
            "resolve_personal_universe received a PersonalUniverse with no symbols"
        )

    resolved: list[Instrument] = []
    for symbol in universe.symbols:
        candidates = lookup(symbol)
        resolved.append(_resolve_one_symbol(symbol, candidates))

    return ResolvedPersonalUniverse(instruments=tuple(resolved))


def _resolve_one_symbol(symbol: str, candidates: Sequence[Instrument]) -> Instrument:
    """Pick the unique valid ETF instrument for ``symbol``.

    Returns the resolved :class:`Instrument`. Raises one of the
    :class:`PersonalUniverseResolutionError` subclasses when zero or
    multiple valid candidates are supplied; the message always
    includes ``symbol`` and the precise reason.
    """
    if not candidates:
        raise PersonalUniverseMissingSymbolError(
            f"symbol {symbol!r} has no candidate in core.instruments; "
            f"seed the instrument before running the personal-universe snapshot"
        )

    valid: list[Instrument] = []
    rejection_reasons: list[str] = []
    for candidate in candidates:
        if candidate.instrument_type is not InstrumentType.ETF:
            rejection_reasons.append(
                f"{candidate.exchange}/{candidate.symbol} "
                f"type={candidate.instrument_type.value!s} (not ETF)"
            )
            continue
        if candidate.exchange not in _VALID_ETF_EXCHANGES:
            rejection_reasons.append(
                f"{candidate.exchange}/{candidate.symbol} exchange not in SSE/SZSE"
            )
            continue
        valid.append(candidate)

    if not valid:
        joined = "; ".join(rejection_reasons)
        raise PersonalUniverseInvalidInstrumentError(
            f"symbol {symbol!r} matched {len(candidates)} candidate(s) but none are "
            f"ETF on SSE/SZSE; reasons: {joined}"
        )

    if len(valid) > 1:
        keys = ", ".join(f"({item.exchange}, {item.symbol})" for item in valid)
        raise PersonalUniverseAmbiguousSymbolError(
            f"symbol {symbol!r} matches {len(valid)} valid ETF candidates on "
            f"SSE/SZSE: {keys}; the personal universe requires exactly one"
        )

    return valid[0]


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
    "InstrumentLookup",
    "PersonalUniverse",
    "PersonalUniverseAmbiguousSymbolError",
    "PersonalUniverseError",
    "PersonalUniverseGroupError",
    "PersonalUniverseInvalidInstrumentError",
    "PersonalUniverseMissingSymbolError",
    "PersonalUniverseResolutionError",
    "PersonalUniverseStructureError",
    "PersonalUniverseSymbolError",
    "PersonalUniverseVersionError",
    "ResolvedPersonalUniverse",
    "load_personal_universe",
    "resolve_personal_universe",
]
