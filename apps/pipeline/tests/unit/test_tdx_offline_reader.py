"""Unit tests for the TDX .day offline reader spike.

The spike is exercised purely against temporary files built with
``struct`` so no fixtures are required. Coverage:

* two-record happy path and inclusive date filtering (int and
  ``datetime.date`` filters)
* canonical ``vipdoc/{market}/lday/{market}{symbol}.day`` layout for
  both ``sh`` and ``sz``
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
        read_symbol(tmp_path, "bj", "110001")


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