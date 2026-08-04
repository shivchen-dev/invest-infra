"""Pure, deterministic merging of per-provider coverage reports."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .provider_coverage_report import CoverageReportModel


class CoverageReportMergeError(ValueError):
    """Raised when coverage reports cannot be safely combined."""


def merge_coverage_reports(
    reports: Iterable[CoverageReportModel],
) -> CoverageReportModel:
    """Merge distinct provider reports into one deterministic report.

    The aggregate ``content_hash`` is the SHA-256 of the sorted input
    content hashes. It identifies the report composition without pretending
    to be a raw-provider payload hash.
    """

    materialized = tuple(reports)
    if not materialized:
        raise CoverageReportMergeError("at least one coverage report is required")
    if any(not isinstance(report, CoverageReportModel) for report in materialized):
        raise CoverageReportMergeError(
            "reports must contain only CoverageReportModel instances"
        )

    schema_versions = {report.schema_version for report in materialized}
    if len(schema_versions) != 1:
        raise CoverageReportMergeError(
            "coverage reports must use the same schema_version"
        )

    providers = tuple(
        provider
        for report in materialized
        for provider in report.providers
    )
    provider_keys = [provider.provider_key for provider in providers]
    duplicates = sorted(
        {key for key in provider_keys if provider_keys.count(key) > 1}
    )
    if duplicates:
        raise CoverageReportMergeError(
            f"coverage reports contain duplicate providers: {', '.join(duplicates)}"
        )

    aggregate_input = "\x1f".join(sorted(report.content_hash for report in materialized))
    aggregate_hash = hashlib.sha256(aggregate_input.encode("utf-8")).hexdigest()
    return CoverageReportModel(
        schema_version=materialized[0].schema_version,
        generated_at=max(report.generated_at for report in materialized),
        content_hash=aggregate_hash,
        providers=tuple(sorted(providers, key=lambda provider: provider.provider_key)),
    )
