"""Unit tests for the TDX .day offline reader spike.

The spike is exercised purely against temporary files built with
``struct`` so no fixtures are required. Coverage:

* two-record happy path and inclusive date filtering (int and
  ``datetime.date`` filters)
* canonical ``vipdoc/{market}/lday/{market}{symbol}.day`` layout for
  ``sh``, ``sz`` and ``bj`` markets
* canonical TDX market → exchange mapping (``sh -> SSE``,
  ``sz -> SZSE``, ``bj -> BJSE``) and the
  :func:`market_to_exchange` helper
* read-only symbol enumeration over the ``vipdoc/{sh,sz,bj}/lday``
  tree, with deterministic ordering and silent skipping of
  non-canonical filenames / non-regular files / missing market
  directories
* strict rejection of non-32-multiple file sizes, invalid calendar
  dates, missing files, non-regular-file paths
* strict rejection of non-finite and negative amounts, plus the
  documented ``TdxOfflineError`` hierarchy
* the trailing four reserved bytes are parsed and ignored — their
  contents never affect the returned bars
* empty files yield an empty tuple
"""

from __future__ import annotations

import struct
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from invest_pipeline.adapters.tdx_offline import (
    DATASET_KEY,
    MARKET_TO_EXCHANGE,
    PROVIDER_KEY,
    TdxDailyBar,
    TdxFileMissingError,
    TdxInvalidDateError,
    TdxInvalidMarketError,
    TdxInvalidPathError,
    TdxInvalidSizeError,
    TdxInvalidSymbolError,
    TdxInvalidValueError,
    TdxOfflineError,
    enumerate_symbols,
    market_to_exchange,
    read_day_file,
    read_symbol,
)


def _build_record(
    date_yyyymmdd: int,
    open_raw: int,
    high_raw: int,
    low_raw: int,
    close_raw: int,
    amount_f32: float,
    volume_raw: int,
    reserved: bytes = b"\x00\x00\x00\x00",
) -> bytes:
    payload = struct.pack(
        "<5IfI",
        date_yyyymmdd,
        open_raw,
        high_raw,
        low_raw,
        close_raw,
        amount_f32,
        volume_raw,
    )
    assert len(payload) == 28
    assert len(reserved) == 4
    return payload + reserved


def _write_day_file(tmp_path: Path, name: str, payload: bytes) -> Path:
    target = tmp_path / name
    target.write_bytes(payload)
    return target


def _write_symbol_file(
    tmp_path: Path,
    market: str,
    symbol: str,
    payload: bytes,
) -> Path:
    base = tmp_path / "vipdoc" / market / "lday"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{market}{symbol}.day"
    target.write_bytes(payload)
    return target


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_provider_and_dataset_keys() -> None:
    assert PROVIDER_KEY == "tdx_offline"
    assert DATASET_KEY == "stock_daily_bars"


def test_error_hierarchy() -> None:
    for cls in (
        TdxFileMissingError,
        TdxInvalidDateError,
        TdxInvalidMarketError,
        TdxInvalidPathError,
        TdxInvalidSizeError,
        TdxInvalidSymbolError,
        TdxInvalidValueError,
    ):
        assert issubclass(cls, TdxOfflineError)
        assert issubclass(cls, Exception)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_two_records_parsed(tmp_path: Path) -> None:
    record_one = _build_record(
        date_yyyymmdd=20230103,
        open_raw=1234,
        high_raw=1300,
        low_raw=1200,
        close_raw=1275,
        amount_f32=987654.5,
        volume_raw=100000,
    )
    record_two = _build_record(
        date_yyyymmdd=20230104,
        open_raw=1280,
        high_raw=1310,
        low_raw=1270,
        close_raw=1290,
        amount_f32=1234567.25,
        volume_raw=150000,
    )
    path = _write_day_file(tmp_path, "sh600000.day", record_one + record_two)

    bars = read_day_file(path)

    assert len(bars) == 2
    first, second = bars
    assert isinstance(first, TdxDailyBar)
    assert first.date == 20230103
    assert first.open == Decimal("12.34")
    assert first.high == Decimal("13.00")
    assert first.low == Decimal("12.00")
    assert first.close == Decimal("12.75")
    assert first.amount == Decimal("987654.5")
    assert first.volume == 100000
    assert second.date == 20230104
    assert second.open == Decimal("12.80")
    assert second.high == Decimal("13.10")
    assert second.low == Decimal("12.70")
    assert second.close == Decimal("12.90")
    assert second.amount == Decimal("1234567.25")
    assert second.volume == 150000


def test_reserved_bytes_are_ignored(tmp_path: Path) -> None:
    record_clean = _build_record(
        date_yyyymmdd=20230105,
        open_raw=1000,
        high_raw=1100,
        low_raw=950,
        close_raw=1050,
        amount_f32=1.0,
        volume_raw=10,
    )
    record_garbage = _build_record(
        date_yyyymmdd=20230106,
        open_raw=2000,
        high_raw=2100,
        low_raw=1950,
        close_raw=2050,
        amount_f32=2.0,
        volume_raw=20,
        reserved=b"\xff\xff\xff\xff",
    )
    path = _write_day_file(tmp_path, "sh600000.day", record_clean + record_garbage)

    bars = read_day_file(path)

    assert len(bars) == 2
    assert bars[0] == bars[0]
    assert bars[1].close == Decimal("20.50")
    assert bars[1].volume == 20
    assert bars[1].amount == Decimal("2.0")


# ---------------------------------------------------------------------------
# Date filtering
# ---------------------------------------------------------------------------


def _three_bars() -> bytes:
    return (
        _build_record(20230101, 1000, 1100, 950, 1050, 1.0, 100)
        + _build_record(20230201, 1100, 1200, 1050, 1150, 2.0, 200)
        + _build_record(20230301, 1200, 1300, 1150, 1250, 3.0, 300)
    )


def test_date_filter_int_bounds(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", _three_bars())

    bars = read_day_file(path, start_date=20230115, end_date=20230215)

    assert [b.date for b in bars] == [20230201]


def test_date_filter_date_objects(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", _three_bars())

    bars = read_day_file(
        path,
        start_date=date(2023, 1, 1),
        end_date=date(2023, 2, 1),
    )

    assert [b.date for b in bars] == [20230101, 20230201]


def test_date_filter_only_start(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", _three_bars())

    bars = read_day_file(path, start_date=20230201)

    assert [b.date for b in bars] == [20230201, 20230301]


def test_date_filter_only_end(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", _three_bars())

    bars = read_day_file(path, end_date=20230201)

    assert [b.date for b in bars] == [20230101, 20230201]


def test_date_filter_no_overlap(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", _three_bars())

    bars = read_day_file(path, start_date=20230401, end_date=20230501)

    assert bars == ()


# ---------------------------------------------------------------------------
# Symbol path resolution
# ---------------------------------------------------------------------------


def test_read_symbol_sh_path(tmp_path: Path) -> None:
    payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
    _write_symbol_file(tmp_path, "sh", "600000", payload)

    bars = read_symbol(tmp_path, "sh", "600000")

    assert len(bars) == 1
    assert bars[0].date == 20230103
    assert bars[0].close == Decimal("10.50")


def test_read_symbol_sz_path(tmp_path: Path) -> None:
    payload = (
        _build_record(20230110, 2000, 2100, 1950, 2050, 5.0, 50)
        + _build_record(20230111, 2050, 2150, 2000, 2100, 6.0, 60)
    )
    _write_symbol_file(tmp_path, "sz", "000001", payload)

    bars = read_symbol(tmp_path, "sz", "000001", start_date=20230111)

    assert [b.date for b in bars] == [20230111]


def test_read_symbol_missing_vipdoc_directory(tmp_path: Path) -> None:
    with pytest.raises(TdxFileMissingError):
        read_symbol(tmp_path, "sh", "600000")


def test_read_symbol_invalid_market(tmp_path: Path) -> None:
    with pytest.raises(TdxInvalidMarketError):
        read_symbol(tmp_path, "us", "110001")


def test_read_symbol_invalid_symbol(tmp_path: Path) -> None:
    with pytest.raises(TdxInvalidSymbolError):
        read_symbol(tmp_path, "sh", "12345")


# ---------------------------------------------------------------------------
# File-system rejections
# ---------------------------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TdxFileMissingError):
        read_day_file(tmp_path / "does_not_exist.day")


def test_path_is_directory_raises(tmp_path: Path) -> None:
    directory = tmp_path / "somedir"
    directory.mkdir()
    with pytest.raises(TdxInvalidPathError):
        read_day_file(directory)


def test_empty_file_returns_empty_tuple(tmp_path: Path) -> None:
    path = _write_day_file(tmp_path, "sh600000.day", b"")
    assert read_day_file(path) == ()


def test_invalid_size_raises(tmp_path: Path) -> None:
    payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
    payload = payload[:-1]  # truncate to 31 bytes -> not a multiple of 32
    path = _write_day_file(tmp_path, "sh600000.day", payload)
    with pytest.raises(TdxInvalidSizeError):
        read_day_file(path)


# ---------------------------------------------------------------------------
# Per-record rejections
# ---------------------------------------------------------------------------


def test_invalid_calendar_date_raises(tmp_path: Path) -> None:
    bad = _build_record(20230230, 1000, 1100, 950, 1050, 1.0, 100)
    path = _write_day_file(tmp_path, "sh600000.day", bad)
    with pytest.raises(TdxInvalidDateError):
        read_day_file(path)


def test_invalid_month_raises(tmp_path: Path) -> None:
    bad = _build_record(20231301, 1000, 1100, 950, 1050, 1.0, 100)
    path = _write_day_file(tmp_path, "sh600000.day", bad)
    with pytest.raises(TdxInvalidDateError):
        read_day_file(path)


def test_out_of_range_date_raises(tmp_path: Path) -> None:
    bad = _build_record(19690101, 1000, 1100, 950, 1050, 1.0, 100)
    path = _write_day_file(tmp_path, "sh600000.day", bad)
    with pytest.raises(TdxInvalidDateError):
        read_day_file(path)


def test_non_finite_amount_raises(tmp_path: Path) -> None:
    nan_amount = struct.pack("<f", float("nan"))[0:4]
    head = struct.pack(
        "<5I",
        20230103,
        1000,
        1100,
        950,
        1050,
    )
    payload = head + nan_amount + struct.pack("<I", 100) + b"\x00\x00\x00\x00"
    assert len(payload) == 32
    path = _write_day_file(tmp_path, "sh600000.day", payload)
    with pytest.raises(TdxInvalidValueError):
        read_day_file(path)


def test_negative_amount_raises(tmp_path: Path) -> None:
    bad = _build_record(20230103, 1000, 1100, 950, 1050, -1.0, 100)
    path = _write_day_file(tmp_path, "sh600000.day", bad)
    with pytest.raises(TdxInvalidValueError):
        read_day_file(path)


def test_inf_amount_raises(tmp_path: Path) -> None:
    bad = _build_record(20230103, 1000, 1100, 950, 1050, float("inf"), 100)
    path = _write_day_file(tmp_path, "sh600000.day", bad)
    with pytest.raises(TdxInvalidValueError):
        read_day_file(path)


def test_rejection_short_circuits_file(tmp_path: Path) -> None:
    good = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
    bad = _build_record(20230230, 1000, 1100, 950, 1050, 1.0, 100)
    path = _write_day_file(tmp_path, "sh600000.day", good + bad)
    with pytest.raises(TdxInvalidDateError):
        read_day_file(path)


# ---------------------------------------------------------------------------
# Market → exchange mapping (Phase 1A: BJ support)
# ---------------------------------------------------------------------------


def test_market_to_exchange_constant_exposes_all_three_markets() -> None:
    # The reader's ``MARKET_TO_EXCHANGE`` is the single source of
    # truth for the TDX ``sh`` / ``sz`` / ``bj`` market codes. The
    # mapping must include Beijing so the Phase 1A production
    # fallback can persist ``BJSE`` evidence on the upstream sidecar.
    assert dict(MARKET_TO_EXCHANGE) == {
        "sh": "SSE",
        "sz": "SZSE",
        "bj": "BJSE",
    }


def test_market_to_exchange_helper_resolves_each_market() -> None:
    assert market_to_exchange("sh") == "SSE"
    assert market_to_exchange("sz") == "SZSE"
    assert market_to_exchange("bj") == "BJSE"


def test_market_to_exchange_helper_rejects_unknown_market() -> None:
    with pytest.raises(TdxInvalidMarketError):
        market_to_exchange("us")


def test_market_to_exchange_constant_is_read_only() -> None:
    # ``MappingProxyType`` freezes the mapping: a future contributor
    # cannot widen the canonical set at runtime.
    with pytest.raises(TypeError):
        MARKET_TO_EXCHANGE["hk"] = "HKEX"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Beijing (``bj``) file reading
# ---------------------------------------------------------------------------


def test_read_symbol_bj_path(tmp_path: Path) -> None:
    payload = _build_record(20230105, 1500, 1600, 1450, 1550, 100.0, 1000)
    _write_symbol_file(tmp_path, "bj", "110001", payload)

    bars = read_symbol(tmp_path, "bj", "110001")

    assert len(bars) == 1
    assert bars[0].date == 20230105
    assert bars[0].open == Decimal("15.00")
    assert bars[0].high == Decimal("16.00")
    assert bars[0].low == Decimal("14.50")
    assert bars[0].close == Decimal("15.50")
    assert bars[0].amount == Decimal("100.0")
    assert bars[0].volume == 1000


def test_read_symbol_bj_path_with_date_filter(tmp_path: Path) -> None:
    payload = (
        _build_record(20230101, 1000, 1100, 950, 1050, 1.0, 100)
        + _build_record(20230201, 1100, 1200, 1050, 1150, 2.0, 200)
        + _build_record(20230301, 1200, 1300, 1150, 1250, 3.0, 300)
    )
    _write_symbol_file(tmp_path, "bj", "830799", payload)

    bars = read_symbol(tmp_path, "bj", "830799", start_date=20230201, end_date=20230201)

    assert [b.date for b in bars] == [20230201]


def test_read_day_file_for_bj_file(tmp_path: Path) -> None:
    # ``read_day_file`` is the path-agnostic primitive: the same
    # strict 32-byte record parsing applies to a Beijing ``.day``
    # file as to a Shanghai one.
    payload = _build_record(20230106, 2000, 2100, 1950, 2050, 5.5, 50)
    _write_symbol_file(tmp_path, "bj", "430047", payload)
    direct_path = tmp_path / "vipdoc" / "bj" / "lday" / "bj430047.day"

    bars = read_day_file(direct_path)

    assert len(bars) == 1
    assert bars[0].date == 20230106
    assert bars[0].close == Decimal("20.50")


# ---------------------------------------------------------------------------
# Read-only symbol enumeration
# ---------------------------------------------------------------------------


def test_enumerate_symbols_returns_discovered_pairs(tmp_path: Path) -> None:
    _write_symbol_file(tmp_path, "sh", "600000", b"")
    _write_symbol_file(tmp_path, "sz", "000001", b"")
    _write_symbol_file(tmp_path, "bj", "110001", b"")

    pairs = enumerate_symbols(tmp_path)

    assert pairs == (
        ("bj", "110001"),
        ("sh", "600000"),
        ("sz", "000001"),
    )


def test_enumerate_symbols_is_deterministic(tmp_path: Path) -> None:
    # Create the files in a deliberately non-sorted order to ensure
    # the helper does not depend on the OS-returned ``iterdir``
    # ordering.
    _write_symbol_file(tmp_path, "sz", "399999", b"")
    _write_symbol_file(tmp_path, "sh", "600000", b"")
    _write_symbol_file(tmp_path, "bj", "110001", b"")
    _write_symbol_file(tmp_path, "sh", "688001", b"")
    _write_symbol_file(tmp_path, "sz", "000001", b"")

    first = enumerate_symbols(tmp_path)
    second = enumerate_symbols(tmp_path)

    assert first == second
    assert first == (
        ("bj", "110001"),
        ("sh", "600000"),
        ("sh", "688001"),
        ("sz", "000001"),
        ("sz", "399999"),
    )


def test_enumerate_symbols_skips_invalid_filenames(tmp_path: Path) -> None:
    # Canonical ``.day`` files mixed with filesystem noise the
    # operator-managed tree is allowed to contain: minute-line
    # ``.lc1`` / ``.lc5`` artefacts, ``index.*`` manifests, the
    # ``stockinfo`` snapshot, plus a symbol that fails the
    # six-digit check.
    _write_symbol_file(tmp_path, "sh", "600000", b"")
    (tmp_path / "vipdoc" / "sh" / "lday" / "sh12345.day").write_bytes(b"")  # 5 digits
    (tmp_path / "vipdoc" / "sh" / "lday" / "sh600000A.day").write_bytes(b"")  # extra char
    (tmp_path / "vipdoc" / "sh" / "lday" / "shabcdef.day").write_bytes(b"")  # not digits
    (tmp_path / "vipdoc" / "sh" / "lday" / "sh600000.lc1").write_bytes(b"")
    (tmp_path / "vipdoc" / "sh" / "lday" / "sh600000.lc5").write_bytes(b"")
    (tmp_path / "vipdoc" / "sh" / "lday" / "index.lq4").write_bytes(b"")
    (tmp_path / "vipdoc" / "sh" / "lday" / "stockinfo").write_bytes(b"")
    (tmp_path / "vipdoc" / "sh" / "lday" / "sh600000.day.bak").write_bytes(b"")

    pairs = enumerate_symbols(tmp_path)

    assert pairs == (("sh", "600000"),)


def test_enumerate_symbols_skips_directories_in_lday(tmp_path: Path) -> None:
    _write_symbol_file(tmp_path, "sh", "600000", b"")
    # A directory whose name happens to look like a ``.day`` file
    # is not a regular file and must be skipped without raising.
    nested = tmp_path / "vipdoc" / "sh" / "lday" / "sh999999.day"
    nested.mkdir(parents=True, exist_ok=True)

    pairs = enumerate_symbols(tmp_path)

    assert pairs == (("sh", "600000"),)


def test_enumerate_symbols_handles_missing_root(tmp_path: Path) -> None:
    # The root directory does not exist: the scan returns an empty
    # tuple instead of raising, so the by-date fallback can rely on
    # a successful call to a non-existent tree.
    assert enumerate_symbols(tmp_path / "does_not_exist") == ()


def test_enumerate_symbols_handles_root_that_is_a_file(tmp_path: Path) -> None:
    # A path that exists but is not a directory is treated the same
    # as a missing directory — empty tuple, no error.
    file_path = tmp_path / "not_a_dir"
    file_path.write_bytes(b"")
    assert enumerate_symbols(file_path) == ()


def test_enumerate_symbols_handles_partial_markets(tmp_path: Path) -> None:
    # Only the Shanghai subtree is populated; Shenzhen and Beijing
    # are absent. The scan returns the ``sh`` pairs and silently
    # skips the missing market directories.
    _write_symbol_file(tmp_path, "sh", "600000", b"")
    _write_symbol_file(tmp_path, "sh", "688001", b"")

    pairs = enumerate_symbols(tmp_path)

    assert pairs == (("sh", "600000"), ("sh", "688001"))


def test_enumerate_symbols_handles_empty_root(tmp_path: Path) -> None:
    assert enumerate_symbols(tmp_path) == ()


def test_enumerate_symbols_handles_market_mismatch(tmp_path: Path) -> None:
    # A file whose name declares market ``bj`` but sits in the
    # ``sh`` lday directory must be dropped: the directory
    # determines the market, not the filename prefix.
    (tmp_path / "vipdoc" / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vipdoc" / "sh" / "lday" / "bj110001.day").write_bytes(b"")
    _write_symbol_file(tmp_path, "sh", "600000", b"")

    pairs = enumerate_symbols(tmp_path)

    assert pairs == (("sh", "600000"),)


# ---------------------------------------------------------------------------
# Backward compatibility for existing SH / SZ callers
# ---------------------------------------------------------------------------


def test_sh_sz_compatibility_unchanged(tmp_path: Path) -> None:
    # The Phase 1A reader must not break the existing Shanghai /
    # Shenzhen paths: the canonical ``vipdoc/sh/lday/sh600000.day``
    # and ``vipdoc/sz/lday/sz000001.day`` layouts still resolve and
    # parse exactly as they did in slice 1.
    sh_payload = _build_record(20230103, 1000, 1100, 950, 1050, 1.0, 100)
    sz_payload = _build_record(20230104, 2000, 2100, 1950, 2050, 2.0, 200)
    _write_symbol_file(tmp_path, "sh", "600000", sh_payload)
    _write_symbol_file(tmp_path, "sz", "000001", sz_payload)

    sh_bars = read_symbol(tmp_path, "sh", "600000")
    sz_bars = read_symbol(tmp_path, "sz", "000001")

    assert [b.close for b in sh_bars] == [Decimal("10.50")]
    assert [b.close for b in sz_bars] == [Decimal("20.50")]
    # Beijing support is additive; the existing two markets are
    # untouched by the new ``MARKET_TO_EXCHANGE`` entry.
    assert market_to_exchange("sh") == "SSE"
    assert market_to_exchange("sz") == "SZSE"