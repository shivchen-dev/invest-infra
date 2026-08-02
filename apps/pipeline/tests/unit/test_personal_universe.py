"""Unit tests for :mod:`invest_pipeline.personal_universe`.

The tests cover every loader branch documented in
:mod:`invest_pipeline.personal_universe`:

* Happy-path loading of the seven-symbol example from
  ``config/personal-universe.yaml``.
* Deduplication within a single group and across groups.
* Deterministic sorted output regardless of YAML declaration order.
* Stable SHA-256 content hash that survives reordering but changes
  when the semantic content changes.
* Validation failures: bad version, missing/wrong-typed top-level
  keys, unknown enabled groups, non-string or non-six-digit symbols,
  empty universe after enabling groups.
* Filesystem failures: missing file, directory in place of file,
  unparseable YAML.

The tests write YAML fixtures into ``tmp_path`` so the suite stays
hermetic and never reads the production config file directly except
for a single smoke test that confirms the checked-in fixture parses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from invest_pipeline.personal_universe import (
    PersonalUniverse,
    PersonalUniverseError,
    PersonalUniverseGroupError,
    PersonalUniverseStructureError,
    PersonalUniverseSymbolError,
    PersonalUniverseVersionError,
    load_personal_universe,
)

# Mirror the seven-symbol example shipped in
# ``config/personal-universe.yaml``. Used by the happy-path tests to
# avoid drift if the production file is updated.
SEVEN_SYMBOL_GROUPS: dict[str, tuple[str, ...]] = {
    "broad_market": ("510300", "510500", "159915"),
    "technology": ("588000", "588080"),
    "overseas": ("513050", "513100"),
}
SEVEN_ENABLED_GROUPS: tuple[str, ...] = (
    "broad_market",
    "technology",
    "overseas",
)
SEVEN_EXPECTED_SYMBOLS: tuple[str, ...] = (
    "159915",
    "510300",
    "510500",
    "513050",
    "513100",
    "588000",
    "588080",
)


def _write_yaml(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def _build_payload(
    *,
    version: int = 1,
    groups: dict[str, tuple[str, ...]] = SEVEN_SYMBOL_GROUPS,
    enabled_groups: tuple[str, ...] = SEVEN_ENABLED_GROUPS,
) -> dict[str, object]:
    return {
        "enabled_groups": list(enabled_groups),
        "groups": {name: list(symbols) for name, symbols in groups.items()},
        "version": version,
    }


def test_loads_seven_symbol_example(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "personal-universe.yaml", _build_payload())

    universe = load_personal_universe(path)

    assert isinstance(universe, PersonalUniverse)
    assert universe.version == 1
    assert universe.symbols == SEVEN_EXPECTED_SYMBOLS


def test_loaded_universe_is_frozen(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "personal-universe.yaml", _build_payload())
    universe = load_personal_universe(path)

    with pytest.raises((AttributeError, TypeError)):
        universe.symbols = ("000000",)  # type: ignore[misc]


def test_loaded_universe_is_hashable(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "personal-universe.yaml", _build_payload())
    universe = load_personal_universe(path)

    # Frozen dataclasses are hashable, so they can live inside sets
    # and dicts without copy surgery.
    assert {universe} == {universe}


def test_checked_in_yaml_fixture_parses() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    fixture = repo_root / "config" / "personal-universe.yaml"

    universe = load_personal_universe(fixture)

    assert universe.version == 1
    assert universe.symbols == SEVEN_EXPECTED_SYMBOLS
    assert len(universe.content_hash) == 64


def test_dedupes_within_single_group(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={"g": ("510300", "510300", "510500")},
        enabled_groups=("g",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    universe = load_personal_universe(path)

    assert universe.symbols == ("510300", "510500")


def test_dedupes_symbol_shared_across_groups(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={
            "a": ("510300", "510500"),
            "b": ("510300",),
        },
        enabled_groups=("a", "b"),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    universe = load_personal_universe(path)

    assert universe.symbols == ("510300", "510500")


def test_symbols_are_returned_sorted_not_in_yaml_order(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={
            "g": ("588080", "510300", "159915", "588000"),
        },
        enabled_groups=("g",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    universe = load_personal_universe(path)

    assert universe.symbols == ("159915", "510300", "588000", "588080")


def test_enabled_groups_order_does_not_affect_symbol_order(tmp_path: Path) -> None:
    payload_reversed = _build_payload(
        groups={
            "broad_market": ("510300", "510500", "159915"),
            "technology": ("588000", "588080"),
        },
        enabled_groups=("technology", "broad_market"),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload_reversed)

    universe = load_personal_universe(path)

    assert universe.symbols == (
        "159915",
        "510300",
        "510500",
        "588000",
        "588080",
    )


def test_hash_is_a_64_character_hex_sha256(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "personal-universe.yaml", _build_payload())
    universe = load_personal_universe(path)

    assert len(universe.content_hash) == 64
    assert all(char in "0123456789abcdef" for char in universe.content_hash)


def test_hash_is_stable_across_repeated_loads(tmp_path: Path) -> None:
    payload = _build_payload()
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    first = load_personal_universe(path)
    second = load_personal_universe(path)

    assert first.content_hash == second.content_hash


def test_hash_depends_only_on_canonical_content(tmp_path: Path) -> None:
    # Re-declaring groups in a different order (or sorted symbol
    # ordering inside each group) must NOT change the content hash.
    payload_a = {
        "version": 1,
        "groups": {
            "broad_market": ["510300", "510500", "159915"],
            "technology": ["588000", "588080"],
        },
        "enabled_groups": ["broad_market", "technology"],
    }
    payload_b = {
        "version": 1,
        "groups": {
            "technology": ["588080", "588000"],  # reversed symbol order
            "broad_market": ["159915", "510500", "510300"],  # reversed
        },
        "enabled_groups": ["technology", "broad_market"],  # reversed
    }
    path_a = _write_yaml(tmp_path / "a.yaml", payload_a)
    path_b = _write_yaml(tmp_path / "b.yaml", payload_b)

    universe_a = load_personal_universe(path_a)
    universe_b = load_personal_universe(path_b)

    assert universe_a.content_hash == universe_b.content_hash
    assert universe_a.symbols == universe_b.symbols


def test_hash_changes_when_version_changes(tmp_path: Path) -> None:
    baseline = load_personal_universe(_write_yaml(tmp_path / "v1.yaml", _build_payload(version=1)))
    bumped = load_personal_universe(_write_yaml(tmp_path / "v2.yaml", _build_payload(version=2)))

    assert baseline.content_hash != bumped.content_hash


def test_hash_changes_when_a_symbol_is_added(tmp_path: Path) -> None:
    baseline = load_personal_universe(_write_yaml(tmp_path / "base.yaml", _build_payload()))
    expanded = load_personal_universe(
        _write_yaml(
            tmp_path / "expanded.yaml",
            _build_payload(
                groups={
                    **SEVEN_SYMBOL_GROUPS,
                    "new_sector": ("159919",),
                },
                enabled_groups=SEVEN_ENABLED_GROUPS + ("new_sector",),
            ),
        )
    )

    assert baseline.content_hash != expanded.content_hash


def test_hash_changes_when_enabled_groups_change(tmp_path: Path) -> None:
    baseline = load_personal_universe(_write_yaml(tmp_path / "base.yaml", _build_payload()))
    shrunk = load_personal_universe(
        _write_yaml(
            tmp_path / "shrunk.yaml",
            _build_payload(enabled_groups=("broad_market",)),
        )
    )

    assert baseline.content_hash != shrunk.content_hash


def test_hash_matches_documented_algorithm(tmp_path: Path) -> None:
    # Pin a snapshot of the canonical JSON used for hashing so a
    # future refactor that tweaks the canonical form triggers this
    # test before reaching production.
    path = _write_yaml(tmp_path / "personal-universe.yaml", _build_payload())

    universe = load_personal_universe(path)

    canonical = {
        "enabled_groups": sorted(set(SEVEN_ENABLED_GROUPS)),
        "groups": sorted(
            ((name, sorted(set(symbols))) for name, symbols in SEVEN_SYMBOL_GROUPS.items()),
            key=lambda pair: pair[0],
        ),
        "version": 1,
    }
    expected = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        ).encode("utf-8")
    ).hexdigest()

    assert universe.content_hash == expected


@pytest.mark.parametrize("bad_version", [0, -1, -100])
def test_rejects_non_positive_version(tmp_path: Path, bad_version: int) -> None:
    payload = _build_payload(version=bad_version)
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseVersionError) as info:
        load_personal_universe(path)

    assert "version" in str(info.value)


def test_rejects_bool_version(tmp_path: Path) -> None:
    payload = _build_payload(version=True)  # bool is subclass of int
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseVersionError):
        load_personal_universe(path)


@pytest.mark.parametrize(
    "bad_version",
    ["1", "1.0", 1.5, None, [1], {"value": 1}],
)
def test_rejects_non_integer_version(tmp_path: Path, bad_version: object) -> None:
    payload = _build_payload(version=bad_version)  # type: ignore[arg-type]
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseVersionError):
        load_personal_universe(path)


def test_rejects_root_that_is_not_a_mapping(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path / "personal-universe.yaml", [1, 2, 3])

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_groups_that_is_not_a_mapping(tmp_path: Path) -> None:
    payload = _build_payload()
    payload["groups"] = ["510300", "510500"]  # type: ignore[assignment]
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_group_values_that_is_not_a_list(tmp_path: Path) -> None:
    payload = _build_payload()
    payload["groups"] = {"broad_market": "510300"}  # type: ignore[assignment]
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_missing_enabled_groups(tmp_path: Path) -> None:
    payload = _build_payload()
    del payload["enabled_groups"]
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_empty_enabled_groups(tmp_path: Path) -> None:
    payload = _build_payload(enabled_groups=())
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_enabled_groups_that_is_not_a_list(tmp_path: Path) -> None:
    payload = _build_payload()
    payload["enabled_groups"] = "broad_market"  # type: ignore[assignment]
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseStructureError):
        load_personal_universe(path)


def test_rejects_enabled_group_with_unknown_name(tmp_path: Path) -> None:
    payload = _build_payload(enabled_groups=("broad_market", "ghost"))
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseGroupError) as info:
        load_personal_universe(path)

    assert "ghost" in str(info.value)


def test_rejects_only_unknown_enabled_groups_with_clear_error(tmp_path: Path) -> None:
    payload = _build_payload(enabled_groups=("ghost", "phantom"))
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseGroupError) as info:
        load_personal_universe(path)

    message = str(info.value)
    assert "ghost" in message
    assert "phantom" in message


@pytest.mark.parametrize(
    "bad_symbol",
    [
        "12345",  # five digits
        "1234567",  # seven digits
        "",  # empty
        "51030A",  # letters
        "5 0300",  # whitespace
        "510300\n",  # trailing newline
        "0510300",  # seven digits (no leading-zero stripping)
    ],
)
def test_rejects_wrong_format_symbol(tmp_path: Path, bad_symbol: str) -> None:
    payload = _build_payload(
        groups={"broad_market": (bad_symbol, "510500", "159915")},
        enabled_groups=("broad_market",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseSymbolError) as info:
        load_personal_universe(path)

    message = str(info.value)
    assert "broad_market" in message
    assert repr(bad_symbol) in message


@pytest.mark.parametrize("bad_symbol", [510300, 510500.0, None, ["510300"]])
def test_rejects_non_string_symbol(tmp_path: Path, bad_symbol: object) -> None:
    payload = _build_payload(
        groups={"broad_market": [bad_symbol]},  # type: ignore[list-item]
        enabled_groups=("broad_market",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseSymbolError):
        load_personal_universe(path)


def test_error_lists_every_invalid_symbol_with_group(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={
            "broad_market": ("510300", "bad1"),
            "technology": ("588000", "even_worse"),
        },
        enabled_groups=("broad_market", "technology"),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseSymbolError) as info:
        load_personal_universe(path)

    message = str(info.value)
    assert "bad1" in message
    assert "'bad1'" in message
    assert "broad_market" in message
    assert "even_worse" in message
    assert "technology" in message


def test_invalid_symbol_in_non_enabled_group_is_ignored(tmp_path: Path) -> None:
    # A bad symbol inside a *non-enabled* group should never raise —
    # that group's contents do not enter the universe at all.
    payload = _build_payload(
        groups={
            "broad_market": ("510300", "510500", "159915"),
            "extra": ("bad",),
        },
        enabled_groups=("broad_market",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    universe = load_personal_universe(path)

    assert universe.symbols == SEVEN_EXPECTED_SYMBOLS[:3]


def test_rejects_when_all_enabled_groups_are_empty(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={"broad_market": (), "technology": ()},
        enabled_groups=("broad_market", "technology"),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseError) as info:
        load_personal_universe(path)

    assert "no symbols" in str(info.value).lower()


def test_rejects_subset_of_groups_yielding_no_symbols(tmp_path: Path) -> None:
    payload = _build_payload(
        groups={
            "broad_market": ("510300",),
            "empty": [],
        },
        enabled_groups=("empty",),
    )
    path = _write_yaml(tmp_path / "personal-universe.yaml", payload)

    with pytest.raises(PersonalUniverseError):
        load_personal_universe(path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"

    with pytest.raises(PersonalUniverseError) as info:
        load_personal_universe(missing)

    assert str(missing) in str(info.value)


def test_rejects_directory_instead_of_file(tmp_path: Path) -> None:
    directory = tmp_path / "directory.yaml"
    directory.mkdir()

    with pytest.raises(PersonalUniverseError):
        load_personal_universe(directory)


def test_rejects_invalid_yaml_syntax(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("version: 1\ngroups: [unterminated", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        load_personal_universe(path)
