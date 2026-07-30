"""Tests for the deterministic canonical-JSON / hashing primitives."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from invest_domain.shared.canonical import (
    CANONICAL_HASH_SCHEMA_VERSION,
    CanonicalizationError,
    canonical_json,
    canonical_sha256,
    content_hash,
)


class TestDecimalCanonicalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1.5", "1.5"),
            ("1500", "1500"),
            ("0.001", "0.001"),
            ("123.45", "123.45"),
            ("123.4500", "123.45"),
            ("0", "0"),
            ("0.0", "0"),
            ("-1.5", "-1.5"),
            ("100", "100"),
            ("0.1", "0.1"),
            ("123E+2", "12300"),
            ("1.23E+10", "12300000000"),
            ("1.23E-5", "0.0000123"),
        ],
    )
    def test_decimal_is_normalized(self, raw: str, expected: str) -> None:
        from invest_domain.shared.canonical import _decimal_to_canonical_string

        assert _decimal_to_canonical_string(Decimal(raw), path="$") == expected

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
    def test_non_finite_decimal_is_rejected(self, bad: str) -> None:
        from invest_domain.shared.canonical import _decimal_to_canonical_string

        with pytest.raises(CanonicalizationError):
            _decimal_to_canonical_string(Decimal(bad), path="$")


class TestCanonicalJson:
    def test_keys_are_sorted(self) -> None:
        result = canonical_json({"z": 1, "a": 2, "m": 3})
        assert result == '{"a":2,"m":3,"z":1}'

    def test_nested_dict_keys_are_sorted(self) -> None:
        result = canonical_json({"outer": {"z": 1, "a": 2}, "list": [{"y": 1, "x": 2}]})
        assert result == '{"list":[{"x":2,"y":1}],"outer":{"a":2,"z":1}}'

    def test_tuple_becomes_list(self) -> None:
        assert canonical_json((1, 2, 3)) == "[1,2,3]"

    def test_set_is_rejected(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonical_json({1, 2, 3})

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonical_json(datetime(2026, 7, 30, 15, 0, 0))

    def test_aware_datetime_is_iso(self) -> None:
        assert (
            canonical_json(datetime(2026, 7, 30, 15, 0, 0, tzinfo=timezone.utc))
            == '"2026-07-30T15:00:00+00:00"'
        )

    def test_date_is_iso(self) -> None:
        assert canonical_json(date(2026, 7, 30)) == '"2026-07-30"'

    def test_uuid_is_canonical(self) -> None:
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert canonical_json(u) == '"12345678-1234-5678-1234-567812345678"'

    def test_decimal_uses_string_form(self) -> None:
        assert canonical_json(Decimal("1.50")) == '"1.5"'

    def test_bool_is_not_treated_as_int(self) -> None:
        # json would render True/False as true/false; the value must round-trip
        # to a Python bool, not collapse to an int.
        result = canonical_json({"ok": True, "ko": False})
        assert result == '{"ko":false,"ok":true}'
        assert json.loads(result) == {"ok": True, "ko": False}

    def test_unknown_type_is_rejected(self) -> None:
        class NotSupported:
            pass

        with pytest.raises(CanonicalizationError):
            canonical_json(NotSupported())


class TestHashDeterminism:
    def test_same_payload_same_hash(self) -> None:
        a = canonical_sha256({"b": 1, "a": 2})
        b = canonical_sha256({"a": 2, "b": 1})
        assert a == b

    def test_different_payload_different_hash(self) -> None:
        a = canonical_sha256({"x": 1})
        b = canonical_sha256({"x": 2})
        assert a != b

    def test_hash_length_is_64_hex(self) -> None:
        h = canonical_sha256({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_content_hash_embeds_schema_version(self) -> None:
        h = content_hash("anything")
        assert len(h) == 64
        # content_hash should differ from canonical_sha256 of the same payload
        # because it embeds the schema version into the input.
        bare = canonical_sha256("anything")
        assert h != bare

    def test_schema_version_constant_is_exposed(self) -> None:
        assert CANONICAL_HASH_SCHEMA_VERSION == 1
