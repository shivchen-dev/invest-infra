"""Focused tests for the DC-3 ``akshare.exposure_mapper`` module.

The mapper turns an :class:`AkshareResponse` for the
``index_stock_cons_weight_csindex`` operation into an
:class:`invest_domain.exposure.IndexProfile` plus a matching
:class:`invest_domain.exposure.IndexConstituentSnapshot`. These tests
pin the contract end-to-end against hermetic dict fixtures:

- happy path: exact field mapping and weight ``/100`` normalisation;
- ``industry`` stays ``None`` on every constituent;
- row order independence: profile / snapshot hashes are stable;
- operation / payload guards (wrong op, empty payload, non-dict row);
- required-field guard (missing keys, empty strings);
- cross-row consistency (mixed date / index code / index name);
- code normalisation (non-numeric, non-6-digit indices / stocks);
- weight validation (bool, non-finite, out-of-range, non-decimal);
- duplicate constituents are rejected;
- naive ``observed_at`` is rejected.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.exposure import (
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.akshare.exposure_mapper import (
    CsindexExposureMapping,
    map_csindex_constituent_weights,
)
from invest_pipeline.adapters.errors import ProviderDataContractError

_EXPECTED_OPERATION = "index_stock_cons_weight_csindex"

_OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
_OBSERVED_AT_PLUS_EIGHT = datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
_NAIVE_OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0)

_FIXED_SNAPSHOT_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
_FIXED_CREATED_AT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def _id_factory() -> UUID:
    return _FIXED_SNAPSHOT_ID


def _now_factory() -> datetime:
    return _FIXED_CREATED_AT


def _make_response(
    payload: Any,
    *,
    operation: str = _EXPECTED_OPERATION,
    raw_payload_hash: str | None = None,
) -> AkshareResponse:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return AkshareResponse(
        operation=operation,
        raw_payload=payload,
        raw_payload_hash=raw_payload_hash or hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _standard_payload() -> list[dict[str, Any]]:
    return [
        {
            "日期": "20260731",
            "指数代码": "000300",
            "指数名称": "沪深300",
            "成分券代码": "600519",
            "权重": "12.5",
        },
        {
            "日期": "20260731",
            "指数代码": "000300",
            "指数名称": "沪深300",
            "成分券代码": "601318",
            "权重": "5.0",
        },
        {
            "日期": "20260731",
            "指数代码": "000300",
            "指数名称": "沪深300",
            "成分券代码": "000858",
            "权重": "3.0",
        },
        {
            "日期": "20260731",
            "指数代码": "000300",
            "指数名称": "沪深300",
            "成分券代码": "300750",
            "权重": "2.0",
        },
    ]


def _map(
    payload: list[dict[str, Any]] | None = None,
    *,
    operation: str = _EXPECTED_OPERATION,
    observed_at: datetime = _OBSERVED_AT,
) -> CsindexExposureMapping:
    response = _make_response(
        payload if payload is not None else _standard_payload(),
        operation=operation,
    )
    return map_csindex_constituent_weights(
        response,
        observed_at=observed_at,
        id_factory=_id_factory,
        now_factory=_now_factory,
    )


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


class HappyPathTest(unittest.TestCase):
    """Exact field mapping and weight /100 normalisation."""

    def test_returns_result_with_profile_and_snapshot(self) -> None:
        result = _map()
        self.assertIsInstance(result, CsindexExposureMapping)
        self.assertIsInstance(result.profile, IndexProfile)
        self.assertIsInstance(result.constituent_snapshot, IndexConstituentSnapshot)

    def test_profile_carries_index_identity(self) -> None:
        result = _map()
        self.assertEqual(result.profile.index_code, "000300")
        self.assertEqual(result.profile.index_name, "沪深300")

    def test_profile_category_is_none_and_as_of_matches_source(
        self,
    ) -> None:
        result = _map()
        self.assertIsNone(result.profile.category)
        self.assertEqual(result.profile.as_of_date.year, 2026)
        self.assertEqual(result.profile.as_of_date.month, 7)
        self.assertEqual(result.profile.as_of_date.day, 31)

    def test_weight_is_divided_by_100_into_ratio(self) -> None:
        result = _map()
        by_code = {c.stock_code: c.weight for c in result.constituent_snapshot.constituents}
        self.assertEqual(by_code["600519"], Decimal("0.125"))
        self.assertEqual(by_code["601318"], Decimal("0.05"))
        self.assertEqual(by_code["000858"], Decimal("0.03"))
        self.assertEqual(by_code["300750"], Decimal("0.02"))

    def test_industry_is_none_on_every_constituent(self) -> None:
        result = _map()
        for constituent in result.constituent_snapshot.constituents:
            self.assertIsNone(constituent.industry)

    def test_index_code_date_iso_form_is_accepted(self) -> None:
        payload = [
            {
                "日期": "2026-07-31",
                "指数代码": "000300",
                "指数名称": "沪深300",
                "成分券代码": "600519",
                "权重": "12.5",
            },
            {
                "日期": "2026-07-31",
                "指数代码": "000300",
                "指数名称": "沪深300",
                "成分券代码": "601318",
                "权重": "5.0",
            },
        ]
        result = _map(payload)
        self.assertEqual(
            result.constituent_snapshot.as_of_date.year * 10000
            + result.constituent_snapshot.as_of_date.month * 100
            + result.constituent_snapshot.as_of_date.day,
            20260731,
        )

    def test_snapshot_uses_injected_id_and_now(self) -> None:
        result = _map()
        self.assertEqual(result.constituent_snapshot.id, _FIXED_SNAPSHOT_ID)
        self.assertEqual(result.constituent_snapshot.created_at, _FIXED_CREATED_AT)

    def test_profile_and_snapshot_share_provenance(self) -> None:
        result = _map()
        self.assertIs(result.profile.provenance, result.constituent_snapshot.provenance)
        self.assertEqual(result.profile.provenance.provider_key, "akshare")
        self.assertEqual(
            result.profile.provenance.dataset_key,
            "index_stock_cons_weight_csindex",
        )
        self.assertEqual(result.profile.provenance.observed_at, _OBSERVED_AT)
        self.assertEqual(result.profile.provenance.revision, 1)
        self.assertEqual(result.profile.provenance.confidence, Decimal("1"))


# ----------------------------------------------------------------------
# Stable ordering / hash independence from row order
# ----------------------------------------------------------------------


class OrderIndependenceTest(unittest.TestCase):
    """Domain content and hash must be row-order-independent."""

    def test_constituent_order_is_sorted_by_stock_code(self) -> None:
        # The domain sort key orders Shanghai six-digit codes before
        # Shenzhen / ChiNext six-digit codes; the mapper just forwards
        # the constituents tuple to ``IndexConstituentSnapshot.create``
        # which applies the sort internally.
        result = _map()
        codes = [c.stock_code for c in result.constituent_snapshot.constituents]
        self.assertEqual(codes, ["600519", "601318", "000858", "300750"])

    def test_reordered_payloads_yield_identical_content_hashes(self) -> None:
        payload_a = _standard_payload()
        reversed_payload = list(reversed(payload_a))
        rot = [payload_a[1], payload_a[3], payload_a[0], payload_a[2]]

        result_orig = _map(payload_a)
        result_reversed = _map(reversed_payload)
        result_rotated = _map(rot)

        self.assertEqual(
            result_orig.profile.content_hash,
            result_reversed.profile.content_hash,
        )
        self.assertEqual(
            result_orig.profile.content_hash,
            result_rotated.profile.content_hash,
        )
        self.assertEqual(
            result_orig.constituent_snapshot.content_hash,
            result_reversed.constituent_snapshot.content_hash,
        )
        self.assertEqual(
            result_orig.constituent_snapshot.content_hash,
            result_rotated.constituent_snapshot.content_hash,
        )

    def test_repeated_calls_on_same_payload_yield_identical_hashes(self) -> None:
        first = _map()
        second = _map()
        self.assertEqual(
            first.profile.content_hash,
            second.profile.content_hash,
        )
        self.assertEqual(
            first.constituent_snapshot.content_hash,
            second.constituent_snapshot.content_hash,
        )

    def test_content_hashes_are_64_hex_chars(self) -> None:
        result = _map()
        for value in (
            result.profile.content_hash,
            result.constituent_snapshot.content_hash,
        ):
            self.assertEqual(len(value), 64)
            int(value, 16)


# ----------------------------------------------------------------------
# Operation / payload guards
# ----------------------------------------------------------------------


class OperationAndPayloadTest(unittest.TestCase):
    def test_wrong_operation_raises_provider_data_contract_error(self) -> None:
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(operation="fund_etf_fund_info_em")
        self.assertEqual(ctx.exception.code, "WRONG_OPERATION")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_empty_raw_payload_raises(self) -> None:
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload=[])
        self.assertEqual(ctx.exception.code, "EMPTY_PAYLOAD")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_dict_row_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = ["not", "a", "dict"]
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "MALFORMED_CSINDEX_ROW")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_akshare_response_raises_contract_error(self) -> None:
        with self.assertRaises(ProviderDataContractError):
            map_csindex_constituent_weights(
                {"operation": _EXPECTED_OPERATION, "raw_payload": _standard_payload()},
                observed_at=_OBSERVED_AT,
            )


# ----------------------------------------------------------------------
# Required-field guard
# ----------------------------------------------------------------------


class RequiredFieldsTest(unittest.TestCase):
    def test_missing_date_field_raises(self) -> None:
        payload = _standard_payload()
        payload[0] = {k: v for k, v in payload[0].items() if k != "日期"}
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_FIELD")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_empty_string_field_raises_missing_required_field(self) -> None:
        payload = _standard_payload()
        payload[0] = dict(payload[0], 指数代码="")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_FIELD")

    def test_empty_string_index_name_raises(self) -> None:
        payload = _standard_payload()
        payload[0] = dict(payload[0], 指数名称="   ")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "EMPTY_FIELD")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_malformed_date_raises(self) -> None:
        payload = _standard_payload()
        payload[0] = dict(payload[0], 日期="not-a-date")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_DATE")
        self.assertEqual(ctx.exception.provider_key, "akshare")


# ----------------------------------------------------------------------
# Cross-row consistency
# ----------------------------------------------------------------------


class CrossRowConsistencyTest(unittest.TestCase):
    def test_mixed_source_date_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 日期="20260801")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INCONSISTENT_SOURCE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_mixed_index_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 指数代码="000905")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INCONSISTENT_SOURCE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_mixed_index_name_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 指数名称="中证500")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INCONSISTENT_SOURCE")
        self.assertEqual(ctx.exception.provider_key, "akshare")


# ----------------------------------------------------------------------
# Code normalisation
# ----------------------------------------------------------------------


class CodeNormalisationTest(unittest.TestCase):
    def test_non_six_digit_index_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 指数代码="9999")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_CODE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_numeric_index_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 指数代码="ABCDEF")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_CODE")

    def test_non_six_digit_stock_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 成分券代码="60051")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_CODE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_numeric_stock_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 成分券代码="A00619")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_CODE")


# ----------------------------------------------------------------------
# Weight validation
# ----------------------------------------------------------------------


class WeightValidationTest(unittest.TestCase):
    def test_bool_weight_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 权重=True)
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "WEIGHT_IS_BOOL")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_finite_weight_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 权重=float("inf"))
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "NON_FINITE_WEIGHT")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_weight_above_100_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 权重="100.0001")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "WEIGHT_OUT_OF_RANGE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_weight_below_zero_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 权重="-0.1")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "WEIGHT_OUT_OF_RANGE")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_decimal_weight_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 权重="not-a-number")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "INVALID_WEIGHT")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_weight_boundary_zero_and_hundred_are_accepted(self) -> None:
        payload = [
            {
                "日期": "20260731",
                "指数代码": "000300",
                "指数名称": "沪深300",
                "成分券代码": "600519",
                "权重": "0",
            },
            {
                "日期": "20260731",
                "指数代码": "000300",
                "指数名称": "沪深300",
                "成分券代码": "601318",
                "权重": "100",
            },
        ]
        result = _map(payload)
        by_code = {c.stock_code: c.weight for c in result.constituent_snapshot.constituents}
        self.assertEqual(by_code["600519"], Decimal("0"))
        self.assertEqual(by_code["601318"], Decimal("1"))


# ----------------------------------------------------------------------
# Duplicate constituents
# ----------------------------------------------------------------------


class DuplicateConstituentTest(unittest.TestCase):
    def test_duplicate_stock_code_raises(self) -> None:
        payload = _standard_payload()
        payload[1] = dict(payload[1], 成分券代码="600519")
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(payload)
        self.assertEqual(ctx.exception.code, "DUPLICATE_CONSTITUENT")
        self.assertEqual(ctx.exception.provider_key, "akshare")


# ----------------------------------------------------------------------
# Naive observed_at
# ----------------------------------------------------------------------


class ObservedAtTest(unittest.TestCase):
    def test_naive_observed_at_raises(self) -> None:
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(observed_at=_NAIVE_OBSERVED_AT)
        self.assertEqual(ctx.exception.code, "NAIVE_OBSERVED_AT")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_non_datetime_observed_at_raises(self) -> None:
        with self.assertRaises(ProviderDataContractError) as ctx:
            _map(observed_at="2026-07-31T12:00:00+00:00")  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "INVALID_OBSERVED_AT")
        self.assertEqual(ctx.exception.provider_key, "akshare")

    def test_utc_plus_eight_observed_at_is_accepted(self) -> None:
        result = _map(observed_at=_OBSERVED_AT_PLUS_EIGHT)
        self.assertEqual(result.profile.provenance.observed_at, _OBSERVED_AT_PLUS_EIGHT)


if __name__ == "__main__":
    unittest.main()
