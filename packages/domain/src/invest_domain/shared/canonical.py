"""Deterministic canonical JSON and SHA-256 hashing primitives.

Used by domain value objects to compute stable content hashes (e.g. ``DailyBar.row_hash``)
and identifier hashes (e.g. ``CandidatePoolPolicy.parameter_hash``). The same logical input
must always produce the same bytes for the same hash schema version.

Design rules:

- Object keys are sorted recursively (lexicographic, Unicode codepoint order).
- Numeric ``Decimal`` values are encoded as their normalized decimal string form
  (no exponent, no trailing zeros, no leading zeros beyond the first digit).
  ``Decimal("NaN")`` and ``Decimal("Infinity")`` are rejected because they cannot
  round-trip through JSON and would break the guarantee that equal canonical
  strings imply equal domain values.
- ``UUID`` is encoded using the standard 8-4-4-4-12 lowercase hex form.
- ``date`` is encoded as ``YYYY-MM-DD``. Naive ``datetime`` is rejected; only
  timezone-aware values are accepted to keep the time axis unambiguous.
- Mapping types other than ``dict`` are normalized to ``dict`` with sorted keys.
- Sets / frozensets are rejected to avoid non-deterministic ordering.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

# Bumped whenever the canonical encoding rules change in a way that would
# produce a different hash for the same logical content. The first version is
# 1; the second version would be 2, etc. Embedded into ``DailyBar.row_hash``
# inputs so that the audit chain can identify which schema produced a hash.
CANONICAL_HASH_SCHEMA_VERSION: Final[int] = 1


class CanonicalizationError(ValueError):
    """Raised when an input cannot be safely canonicalized."""


def _decimal_to_canonical_string(value: Decimal, *, path: str) -> str:
    if not value.is_finite():
        raise CanonicalizationError(f"non-finite Decimal at {path!r}: {value!s}")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    sign, digits, exponent = normalized.as_tuple()
    sign_str = "-" if sign else ""
    digits_str = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        return f"{sign_str}{digits_str}{'0' * exponent}"
    decimal_places = -exponent
    if decimal_places >= len(digits_str):
        leading_zeros = "0" * (decimal_places - len(digits_str))
        return f"{sign_str}0.{leading_zeros}{digits_str}"
    split = len(digits_str) - decimal_places
    return f"{sign_str}{digits_str[:split]}.{digits_str[split:]}"


def _normalize(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return _decimal_to_canonical_string(value, path=path)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise CanonicalizationError(
                f"naive datetime at {path!r}; timezone-aware required for determinism"
            )
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(item, path=f"{path}.{key!r}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item, path=f"{path}[{idx}]") for idx, item in enumerate(value)]
    raise CanonicalizationError(
        f"unsupported value of type {type(value).__name__} at {path!r}"
    )


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON string for ``value``."""
    normalized = _normalize(value, path="$")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Return the lowercase hex SHA-256 digest of ``canonical_json(value)``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_hash(value: Any) -> str:
    """Embed the schema version into the hash input and return hex digest.

    Different ``CANONICAL_HASH_SCHEMA_VERSION`` values produce different
    digests for the same logical content, which is required so that
    historical ``row_hash`` values remain interpretable after the canonical
    encoding rules evolve.
    """

    payload = {"hash_schema_version": CANONICAL_HASH_SCHEMA_VERSION, "value": value}
    return hashlib.sha256(
        json.dumps(
            _normalize(payload, path="$"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
