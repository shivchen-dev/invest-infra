"""Tests for deterministic multi-provider coverage report merging."""

from __future__ import annotations

import hashlib

import pytest
from invest_pipeline.provider_coverage_merge import (
    CoverageReportMergeError,
    merge_coverage_reports,
)
from invest_pipeline.provider_coverage_report import (
    CoverageReportModel,
    ProviderCoverageRow,
    SymbolCoverageRow,
)


def _report(
    provider_key: str,
    *,
    schema_version: int = 1,
    generated_at: str = "2026-08-04T00:00:00+00:00",
    content_hash: str | None = None,
) -> CoverageReportModel:
    row = SymbolCoverageRow(
        symbol="510300",
        requested_start=None,
        requested_end=None,
        covered_start=None,
        covered_end=None,
        record_count=0,
        fields=(),
        requested_fields=None,
        warnings=(),
        errors=(),
    )
    provider = ProviderCoverageRow(
        provider_key=provider_key,
        symbols=(row,),
        requested_start=None,
        requested_end=None,
        requested_fields=None,
        raw_payload_hash=None,
    )
    return CoverageReportModel(
        schema_version=schema_version,
        generated_at=generated_at,
        content_hash=content_hash or f"hash-{provider_key}",
        providers=(provider,),
    )


def test_merge_single_report_preserves_provider_and_schema() -> None:
    report = _report("akshare")

    merged = merge_coverage_reports((report,))

    assert merged.schema_version == report.schema_version
    assert merged.generated_at == report.generated_at
    assert merged.providers == report.providers
    assert merged.content_hash == hashlib.sha256(b"hash-akshare").hexdigest()


def test_merge_multiple_reports_sorts_providers_and_uses_latest_timestamp() -> None:
    eastmoney = _report(
        "eastmoney",
        generated_at="2026-08-04T01:00:00+00:00",
        content_hash="east-hash",
    )
    akshare = _report(
        "akshare",
        generated_at="2026-08-04T02:00:00+00:00",
        content_hash="ak-hash",
    )

    merged = merge_coverage_reports((eastmoney, akshare))

    assert [provider.provider_key for provider in merged.providers] == [
        "akshare",
        "eastmoney",
    ]
    assert merged.generated_at == "2026-08-04T02:00:00+00:00"
    expected = hashlib.sha256(b"ak-hash\x1feast-hash").hexdigest()
    assert merged.content_hash == expected


def test_merge_rejects_duplicate_provider_keys() -> None:
    with pytest.raises(CoverageReportMergeError, match="duplicate providers"):
        merge_coverage_reports((_report("akshare"), _report("akshare")))


def test_merge_rejects_schema_version_mismatch() -> None:
    with pytest.raises(CoverageReportMergeError, match="schema_version"):
        merge_coverage_reports((_report("akshare"), _report("eastmoney", schema_version=2)))


def test_merge_rejects_empty_and_non_model_inputs() -> None:
    with pytest.raises(CoverageReportMergeError, match="at least one"):
        merge_coverage_reports(())
    with pytest.raises(CoverageReportMergeError, match="CoverageReportModel"):
        merge_coverage_reports((object(),))  # type: ignore[arg-type]


def test_merge_hash_is_independent_of_input_report_order() -> None:
    first = merge_coverage_reports((_report("akshare"), _report("eastmoney")))
    second = merge_coverage_reports((_report("eastmoney"), _report("akshare")))

    assert first == second
