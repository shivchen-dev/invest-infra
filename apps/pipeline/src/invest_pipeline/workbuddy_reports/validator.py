"""M0 first-slice governance validator for WorkBuddy daily-report triplets.

Implements the hard-validation surface defined by
``docs/implementation/WORKBUDDY-GOVERNANCE-M0-CONTRACT.md`` sections
2–6 and 9.  The contract is the authoritative specification; this
module only encodes the rules frozen for M0 (rules version ``1.1.2``,
``sector-seven-step-v2`` strategy compatibility contract).

The public entry point is :func:`validate_triplet`.  The CLI is exposed
through :mod:`invest_pipeline.workbuddy_reports.__main__`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

__all__ = [
    "ValidationResult",
    "validate_triplet",
    "SUPPORTED_RULES_VERSION",
    "TOLERANCE",
    "is_safe_workflow_run_id",
    "is_valid_trade_date",
]

SUPPORTED_RULES_VERSION = "1.1.2"
TOLERANCE = 0.01
_TRADE_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORKFLOW_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PRODUCER_STATUSES = frozenset(
    {"succeeded", "failed_validation", "failed_execution", "needs_rule_confirmation"}
)
_RESULT_CORE_IDENTITY_FIELDS: tuple[str, ...] = (
    "workflow_run_id",
    "trade_date",
    "report_rules_version",
    "strategy_version",
    "producer_status",
)
_QUALITY_CORE_IDENTITY_FIELDS: tuple[str, ...] = (
    "workflow_run_id",
    "trade_date",
)
_CROSS_FILE_IDENTITY_FIELDS: tuple[str, ...] = (
    "workflow_run_id",
    "trade_date",
    "report_rules_version",
    "strategy_version",
)
_STAGE_COUNT_FIELDS: tuple[str, ...] = (
    "input_count",
    "passed_count",
    "rejected_count",
    "missing_data_count",
)


@dataclass(slots=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    governance_status: str
    file_hashes: dict[str, dict[str, int | str]] = field(default_factory=dict)
    error_codes: list[str] = field(default_factory=list)
    workflow_run_id: str | None = None
    trade_date: str | None = None
    producer_status: str | None = None

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    @property
    def exit_code(self) -> int:
        if self.governance_status == "accepted":
            return 0
        if self.governance_status == "partial":
            return 2
        if self.governance_status == "rejected" and (
            "input_error" in self.error_codes or "unsupported_version" in self.error_codes
        ):
            return 4
        return 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "trade_date": self.trade_date,
            "producer_status": self.producer_status,
            "governance_status": self.governance_status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "file_hashes": {
                role: dict(details) for role, details in self.file_hashes.items()
            },
            "exit_code": self.exit_code,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_triplet(
    result_path: str | os.PathLike[str],
    report_path: str | os.PathLike[str],
    quality_path: str | os.PathLike[str],
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    error_codes: list[str] = []

    try:
        result_path = os.fspath(result_path)
        report_path = os.fspath(report_path)
        quality_path = os.fspath(quality_path)
    except (TypeError, ValueError) as exc:
        return _verdict(
            "rejected",
            [f"invalid triplet path: {exc}"],
            [],
            error_codes=["input_error"],
        )

    paths = {
        "result": result_path,
        "report": report_path,
        "quality_report": quality_path,
    }
    loaded: dict[str, bytes] = {}
    for role, path in paths.items():
        payload = _read_bytes(path, errors, label=role)
        if payload is not None:
            loaded[role] = payload
    file_hashes = _independent_hashes(loaded)
    if errors or len(loaded) != len(paths):
        return _verdict("rejected", errors, warnings, file_hashes, error_codes + ["input_error"])

    result = _parse_json(loaded["result"], errors, label="result")
    report_text = _parse_utf8(loaded["report"], errors, label="report")
    quality = _parse_json(loaded["quality_report"], errors, label="quality_report")
    if result is None or report_text is None or quality is None:
        return _verdict("rejected", errors, warnings, file_hashes, error_codes + ["input_error"])
    if isinstance(result, str) or isinstance(quality, str):
        return _verdict("rejected", errors, warnings, file_hashes, error_codes + ["input_error"])

    _normalize_producer_status_alias(result, warnings)
    _check_hashes(
        quality=quality,
        result_filename=os.path.basename(result_path),
        report_filename=os.path.basename(report_path),
        result_bytes=loaded["result"],
        report_bytes=loaded["report"],
        warnings=warnings,
    )
    _check_core_identity_result(result, errors, error_codes)
    _check_core_identity_quality(quality, errors)
    _check_cross_file_identity(result, quality, errors)
    _check_schema_versions(result, quality, errors, error_codes)
    _check_report_rules_version(result, quality, errors, error_codes)

    if errors:
        return _verdict(
            "rejected",
            errors,
            warnings,
            file_hashes,
            error_codes,
            result.get("workflow_run_id"),
            result.get("trade_date"),
            result.get("producer_status"),
        )

    sources = _collect_sources(result.get("sources"))
    _check_stages(result.get("stages"), errors, warnings)
    _check_applied_rules(result, sources, errors)
    _check_missing_data_not_scored_or_ranked(result, errors)
    _check_scores(result, errors)
    sector_score = _sector_score_map(result.get("scores"))
    _check_ranking(result.get("ranking"), sector_score, errors)
    _check_candidates(result.get("candidates"), result.get("ranking"), errors)
    _check_markdown(result, report_text, errors)

    if errors:
        return _verdict(
            "rejected",
            errors,
            warnings,
            file_hashes,
            error_codes,
            result.get("workflow_run_id"),
            result.get("trade_date"),
            result.get("producer_status"),
        )

    status = _classify_partial(result) or "accepted"
    return _verdict(
        status,
        errors,
        warnings,
        file_hashes,
        error_codes,
        result.get("workflow_run_id"),
        result.get("trade_date"),
        result.get("producer_status"),
    )


def _read_bytes(path: str, errors: list[str], *, label: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        errors.append(f"{label} file unreadable: {exc}")
        return None


def _parse_json(payload: bytes, errors: list[str], *, label: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} JSON/UTF-8 parse failed: {exc}")
        return None
    if not isinstance(decoded, dict):
        errors.append(f"{label} JSON must be an object")
        return None
    return decoded


def _parse_utf8(payload: bytes, errors: list[str], *, label: str) -> str | None:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{label} is not valid UTF-8: {exc}")
        return None


def _independent_hashes(loaded: dict[str, bytes]) -> dict[str, dict[str, int | str]]:
    return {
        role: {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for role, payload in loaded.items()
    }


def _verdict(
    status: str,
    errors: list[str],
    warnings: list[str],
    file_hashes: dict[str, dict[str, int | str]] | None = None,
    error_codes: list[str] | None = None,
    workflow_run_id: Any = None,
    trade_date: Any = None,
    producer_status: Any = None,
) -> ValidationResult:
    return ValidationResult(
        errors=list(errors),
        warnings=list(warnings),
        governance_status=status,
        file_hashes=dict(file_hashes or {}),
        error_codes=list(error_codes or []),
        workflow_run_id=workflow_run_id if isinstance(workflow_run_id, str) else None,
        trade_date=trade_date if isinstance(trade_date, str) else None,
        producer_status=producer_status if isinstance(producer_status, str) else None,
    )


def _normalize_producer_status_alias(
    result: dict[str, Any], warnings: list[str]
) -> None:
    """Treat ``result.status`` as a legacy alias for ``producer_status``.

    Per M0 contract §2, ``producer_status`` is the canonical field on the
    ``result`` payload; ``status`` is accepted as a backward-compatible
    alias.  The value is normalized in place so downstream core-identity
    and verdict logic sees a single canonical field, and a warning is
    recorded for observability.  An already-present ``producer_status``
    always wins — the alias is only consulted when the canonical field
    is missing.
    """
    if "producer_status" in result:
        return
    legacy = result.get("status")
    if isinstance(legacy, str) and legacy:
        warnings.append(
            f"result.status={legacy!r} treated as legacy alias for producer_status"
        )
        result["producer_status"] = legacy
    elif legacy is not None:
        warnings.append(
            f"result.status={legacy!r} ignored; expected a non-empty string"
        )


def is_valid_trade_date(value: str) -> bool:
    """Return ``True`` when ``value`` is a strict ``YYYY-MM-DD`` calendar date.

    Rejects syntactically-valid but semantically-impossible dates such as
    ``2026-13-01`` (month out of range) or ``2026-02-30`` (day out of
    range), wrong separators (``2026/08/13``), two-digit years
    (``26-08-13``), and any trailing time component
    (``2026-08-13T10:00:00``).  Used as the boundary check that prevents
    ``<root>/runs/<trade_date>/`` from being constructed with attacker-
    controlled characters.
    """
    if not isinstance(value, str) or not _TRADE_DATE_PATTERN.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_safe_workflow_run_id(value: str) -> bool:
    """Return ``True`` when ``value`` is safe to use as a single path segment.

    The M1/M2 archive layout is
    ``<root>/runs/<trade_date>/<workflow_run_id>/``.  Because the value
    flows straight into ``os.path.join`` and ultimately ``mkdir`` /
    ``os.replace``, it must (a) be a non-empty string of bounded length,
    (b) start with an ASCII letter or digit so a leading dot cannot
    smuggle ``.`` / ``..`` / ``.hidden`` through, and (c) contain only
    ASCII letters, digits, ``_``, ``-``, and the safe interior dot — no
    path separators, no whitespace, no control characters.  This check
    is the validator-side fail-closed barrier against path traversal;
    the archive module re-validates defensively against the same rule.
    """
    return isinstance(value, str) and bool(_WORKFLOW_RUN_ID_PATTERN.match(value))


def _check_core_identity_result(
    payload: dict[str, Any],
    errors: list[str],
    error_codes: list[str],
) -> None:
    for name in _RESULT_CORE_IDENTITY_FIELDS:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            errors.append(f"core identity field '{name}' missing, empty, or not a string")
            continue
        if name == "producer_status" and value not in _PRODUCER_STATUSES:
            errors.append(f"core identity field 'producer_status={value!r}' is not supported")
            error_codes.append("unsupported_version")
        if name == "trade_date" and not is_valid_trade_date(value):
            errors.append(
                f"core identity field 'trade_date={value!r}' is not a valid "
                f"YYYY-MM-DD calendar date"
            )
            error_codes.append("input_error")
        if name == "workflow_run_id" and not is_safe_workflow_run_id(value):
            errors.append(
                f"core identity field 'workflow_run_id={value!r}' is not a safe "
                f"single path-segment identifier"
            )
            error_codes.append("input_error")


def _check_core_identity_quality(
    payload: dict[str, Any], errors: list[str]
) -> None:
    """Quality_report only requires the run identity fields.

    Per M0 contract §2, ``quality_report`` does not need to repeat
    ``producer_status`` or the rule/strategy metadata; it participates
    in cross-file identity checks for those fields only when they are
    present.  ``workflow_run_id`` and ``trade_date`` are the minimum
    fields the quality report must carry to bind itself to the run.

    When present, the values must satisfy the same format constraints
    as the result's identity fields so that cross-file matching cannot
    be spoofed by a quality payload that smuggles a different shape
    through the comparison.
    """
    for name in _QUALITY_CORE_IDENTITY_FIELDS:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            errors.append(
                f"quality_report core identity field '{name}' missing, empty, or not a string"
            )
            continue
        if name == "trade_date" and not is_valid_trade_date(value):
            errors.append(
                f"quality_report core identity field 'trade_date={value!r}' is "
                f"not a valid YYYY-MM-DD calendar date"
            )
        if name == "workflow_run_id" and not is_safe_workflow_run_id(value):
            errors.append(
                f"quality_report core identity field 'workflow_run_id={value!r}' "
                f"is not a safe single path-segment identifier"
            )


def _check_cross_file_identity(
    result: dict[str, Any], quality: dict[str, Any], errors: list[str]
) -> None:
    """Cross-file identity uses only the four canonical identity fields.

    ``producer_status`` is intentionally excluded: per M0 contract §2 the
    quality report does not need to repeat it, so comparing it across
    files would manufacture false identity mismatches for fully valid
    triplets.
    """
    for name in _CROSS_FILE_IDENTITY_FIELDS:
        if name not in result or name not in quality:
            continue
        if result[name] != quality[name]:
            errors.append(
                f"core identity mismatch on '{name}': "
                f"result={result[name]!r} quality={quality[name]!r}"
            )


def _check_schema_versions(
    result: dict[str, Any],
    quality: dict[str, Any],
    errors: list[str],
    error_codes: list[str],
) -> None:
    for label, payload in (("result", result), ("quality_report", quality)):
        raw = payload.get("schema_version")
        major = _parse_schema_major(raw)
        if major is None:
            errors.append(f"{label}.schema_version missing or unparseable")
            error_codes.append("unsupported_version")
            continue
        if major >= 2:
            errors.append(
                f"{label}.schema_version major={major} not supported (only major=1 accepted)"
            )
            error_codes.append("unsupported_version")


def _parse_schema_major(raw: Any) -> int | None:
    if not isinstance(raw, str) or not raw:
        return None
    token = raw.split("@", 1)[-1].strip()
    head = token.split(".", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def _check_report_rules_version(
    result: dict[str, Any],
    quality: dict[str, Any],
    errors: list[str],
    error_codes: list[str],
) -> None:
    for label, payload in (("result", result), ("quality_report", quality)):
        version = payload.get("report_rules_version")
        if version != SUPPORTED_RULES_VERSION:
            errors.append(
                f"{label}.report_rules_version={version!r} not supported; "
                f"first supported rules version is {SUPPORTED_RULES_VERSION}"
            )
            error_codes.append("unsupported_version")





def _check_stages(stages: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(stages, list) or not stages:
        errors.append("stages missing or empty")
        return
    normalized: list[dict[str, Any]] = []
    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            errors.append(f"stages[{i}] is not an object")
            continue
        msg = _check_single_stage(stage, index=i, warnings=warnings)
        if msg is not None:
            errors.append(f"stages[{i}] {msg}")
        normalized.append(stage)
    if errors:
        return
    prev_passed: set[str] | None = None
    for i, stage in enumerate(normalized):
        current_input = set(stage.get("input_symbols", []))
        current_passed = set(stage.get("passed_symbols", []))
        if prev_passed is not None and current_input != prev_passed:
            errors.append(
                f"stage adjacency violated: stages[{i - 1}].passed_symbols "
                f"!= stages[{i}].input_symbols"
            )
            return
        prev_passed = current_passed


def _check_single_stage(
    stage: dict[str, Any],
    *,
    index: int,
    warnings: list[str] | None = None,
) -> str | None:
    inp = list(stage.get("input_symbols", []))
    passed = list(stage.get("passed_symbols", []))
    rejected = list(stage.get("rejected_symbols", []))
    missing = list(stage.get("missing_data_symbols", []))

    if len(set(inp)) != len(inp):
        return "input_symbols contains duplicates"
    if len(inp) != len(passed) + len(rejected) + len(missing):
        return (
            f"counts do not balance: "
            f"input={len(inp)} passed={len(passed)} "
            f"rejected={len(rejected)} missing={len(missing)}"
        )

    sets = (
        ("passed_symbols", set(passed)),
        ("rejected_symbols", set(rejected)),
        ("missing_data_symbols", set(missing)),
    )
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            if sets[i][1] & sets[j][1]:
                return f"{sets[i][0]} and {sets[j][0]} intersect"

    union = set(passed) | set(rejected) | set(missing)
    if union != set(inp):
        return "passed ∪ rejected ∪ missing != input_symbols"

    if warnings is not None:
        _warn_stage_count_mismatch(stage, index=index, warnings=warnings)
    return None


def _warn_stage_count_mismatch(
    stage: dict[str, Any],
    *,
    index: int,
    warnings: list[str],
) -> None:
    """Cross-check producer-declared stage counts against set-derived counts.

    Per M0 contract §5, the governor recomputes counts from the
    ``*_symbols`` sets itself; producer-provided ``*_count`` fields are
    only used as a soft cross-check and never constitute an extra hard
    barrier.  Mismatches therefore surface as warnings, not errors.
    """
    if not any(name in stage for name in _STAGE_COUNT_FIELDS):
        return
    expected = {
        "input_count": len(stage.get("input_symbols", []) or []),
        "passed_count": len(stage.get("passed_symbols", []) or []),
        "rejected_count": len(stage.get("rejected_symbols", []) or []),
        "missing_data_count": len(stage.get("missing_data_symbols", []) or []),
    }
    for name, exp in expected.items():
        if name not in stage:
            continue
        declared = stage[name]
        if isinstance(declared, bool) or not isinstance(declared, int):
            warnings.append(
                f"stages[{index}].{name}={declared!r} not an integer; ignoring declared count"
            )
            continue
        if declared != exp:
            warnings.append(
                f"stages[{index}].{name} declared={declared} disagrees with "
                f"set-derived={exp}"
            )


# ---------------------------------------------------------------------------
# Applied rules source_ref resolution
# ---------------------------------------------------------------------------


def _collect_sources(raw: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(raw, list):
        return ids
    for entry in raw:
        if isinstance(entry, dict):
            sid = entry.get("source_id")
            if isinstance(sid, str):
                ids.add(sid)
    return ids


def _extract_source_refs(rule: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    value = rule.get("source_ref")
    if isinstance(value, str):
        refs.append(value)
    value = rule.get("source_refs")
    if isinstance(value, str):
        refs.append(value)
    elif isinstance(value, list):
        refs.extend(v for v in value if isinstance(v, str))
    return refs


def _validate_source_refs(
    refs: list[str], sources: set[str], *, label: str
) -> str | None:
    if not refs:
        return f"{label} declares no source_ref/source_refs"
    missing = [r for r in refs if r not in sources]
    if missing:
        return f"{label} unresolved source_ref: {missing}"
    return None


def _check_applied_rules(result: dict[str, Any], sources: set[str], errors: list[str]) -> None:
    # Top-level ``applied_rules`` (validated when present; some producers
    # move source references into stages[*].applied_rules instead).
    applied = result.get("applied_rules")
    if applied is not None and not isinstance(applied, list):
        errors.append("applied_rules must be a list when present")
    elif isinstance(applied, list):
        for i, rule in enumerate(applied):
            if not isinstance(rule, dict):
                errors.append(f"applied_rules[{i}] is not an object")
                continue
            msg = _validate_source_refs(
                _extract_source_refs(rule), sources, label=f"applied_rules[{i}]"
            )
            if msg is not None:
                errors.append(msg)

    # Recurse into ``stages[*].applied_rules``: string rule IDs are opaque
    # references and skip source-ref checks; rule objects must resolve.
    stages = result.get("stages")
    if isinstance(stages, list):
        for si, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            stage_applied = stage.get("applied_rules")
            if stage_applied is None:
                continue
            if not isinstance(stage_applied, list):
                errors.append(f"stages[{si}].applied_rules must be a list when present")
                continue
            for ri, rule in enumerate(stage_applied):
                label = f"stages[{si}].applied_rules[{ri}]"
                if isinstance(rule, str):
                    continue
                if not isinstance(rule, dict):
                    errors.append(f"{label} is not a string or object")
                    continue
                msg = _validate_source_refs(
                    _extract_source_refs(rule), sources, label=label
                )
                if msg is not None:
                    errors.append(msg)

    # ``rule_definitions[*].source_refs`` must resolve when present.
    rule_defs = result.get("rule_definitions")
    if isinstance(rule_defs, list):
        for di, defn in enumerate(rule_defs):
            if not isinstance(defn, dict):
                continue
            value = defn.get("source_refs")
            refs_list: list[str] = []
            if isinstance(value, list):
                refs_list = [v for v in value if isinstance(v, str)]
            elif isinstance(value, str):
                refs_list = [value]
            msg = _validate_source_refs(
                refs_list, sources, label=f"rule_definitions[{di}]"
            )
            if msg is not None:
                errors.append(msg)


# ---------------------------------------------------------------------------
# Scores / ranking / candidates
# ---------------------------------------------------------------------------


def _sector_score_map(scores: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(scores, list):
        return out
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sector_id")
        value = entry.get("overall_score")
        if isinstance(sid, str) and isinstance(value, (int, float)):
            out[sid] = float(value)
    return out


def _check_missing_data_not_scored_or_ranked(result: dict[str, Any], errors: list[str]) -> None:
    missing = result.get("missing_data_symbols") or []
    if not isinstance(missing, list) or not missing:
        return
    missing_set = {m for m in missing if isinstance(m, str)}
    if not missing_set:
        return
    scored_sectors = {s.get("sector_id") for s in result.get("scores", []) if isinstance(s, dict)}
    ranked_sectors = {r.get("sector_id") for r in result.get("ranking", []) if isinstance(r, dict)}
    leaked_scores = scored_sectors & missing_set
    leaked_ranking = ranked_sectors & missing_set
    if leaked_scores:
        errors.append(f"missing_data_symbols present in scores: {sorted(leaked_scores)}")
    if leaked_ranking:
        errors.append(f"missing_data_symbols present in ranking: {sorted(leaked_ranking)}")


def _check_scores(result: dict[str, Any], errors: list[str]) -> None:
    scores = result.get("scores")
    if not isinstance(scores, list) or not scores:
        errors.append("scores missing or empty")
        return
    normalization = result.get("normalization") or {}
    if not isinstance(normalization, dict):
        normalization = {}

    for i, entry in enumerate(scores):
        if not isinstance(entry, dict):
            errors.append(f"scores[{i}] is not an object")
            continue
        sid = entry.get("sector_id")
        if not isinstance(sid, str):
            errors.append(f"scores[{i}].sector_id missing or not a string")
            continue
        recomputed = _recompute_overall_score(entry, normalization)
        declared = entry.get("overall_score")
        if recomputed is None:
            errors.append(
                f"scores[{i}] ({sid}) cannot be recomputed: missing dimension_scores or weights"
            )
            continue
        if not isinstance(declared, (int, float)):
            errors.append(f"scores[{i}] ({sid}).overall_score not numeric")
            continue
        if abs(float(declared) - recomputed) > TOLERANCE:
            errors.append(
                f"scores[{i}] ({sid}).overall_score {declared} not within "
                f"tolerance {TOLERANCE} of recomputed {recomputed:.4f}"
            )


def _recompute_overall_score(score: dict[str, Any], normalization: dict[str, Any]) -> float | None:
    dim_scores = score.get("dimension_scores")
    weights = score.get("weights")
    if not isinstance(dim_scores, dict) or not isinstance(weights, dict):
        return None
    norm_dims: dict[str, float] = {}
    for dim, raw in dim_scores.items():
        if not isinstance(raw, (int, float)):
            return None
        if dim not in weights or not isinstance(weights[dim], (int, float)):
            return None
        spec = normalization.get(dim)
        if isinstance(spec, dict):
            lo = spec.get("min")
            hi = spec.get("max")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                if hi == lo:
                    norm_dims[dim] = 0.0
                else:
                    norm_dims[dim] = (float(raw) - float(lo)) / (float(hi) - float(lo))
                continue
        norm_dims[dim] = float(raw)

    numerator = sum(norm_dims[d] * float(weights[d]) for d in norm_dims)
    denominator = sum(float(weights[d]) for d in norm_dims)
    if denominator == 0:
        return None
    return numerator / denominator


def _check_ranking(
    ranking: Any,
    sector_scores: dict[str, float],
    errors: list[str],
) -> None:
    if not isinstance(ranking, list) or not ranking:
        errors.append("ranking missing or empty")
        return
    prev_score: float | None = None
    prev_sector: str | None = None
    for i, entry in enumerate(ranking):
        if not isinstance(entry, dict):
            errors.append(f"ranking[{i}] is not an object")
            continue
        sid = entry.get("sector_id")
        if not isinstance(sid, str):
            errors.append(f"ranking[{i}].sector_id missing or not a string")
            continue
        if sid not in sector_scores:
            errors.append(f"ranking[{i}] references sector_id {sid!r} not in scores")
            continue
        score = sector_scores[sid]
        if prev_score is not None:
            if score > prev_score + 1e-9:
                errors.append(
                    f"ranking not descending at position {i}: "
                    f"{sid}={score} > {prev_sector}={prev_score}"
                )
            elif abs(score - prev_score) <= 1e-9 and (
                prev_sector is not None and sid < prev_sector
            ):
                errors.append(
                    f"ranking tie-breaking violated at position {i}: "
                    f"{sid!r} < {prev_sector!r} with equal score"
                )
        prev_score = score
        prev_sector = sid


def _check_candidates(candidates: Any, ranking: Any, errors: list[str]) -> None:
    if not isinstance(candidates, list) or not candidates:
        return
    if not isinstance(ranking, list):
        errors.append("candidates present but ranking missing")
        return
    n = len(candidates)
    if n > len(ranking):
        errors.append(f"candidates length {n} exceeds ranking length {len(ranking)}")
        return
    top = ranking[:n]
    for i, (cand, rank) in enumerate(zip(candidates, top, strict=True)):
        if not isinstance(cand, dict) or not isinstance(rank, dict):
            continue
        c_status = cand.get("candidate_status")
        r_status = rank.get("ranking_status")
        if c_status != r_status:
            errors.append(
                f"candidate {i} candidate_status={c_status!r} "
                f"mismatches ranking_status={r_status!r}"
            )


# ---------------------------------------------------------------------------
# Markdown cross-check
# ---------------------------------------------------------------------------


def _check_markdown(result: dict[str, Any], md_text: str, errors: list[str]) -> None:
    wid = result.get("workflow_run_id")
    tdate = result.get("trade_date")
    if isinstance(wid, str) and wid not in md_text:
        errors.append("markdown missing workflow_run_id")
    if isinstance(tdate, str) and tdate not in md_text:
        errors.append("markdown missing trade_date")

    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return
    sector_score = _sector_score_map(result.get("scores"))
    for i, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            continue
        sid = cand.get("sector_id")
        status = cand.get("candidate_status")
        score = sector_score.get(sid) if isinstance(sid, str) else None
        if not isinstance(sid, str):
            continue
        if sid not in md_text:
            errors.append(f"markdown missing candidate[{i}] sector_id {sid!r}")
        if score is not None and f"{score:.4f}" not in md_text and str(score) not in md_text:
            errors.append(f"markdown missing candidate[{i}] score for {sid!r}")
        if isinstance(status, str) and status not in md_text:
            errors.append(f"markdown missing candidate[{i}] candidate_status {status!r}")


# ---------------------------------------------------------------------------
# Hash checks (warning vs hard fail)
# ---------------------------------------------------------------------------


def _check_hashes(
    *,
    quality: dict[str, Any],
    result_filename: str,
    report_filename: str,
    result_bytes: bytes,
    report_bytes: bytes,
    warnings: list[str],
) -> None:
    file_hashes = quality.get("file_hashes")
    if not isinstance(file_hashes, dict) or not file_hashes:
        warnings.append("quality_report.file_hashes missing or empty")
        return

    actual = {
        result_filename: hashlib.sha256(result_bytes).hexdigest(),
        report_filename: hashlib.sha256(report_bytes).hexdigest(),
    }

    for filename, declared in file_hashes.items():
        if not isinstance(declared, str):
            warnings.append(f"quality file_hashes[{filename!r}] not a string")
            continue
        computed = actual.get(filename)
        if computed is None:
            warnings.append(f"quality file_hashes references unknown file {filename!r}")
            continue
        if computed != declared:
            warnings.append(
                f"producer hash mismatch for {filename!r}: "
                f"declared={declared[:12]}… recomputed={computed[:12]}…"
            )


# ---------------------------------------------------------------------------
# Partial classification
# ---------------------------------------------------------------------------


def _classify_partial(result: dict[str, Any]) -> str | None:
    missing = result.get("missing_data_symbols")
    if isinstance(missing, list) and any(isinstance(m, str) for m in missing):
        return "partial"

    scores = result.get("scores")
    if isinstance(scores, list):
        for entry in scores:
            if not isinstance(entry, dict):
                continue
            status = entry.get("dimension_status")
            if isinstance(status, dict):
                for dim_state in status.values():
                    if dim_state == "missing":
                        return "partial"
            if entry.get("overall_score") is None:
                return "partial"
    return None


# ---------------------------------------------------------------------------
# CLI helpers (used by __main__.py)
# ---------------------------------------------------------------------------


def discover_triplet(
    source_dir: str | os.PathLike[str],
) -> tuple[str, str, str] | None:
    """Locate the result/report/quality files inside ``source_dir``.

    Returns absolute paths or ``None`` when at least one role is missing or
    ambiguous.  Role identification is purely by glob prefix; the
    governance contract (§2) intentionally allows flexible naming.

    For each role the canonical name is tried first; compatible aliases are
    accepted when the canonical name is absent.  The canonical naming for
    M1 is ``sector_result*.json`` / ``板块强度排行榜*.md`` /
    ``sector_quality*.json``; legacy ``result*.json`` / ``report*.md`` /
    ``quality_report*.json`` triplets remain supported for backward
    compatibility with the 2026-08-13 sample.
    """
    root = os.fspath(source_dir)
    if not os.path.isdir(root):
        return None
    result = (
        _glob_unique(root, "sector_result*.json")
        or _glob_unique(root, "result*.json")
    )
    report = (
        _glob_unique(root, "板块强度排行榜*.md")
        or _glob_unique(root, "report*.md")
    )
    quality = (
        _glob_unique(root, "sector_quality*.json")
        or _glob_unique(root, "quality_report*.json")
    )
    if not (result and report and quality):
        return None
    return result, report, quality


def _glob_unique(root: str, pattern: str) -> str | None:
    import glob

    matches = sorted(glob.glob(os.path.join(root, pattern)))
    if not matches:
        return None
    if len(matches) > 1:
        priority = (
            "sector_result.json",
            "sector_result_",
            "板块强度排行榜",
            "板块强度排行榜_",
            "sector_quality.json",
            "sector_quality_",
        )
        for token in priority:
            for path in matches:
                if os.path.basename(path).startswith(token):
                    return os.path.abspath(path)
        return os.path.abspath(matches[0])
    return os.path.abspath(matches[0])
