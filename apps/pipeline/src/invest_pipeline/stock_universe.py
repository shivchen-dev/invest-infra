"""Stock universe value object and YAML loader (Stage 4B).

Carves out a small, explicit loader for the A-share stock symbols the
:func:`invest_pipeline.assets.stock_daily_bars_raw` asset must collect
on every partition. The slice stops short of resolving symbols against
``core.instruments`` — that alignment is left for the Stage 5 follow-up
that introduces ``stock_input_snapshot`` — and deliberately does **not**
fall back to an implicit full-market scan. The asset's symbol set is
the union of every enabled group declared in the loader's YAML, sorted
and deduplicated, exactly the way :mod:`invest_pipeline.personal_universe`
handles ETF groups.

The YAML schema mirrors the ETF personal-universe shape on purpose so
operators can copy / extend an existing file:

.. code-block:: yaml

    version: 1
    groups:
      benchmark: ["600519", "000001"]
      tech: ["600276", "002415"]
    enabled_groups:
      - benchmark
      - tech

Validation contract:

* ``version`` is a positive integer (``>= 1``); booleans rejected.
* ``groups`` is a mapping ``group_name -> list[symbol]``; group names
  must be non-empty strings, lists may be empty.
* ``enabled_groups`` is a non-empty list of group names that must all
  exist in ``groups``.
* Each symbol must be a non-empty string. The loader intentionally
  stores **naked** six-digit codes (e.g. ``600519`` / ``000001``) so
  the symbols line up byte-for-byte with ``core.instruments.symbol``,
  which the Tushare ``map_stock_basic`` mapper persists without the
  ``.SH`` / ``.SZ`` suffix. The
  :class:`invest_pipeline.adapters.tushare.StockTushareProvider`
  re-adds the exchange suffix on demand through its inherited
  ``_native_code`` helper before issuing a ``fetch_stock_daily`` call,
  so the YAML is the single source of truth for the universe.
  Symbols that are not strings raise
  :class:`StockUniverseSymbolError` with every offending entry.
* Duplicates are deduplicated in declaration order without raising.

Output contract:

The returned :class:`StockUniverse` is a frozen dataclass with two
fields:

* ``version`` - the validated schema version.
* ``symbols`` - deterministically sorted, deduplicated tuple of the
  union of all enabled-group symbols. The ordering is lexical so the
  asset's daily-bars request key is stable across reruns and operators
  can read the asset's metadata at a glance.

The loader is deliberately free of SQLAlchemy, Dagster, ``Session`` or
any I/O concerns beyond reading the YAML from disk. Wiring those
concerns in is the job of the asset layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class StockUniverseError(ValueError):
    """Base class for every StockUniverse configuration failure.

    Subclasses below tag the failure (version, group, symbol) so callers
    can react programmatically without parsing free text. The base
    class is itself a :class:`ValueError` so generic error-handling code
    that catches ``ValueError`` still works.
    """


class StockUniverseVersionError(StockUniverseError):
    """``version`` is missing or not a positive integer."""


class StockUniverseStructureError(StockUniverseError):
    """``groups`` or ``enabled_groups`` are missing or not a mapping/list."""


class StockUniverseGroupError(StockUniverseError):
    """``enabled_groups`` references a group that does not exist."""


class StockUniverseSymbolError(StockUniverseError):
    """One or more symbols are not non-empty strings."""


@dataclass(frozen=True, slots=True)
class StockUniverse:
    """A validated, frozen snapshot of the stock-universe YAML.

    Attributes
    ----------
    version:
        The schema version declared in the YAML; a positive integer.
    symbols:
        Deterministic sorted tuple of deduplicated symbols collected
        from the enabled groups. The Tushare ``stock_daily_bars``
        request key is derived from this tuple verbatim so the asset's
        contract — fixed symbols, no implicit full-market scan — is
        guaranteed at the loader boundary.
    """

    version: int
    symbols: tuple[str, ...]


def load_stock_universe(path: Path) -> StockUniverse:
    """Load and validate a stock-universe YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the YAML configuration. The file must be a
        regular file readable as UTF-8.

    Returns
    -------
    StockUniverse
        A frozen value object exposing ``version`` and ``symbols``.

    Raises
    ------
    StockUniverseError
        Subclass detailed in the module docstring. The base class is a
        :class:`ValueError`.
    """

    import yaml

    if not path.exists():
        raise StockUniverseError(f"stock-universe file not found: {path}")
    if not path.is_file():
        raise StockUniverseError(f"stock-universe path is not a file: {path}")

    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if not isinstance(loaded, Mapping):
        raise StockUniverseStructureError(
            "stock-universe root must be a mapping with keys version, groups, enabled_groups"
        )

    version = _validate_version(loaded.get("version"))
    groups = _validate_groups(loaded.get("groups"))
    enabled_groups = _validate_enabled_groups(loaded.get("enabled_groups"))

    missing = sorted(set(enabled_groups) - set(groups))
    if missing:
        joined = ", ".join(missing)
        raise StockUniverseGroupError(
            f"enabled_groups references unknown group(s): {joined}"
        )

    symbols = _collect_symbols(groups, enabled_groups)
    return StockUniverse(version=version, symbols=symbols)


def _validate_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StockUniverseVersionError(
            f"version must be a positive integer, got {type(value).__name__}: {value!r}"
        )
    if value < 1:
        raise StockUniverseVersionError(f"version must be >= 1, got {value}")
    return value


def _validate_groups(value: object) -> dict[str, tuple[object, ...]]:
    if not isinstance(value, Mapping):
        raise StockUniverseStructureError(
            "groups must be a mapping from group name to list of symbols"
        )
    out: dict[str, tuple[object, ...]] = {}
    for group_name, symbols in value.items():
        if not isinstance(group_name, str) or not group_name:
            raise StockUniverseStructureError(
                f"group names must be non-empty strings, got {group_name!r}"
            )
        if not isinstance(symbols, list):
            raise StockUniverseStructureError(
                f"groups[{group_name!r}] must be a list of symbols, "
                f"got {type(symbols).__name__}"
            )
        out[group_name] = tuple(symbols)
    return out


def _validate_enabled_groups(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) == 0:
        raise StockUniverseStructureError(
            "enabled_groups must be a non-empty list of group names"
        )
    for name in value:
        if not isinstance(name, str) or not name:
            raise StockUniverseStructureError(
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
            if not isinstance(raw_symbol, str) or not raw_symbol:
                invalid.append((repr(raw_symbol), group_name))
                continue
            if raw_symbol in seen:
                continue
            seen.add(raw_symbol)

    if invalid:
        details = ", ".join(f"{symbol_repr} (group={group})" for symbol_repr, group in invalid)
        raise StockUniverseSymbolError(
            f"invalid symbol(s) in groups: {details}; "
            f"each symbol must be a non-empty string"
        )

    if not seen:
        raise StockUniverseError(
            "stock-universe has no symbols after applying enabled_groups; "
            "every enabled group is empty"
        )

    return tuple(sorted(seen))


__all__ = [
    "StockUniverse",
    "StockUniverseError",
    "StockUniverseGroupError",
    "StockUniverseStructureError",
    "StockUniverseSymbolError",
    "StockUniverseVersionError",
    "load_stock_universe",
]