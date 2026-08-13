"""Behavioral tests for ``invest_pipeline.workbuddy_reports.validator``.

M0 first slice — only the hard-validation surface defined by
``docs/implementation/WORKBUDDY-GOVERNANCE-M0-CONTRACT.md`` is exercised.
All fixtures are synthetic; the legacy 2026-08-13 sample must NOT be
shaped to look accepted (it lacks ``result.producer_status`` and is
therefore expected to be ``rejected`` even though ``quality_report``
without ``producer_status`` is now explicitly tolerated).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PIPELINE_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_SRC))


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        env["PYTHONPATH"] = f"{_PIPELINE_SRC}{os.pathsep}{pythonpath}"
    else:
        env["PYTHONPATH"] = str(_PIPELINE_SRC)
    return env


def test_module_exposes_validate_triplet() -> None:
    """The public entry point must be importable from the package root."""
    from invest_pipeline.workbuddy_reports import validate_triplet  # noqa: F401

    assert callable(validate_triplet)


def test_supported_rules_version_is_1_1_2() -> None:
    """The frozen M0 rules version is 1.1.2 per WORKBUDDY-REPORT-RULES.md."""
    from invest_pipeline.workbuddy_reports import SUPPORTED_RULES_VERSION

    assert SUPPORTED_RULES_VERSION == "1.1.2"


def test_accepted_when_result_uses_status_alias(tmp_path: Path) -> None:
    """``result.status`` is a legacy alias for ``producer_status`` (M0 §2).

    It is normalized in place with a warning and the triplet remains
    ``accepted`` when no other check fails.
    """
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["status"] = payload.pop("producer_status")
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    _refresh_quality_hashes(quality, result_path, report_path)
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["producer_status"] == "succeeded"
    assert any(
        "status" in w and "alias" in w for w in verdict["warnings"]
    ), verdict


def test_accepted_when_quality_report_lacks_producer_status(tmp_path: Path) -> None:
    """``quality_report`` is not required to repeat ``producer_status``.

    M0 contract §2 explicitly lists ``producer_status`` as optional on the
    quality payload; the triplet is still ``accepted`` when only the run
    identity fields are present in the quality report.
    """
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality.pop("producer_status", None)
    _refresh_quality_hashes(quality, result_path, report_path)
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["errors"] == [], verdict


def test_stage_count_mismatch_is_warning_only(tmp_path: Path) -> None:
    """Producer-declared stage counts that disagree with set-derived counts
    surface as warnings; they are not an extra hard barrier (M0 §5)."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    stages = _good_stages()
    # Deliberately wrong declared counts on stage 0; sets are unchanged.
    stages[0]["input_count"] = 99
    stages[0]["passed_count"] = 42
    stages[0]["rejected_count"] = 0
    stages[0]["missing_data_count"] = 0

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"stages": stages},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["errors"] == [], verdict
    warning_text = " ".join(verdict["warnings"])
    assert "input_count" in warning_text
    assert "passed_count" in warning_text


def test_stage_count_non_integer_is_warning_only(tmp_path: Path) -> None:
    """Non-integer ``*_count`` fields are reported as warnings but never
    escalate to a hard failure."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    stages = _good_stages()
    stages[0]["input_count"] = "3"
    stages[0]["passed_count"] = None

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"stages": stages},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    warning_text = " ".join(verdict["warnings"])
    assert "input_count" in warning_text
    assert "passed_count" in warning_text


def test_status_alias_does_not_override_existing_producer_status(tmp_path: Path) -> None:
    """If both ``status`` and ``producer_status`` are present on ``result``,
    the canonical ``producer_status`` wins and the alias is silently
    ignored (no warning is emitted for the alias path itself)."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["status"] = "succeeded"
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["producer_status"] == "succeeded"
    assert not any("alias" in w for w in verdict["warnings"]), verdict


# ---------------------------------------------------------------------------
# Path-traversal regression: trade_date / workflow_run_id format barriers
# ---------------------------------------------------------------------------


_UNSAFE_WORKFLOW_RUN_IDS = [
    pytest.param("/etc/passwd", id="absolute-path"),
    pytest.param("wr/../escape", id="parent-traversal-segment"),
    pytest.param("/", id="bare-slash"),
    pytest.param("wr\\..\\escape", id="backslash-segment"),
    pytest.param("wr id", id="whitespace"),
    pytest.param("a" * 129, id="too-long-129"),
    pytest.param(".", id="dot-only"),
    pytest.param("..", id="dot-dot-only"),
    pytest.param(".hidden", id="leading-dot"),
]


@pytest.mark.parametrize("workflow_run_id", _UNSAFE_WORKFLOW_RUN_IDS)
def test_unsafe_workflow_run_id_is_rejected(
    tmp_path: Path, workflow_run_id: str
) -> None:
    """Format barrier for ``workflow_run_id`` (M0 contract §7).

    Accepts only ASCII letters/digits/``_``/``-``/interior ``.`` starting
    with a letter or digit, length 1–128.  Anything else — absolute
    paths, ``..``/``.hidden``/``.`` segments, path separators, whitespace,
    oversize strings — must be rejected with ``input_error`` so the
    archive module never receives a verdict containing it.  (Empty input
    is exercised through the separate "missing or empty" identity check
    and is intentionally not in this matrix.)"""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"workflow_run_id": workflow_run_id},
        quality_overrides={"workflow_run_id": workflow_run_id},
    )
    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert "input_error" in verdict.error_codes, verdict
    assert any(
        "workflow_run_id" in e and "path-segment" in e for e in verdict["errors"]
    ), verdict


def test_safe_workflow_run_id_with_dot_segment_is_accepted(
    tmp_path: Path,
) -> None:
    """Safe interior dot is allowed (M0 contract §7).

    ``wr.001`` is the canonical safe form — alphanumeric start, bounded
    length, ASCII-only — and must be accepted so the validator does not
    reject well-formed producer identifiers that contain a dot."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"workflow_run_id": "wr.001"},
        quality_overrides={"workflow_run_id": "wr.001"},
    )
    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["errors"] == [], verdict


_UNSAFE_TRADE_DATES = [
    pytest.param("2026/08/13", id="wrong-separator"),
    pytest.param("2026-13-01", id="invalid-month"),
    pytest.param("2026-02-30", id="invalid-day"),
    pytest.param("26-08-13", id="two-digit-year"),
    pytest.param("2026-08-13T10:00:00", id="trailing-time"),
    pytest.param("../2026-08-13", id="parent-traversal"),
]


@pytest.mark.parametrize("trade_date", _UNSAFE_TRADE_DATES)
def test_unsafe_trade_date_is_rejected(tmp_path: Path, trade_date: str) -> None:
    """Format barrier for ``trade_date`` (M0 contract §7).

    Strict ``YYYY-MM-DD`` calendar date only.  Wrong separators, out-of-
    range components, two-digit years, trailing time components, and
    parent-traversal prefixes all reject with ``input_error`` so the
    runs/ directory cannot be escaped."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"trade_date": trade_date},
        quality_overrides={"trade_date": trade_date},
    )
    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert "input_error" in verdict.error_codes, verdict
    assert any("trade_date" in e for e in verdict["errors"]), verdict


def test_quality_report_with_malformed_identity_is_rejected(
    tmp_path: Path,
) -> None:
    """Cross-file identity matching cannot be used to smuggle a bad
    value through a matching quality_report — the validator rejects the
    malformed value at the boundary regardless of cross-file parity."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"workflow_run_id": "wr-2026-08-13-001"},
        quality_overrides={"workflow_run_id": "wr/../escape"},
    )
    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any(
        "quality_report" in e and "workflow_run_id" in e for e in verdict["errors"]
    ), verdict


# ---------------------------------------------------------------------------
# Fixture builders (synthetic; deliberately minimal)
# ---------------------------------------------------------------------------


def _core_identity(
    *,
    workflow_run_id: str = "wr-2026-08-13-001",
    trade_date: str = "2026-08-13",
    report_rules_version: str = "1.1.2",
    strategy_version: str = "sector-seven-step-v2@1",
    producer_status: str = "succeeded",
) -> dict[str, object]:
    return {
        "workflow_run_id": workflow_run_id,
        "trade_date": trade_date,
        "report_rules_version": report_rules_version,
        "strategy_version": strategy_version,
        "producer_status": producer_status,
    }


def _good_sources() -> list[dict[str, object]]:
    return [
        {"source_id": "src_market", "type": "market", "path": "ignored"},
        {"source_id": "src_fundamental", "type": "fundamental", "path": "ignored"},
    ]


def _good_stages() -> list[dict[str, object]]:
    return [
        {
            "name": "stage_universe",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB", "CCC"],
            "rejected_symbols": [],
            "missing_data_symbols": [],
        },
        {
            "name": "stage_scoring",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB", "CCC"],
            "rejected_symbols": [],
            "missing_data_symbols": [],
        },
        {
            "name": "stage_ranking",
            "input_symbols": ["AAA", "BBB", "CCC"],
            "passed_symbols": ["AAA", "BBB"],
            "rejected_symbols": ["CCC"],
            "missing_data_symbols": [],
        },
    ]


def _good_scores() -> list[dict[str, object]]:
    return [
        {
            "sector_id": "AAA",
            "dimension_scores": {"growth": 0.9, "value": 0.4},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.9 * 0.6 + 0.4 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
        {
            "sector_id": "BBB",
            "dimension_scores": {"growth": 0.5, "value": 0.7},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.5 * 0.6 + 0.7 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
        {
            "sector_id": "CCC",
            "dimension_scores": {"growth": 0.2, "value": 0.1},
            "weights": {"growth": 0.6, "value": 0.4},
            "overall_score": 0.2 * 0.6 + 0.1 * 0.4,
            "dimension_status": {"growth": "ok", "value": "ok"},
        },
    ]


def _good_ranking() -> list[dict[str, object]]:
    return [
        {"sector_id": "AAA", "ranking_status": "candidate"},
        {"sector_id": "BBB", "ranking_status": "candidate"},
        {"sector_id": "CCC", "ranking_status": "rejected"},
    ]


def _good_candidates() -> list[dict[str, object]]:
    return [
        {"sector_id": "AAA", "candidate_status": "candidate"},
        {"sector_id": "BBB", "candidate_status": "candidate"},
    ]


def _good_applied_rules() -> list[dict[str, object]]:
    return [
        {"rule_id": "rule_growth_floor", "source_ref": "src_market"},
        {"rule_id": "rule_value_ceiling", "source_refs": ["src_fundamental"]},
    ]


def _good_result() -> dict[str, object]:
    return {
        "schema_version": "invest-pipeline/sector-result@1.0",
        **_core_identity(),
        "sources": _good_sources(),
        "stages": _good_stages(),
        "scores": _good_scores(),
        "ranking": _good_ranking(),
        "candidates": _good_candidates(),
        "applied_rules": _good_applied_rules(),
        "missing_data_symbols": [],
        "normalization": {
            "growth": {"min": 0.0, "max": 1.0},
            "value": {"min": 0.0, "max": 1.0},
        },
    }


def _good_quality(*, result_path: Path, report_path: Path) -> dict[str, object]:
    def _sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    return {
        "schema_version": "1.0",
        **_core_identity(),
        "file_hashes": {
            result_path.name: _sha(result_path),
            report_path.name: _sha(report_path),
        },
        "checks": [{"check_id": "self_test", "status": "passed"}],
    }


def _good_markdown(result: dict[str, object]) -> str:
    lines = [
        f"# 板块强度排行榜 {result['trade_date']}",
        "",
        f"workflow_run_id: {result['workflow_run_id']}",
        f"trade_date: {result['trade_date']}",
        f"producer_status: {result['producer_status']}",
        "",
        "| 排名 | 板块 | 综合分 | 候选状态 |",
        "| ---: | --- | ---: | --- |",
    ]
    for i, entry in enumerate(result["ranking"], start=1):
        score = next(
            s["overall_score"] for s in result["scores"] if s["sector_id"] == entry["sector_id"]
        )
        lines.append(f"| {i} | {entry['sector_id']} | {score:.4f} | {entry['ranking_status']} |")
    lines.append("")
    return "\n".join(lines)


def _refresh_quality_hashes(
    quality: dict[str, object], result_path: Path, report_path: Path
) -> None:
    file_hashes = quality.get("file_hashes")
    if not isinstance(file_hashes, dict):
        return
    file_hashes[result_path.name] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    file_hashes[report_path.name] = hashlib.sha256(report_path.read_bytes()).hexdigest()


def _write_triplet(
    tmp_path: Path,
    *,
    result_overrides: dict[str, object] | None = None,
    quality_overrides: dict[str, object] | None = None,
    markdown_text: str | None = None,
    result_file_name: str = "result.json",
    report_file_name: str = "report.md",
    quality_file_name: str = "quality_report.json",
) -> tuple[Path, Path, Path]:
    result = _good_result()
    if result_overrides:
        for key, value in result_overrides.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = {**result[key], **value}
            else:
                result[key] = value

    result_path = tmp_path / result_file_name
    report_path = tmp_path / report_file_name
    quality_path = tmp_path / quality_file_name

    result_path.write_text(json.dumps(result), encoding="utf-8")
    report_path.write_text(
        markdown_text if markdown_text is not None else _good_markdown(result),
        encoding="utf-8",
    )

    quality = _good_quality(result_path=result_path, report_path=report_path)
    if quality_overrides:
        for key, value in quality_overrides.items():
            if isinstance(value, dict) and isinstance(quality.get(key), dict):
                quality[key] = {**quality[key], **value}
            else:
                quality[key] = value
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    return result_path, report_path, quality_path


# ---------------------------------------------------------------------------
# validate_triplet() — pure-Python coverage
# ---------------------------------------------------------------------------


def test_accepted_when_all_hard_checks_pass(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["errors"] == []
    assert verdict["warnings"] == []


def test_partial_when_missing_data_symbols_present(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={
            "stages": [
                {
                    "name": "stage_universe",
                    "input_symbols": ["AAA", "BBB", "CCC"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": ["CCC"],
                },
                {
                    "name": "stage_scoring",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_ranking",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA"],
                    "rejected_symbols": ["BBB"],
                    "missing_data_symbols": [],
                },
            ],
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.7,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
            "ranking": [
                {"sector_id": "AAA", "ranking_status": "candidate"},
                {"sector_id": "BBB", "ranking_status": "rejected"},
            ],
            "candidates": [{"sector_id": "AAA", "candidate_status": "candidate"}],
            "missing_data_symbols": ["CCC"],
        },
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "partial", verdict
    assert verdict["errors"] == []


def test_rejected_when_producer_status_missing(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload.pop("producer_status")
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality.pop("producer_status")
    _refresh_quality_hashes(quality, result_path, report_path)
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("producer_status" in err for err in verdict["errors"])


def test_rejected_when_report_rules_version_unsupported(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"report_rules_version": "1.1.0"},
        quality_overrides={"report_rules_version": "1.1.0"},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("report_rules_version" in err for err in verdict["errors"])


# ---------------------------------------------------------------------------
# Rules-version compatibility matrix (PATCH/MINOR/MAJOR strategy)
# ---------------------------------------------------------------------------


_ACCEPTED_RULES_VERSIONS = pytest.mark.parametrize(
    "rules_version", ["1.1.1", "1.1.2"]
)


@_ACCEPTED_RULES_VERSIONS
def test_accepted_when_report_rules_version_is_in_compat_matrix(
    tmp_path: Path, rules_version: str
) -> None:
    """Versions in the explicit compat matrix are not rejected on version grounds."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"report_rules_version": rules_version},
        quality_overrides={"report_rules_version": rules_version},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert verdict["errors"] == [], verdict
    assert "unsupported_version" not in verdict.error_codes


_REJECTED_RULES_VERSIONS = pytest.mark.parametrize(
    "rules_version", ["1.1.3", "2.0.0"]
)


@_REJECTED_RULES_VERSIONS
def test_rejected_when_report_rules_version_not_in_compat_matrix(
    tmp_path: Path, rules_version: str
) -> None:
    """Versions outside the compat matrix fail-closed with exit code 4."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"report_rules_version": rules_version},
        quality_overrides={"report_rules_version": rules_version},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert "unsupported_version" in verdict.error_codes, verdict
    assert any("report_rules_version" in err for err in verdict["errors"])
    assert verdict.exit_code == 4, verdict


def test_rejected_when_schema_major_ge_2(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"schema_version": "invest-pipeline/sector-result@2.0"},
        quality_overrides={"schema_version": "2.0"},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("schema_version" in err for err in verdict["errors"])


def test_rejected_when_stage_counts_do_not_balance(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    bad_stages = _good_stages()
    bad_stages[0]["passed_symbols"] = ["AAA", "BBB"]  # CCC missing on purpose
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"stages": bad_stages},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("stage" in err.lower() for err in verdict["errors"])


def test_rejected_when_stage_passed_does_not_match_next_input(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    bad_stages = _good_stages()
    bad_stages[1]["input_symbols"] = ["AAA", "BBB"]  # missing CCC
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"stages": bad_stages},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("adjacency" in err.lower() or "passed" in err.lower() for err in verdict["errors"])


def test_rejected_when_score_recompute_fails(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    scores = _good_scores()
    scores[0]["overall_score"] = 0.42  # deliberately wrong; expected ~0.70
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"scores": scores},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("overall_score" in err for err in verdict["errors"])


def test_rejected_when_ranking_not_descending(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    ranking = [
        {"sector_id": "BBB", "ranking_status": "candidate"},
        {"sector_id": "AAA", "ranking_status": "candidate"},
        {"sector_id": "CCC", "ranking_status": "rejected"},
    ]
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"ranking": ranking},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("ranking" in err.lower() for err in verdict["errors"])


def test_rejected_when_candidate_status_mismatch(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    candidates = [
        {"sector_id": "AAA", "candidate_status": "rejected"},
        {"sector_id": "BBB", "candidate_status": "candidate"},
    ]
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"candidates": candidates},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("candidate" in err.lower() for err in verdict["errors"])


def test_rejected_when_source_ref_unresolved(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    applied = [
        {"rule_id": "rule_growth_floor", "source_ref": "src_unknown"},
    ]
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={"applied_rules": applied},
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("source_ref" in err for err in verdict["errors"])


def test_rejected_when_markdown_missing_workflow_run_id(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        markdown_text="# 板块强度排行榜\n\ntrade_date: 2026-08-13\n",
    )

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "rejected", verdict
    assert any("markdown" in err.lower() or "workflow_run_id" in err for err in verdict["errors"])


def test_governance_recomputes_hash_independently(tmp_path: Path) -> None:
    """When a result file is tampered with, governance still parses+reads it
    (the hard read/JSON capability holds) and the resulting hash drift is
    surfaced as a warning, not a hard error."""
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)

    # Append a trailing space so the on-disk bytes diverge from the hash the
    # quality file already declared, but the JSON still parses cleanly.
    result_path.write_text(result_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    assert verdict["governance_status"] == "accepted", verdict
    assert any("hash" in w.lower() for w in verdict["warnings"]), verdict


def test_producer_hash_mismatch_is_warning_only(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    result_path, report_path, quality_path = _write_triplet(tmp_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["file_hashes"][result_path.name] = "0" * 64  # bogus producer hash
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )

    # Producer hash error is a warning; validator independently recomputes and
    # sees the real bytes, so hard validation still passes -> accepted.
    assert verdict["governance_status"] == "accepted", verdict
    assert any("hash" in w.lower() for w in verdict["warnings"])


def test_cli_returns_input_error_for_missing_dir() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "validate",
            "--source-dir",
            "/nonexistent/workbuddy/run",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )

    assert proc.returncode == 4, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "input_error"


def test_cli_exit_codes(tmp_path: Path) -> None:
    from invest_pipeline.workbuddy_reports import validate_triplet

    _write_triplet(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "validate",
            "--source-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "accepted"

    # Re-shape the same triplet into a partial outcome and confirm 2.
    result_path, report_path, quality_path = _write_triplet(
        tmp_path,
        result_overrides={
            "stages": [
                {
                    "name": "stage_universe",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_scoring",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA", "BBB"],
                    "rejected_symbols": [],
                    "missing_data_symbols": [],
                },
                {
                    "name": "stage_ranking",
                    "input_symbols": ["AAA", "BBB"],
                    "passed_symbols": ["AAA"],
                    "rejected_symbols": ["BBB"],
                    "missing_data_symbols": [],
                },
            ],
            "scores": [
                {
                    "sector_id": "AAA",
                    "dimension_scores": {"growth": 0.9, "value": 0.4},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.7,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
                {
                    "sector_id": "BBB",
                    "dimension_scores": {"growth": 0.5, "value": 0.7},
                    "weights": {"growth": 0.6, "value": 0.4},
                    "overall_score": 0.58,
                    "dimension_status": {"growth": "ok", "value": "ok"},
                },
            ],
            "ranking": [
                {"sector_id": "AAA", "ranking_status": "candidate"},
                {"sector_id": "BBB", "ranking_status": "rejected"},
            ],
            "candidates": [{"sector_id": "AAA", "candidate_status": "candidate"}],
            "missing_data_symbols": ["CCC"],
        },
    )
    verdict = validate_triplet(
        result_path=str(result_path),
        report_path=str(report_path),
        quality_path=str(quality_path),
    )
    assert verdict["governance_status"] == "partial"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "validate",
            "--source-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "partial"

    # Drop producer_status -> rejected -> exit 3.
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.pop("producer_status")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality.pop("producer_status")
    _refresh_quality_hashes(quality, result_path, report_path)
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest_pipeline.workbuddy_reports",
            "validate",
            "--source-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_cli_env(),
    )
    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    assert payload["governance_status"] == "rejected"


# ---------------------------------------------------------------------------
# Opt-in real-sample regression
# ---------------------------------------------------------------------------


def test_real_sample_not_rejected_on_version_alone() -> None:
    """Opt-in: when ``WORKBUDDY_REAL_SAMPLE_DIR`` points at a real
    1.1.1 / 1.1.2 triplet the validator must not reject it on version
    grounds; the content-level verdict is unconstrained."""
    real_dir = os.environ.get("WORKBUDDY_REAL_SAMPLE_DIR")
    if not real_dir:
        pytest.skip("WORKBUDDY_REAL_SAMPLE_DIR not set")
    from invest_pipeline.workbuddy_reports import discover_triplet, validate_triplet

    triple = discover_triplet(real_dir)
    assert triple is not None, f"WORKBUDDY_REAL_SAMPLE_DIR={real_dir!r} has no canonical triplet"
    result_path, report_path, quality_path = triple
    verdict = validate_triplet(
        result_path=result_path,
        report_path=report_path,
        quality_path=quality_path,
    )

    assert "unsupported_version" not in verdict.error_codes, verdict
    assert not any("report_rules_version" in err for err in verdict["errors"]), verdict
