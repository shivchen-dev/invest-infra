"""Pure evaluator for the approved sector-strength-ranking v2 strategy."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from invest_domain.strategy import (
    DataBundle,
    DataRequest,
    validate_data_bundle_for_evaluation,
)

STRATEGY_KEY = "sector-strength-ranking"
STRATEGY_VERSION = "2.0.0"
STRATEGY_ARTIFACT_HASH = "e05e2e191311fb3273a2f14748b7265c1cec47a37339f7a70a139a85a7bf68b2"
_SCHEMA_VERSION = "invest-infra-stage-result/1.0"
_GROUPS = frozenset({"industry", "concept", "area"})
_ZGB = re.compile(r"([0-9]+)/([0-9]+)")
_REQUIRED_RULE_IDS = frozenset({"R-A1", "R-A3", "R-A4", "R-A5"})


class SectorEvaluationError(ValueError):
    """A stable, sanitized failure raised when sector evaluation is unsafe."""


def _fail(message: str) -> SectorEvaluationError:
    return SectorEvaluationError(message)


def _parse_inputs(request: object, bundle: object) -> tuple[DataRequest, DataBundle]:
    try:
        parsed_request = (
            DataRequest.from_mapping(request) if isinstance(request, Mapping) else request
        )
        parsed_bundle = DataBundle.from_mapping(bundle) if isinstance(bundle, Mapping) else bundle
        if not isinstance(parsed_request, DataRequest) or not isinstance(parsed_bundle, DataBundle):
            raise TypeError
        validate_data_bundle_for_evaluation(parsed_request, parsed_bundle)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _fail("request or bundle failed evaluation validation") from None
    return parsed_request, parsed_bundle


def _validate_strategy(request: DataRequest, artifact: object) -> None:
    if (
        request.strategy_key != STRATEGY_KEY
        or request.strategy_version != STRATEGY_VERSION
        or request.strategy_artifact_hash != STRATEGY_ARTIFACT_HASH
        or request.stage != "sector_selection"
    ):
        raise _fail("strategy identity or stage is not approved")
    if not isinstance(artifact, Mapping):
        raise _fail("reviewed strategy artifact is required")

    strategy_key = artifact.get("strategy_key", artifact.get("strategy_id"))
    strategy_version = artifact.get("strategy_version", artifact.get("version_candidate"))
    artifact_hash = artifact.get("strategy_artifact_hash", STRATEGY_ARTIFACT_HASH)
    rules = artifact.get("rules")
    if isinstance(rules, Mapping):
        rule_ids = frozenset(str(key) for key in rules)
    elif isinstance(rules, Sequence) and not isinstance(rules, (str, bytes, bytearray)):
        rule_ids = frozenset(item.get("id") for item in rules if isinstance(item, Mapping))
    else:
        rule_ids = frozenset()
    if (
        strategy_key != STRATEGY_KEY
        or strategy_version != STRATEGY_VERSION
        or artifact_hash != STRATEGY_ARTIFACT_HASH
        or not _REQUIRED_RULE_IDS.issubset(rule_ids)
    ):
        raise _fail("reviewed strategy artifact does not match approved rules")


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("sector data contains an invalid record")
    return value.strip()


def _decimal(value: object, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise _fail("sector data contains an invalid record")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise _fail("sector data contains an invalid record") from None
    if not result.is_finite() or (positive and result <= 0):
        raise _fail("sector data contains an invalid record")
    return result


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        raise _fail("sector calculation produced an invalid number")
    return result


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise _fail("result could not be canonicalized") from None


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _datasets(bundle: DataBundle) -> dict[str, Any]:
    by_key = {dataset.dataset_key: dataset for dataset in bundle.datasets}
    if set(by_key) != {"sector-ranking", "sector-constituents"}:
        raise _fail("required sector datasets are missing or unexpected")
    return by_key


def _ranking_rows(dataset: Any, as_of: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for raw in dataset.records:
        try:
            group = raw["group"]
            if group not in _GROUPS:
                raise _fail("sector data contains an invalid record")
            bd_code = _text(raw["bd_code"])
            key = (group, bd_code)
            if key in seen:
                raise _fail("sector data contains a duplicate candidate")
            seen.add(key)
            record_as_of = raw.get("as_of", as_of)
            if record_as_of != as_of:
                raise _fail("sector data contains mixed dates")
            match = _ZGB.fullmatch(_text(raw["zgb"]))
            if match is None:
                raise _fail("sector data contains malformed zgb")
            limit_up_count, total_count = (int(item) for item in match.groups())
            if total_count <= 0 or limit_up_count > total_count:
                raise _fail("sector data contains malformed zgb")
            grouped.setdefault(group, []).append(
                {
                    "group": group,
                    "bd_code": bd_code,
                    "bd_name": _text(raw["bd_name"]),
                    "cje": _decimal(raw["cje"], positive=True),
                    "bd_zdf": _decimal(raw["bd_zdf"]),
                    "limit_up_count": limit_up_count,
                    "total_count": total_count,
                    "ratio": Decimal(limit_up_count) / Decimal(total_count),
                }
            )
        except KeyError:
            raise _fail("sector data contains an invalid record") from None
    if set(grouped) != _GROUPS:
        raise _fail("sector ranking data must contain every approved group")
    return grouped


def _constituents(
    dataset: Any, as_of: str, selected: Mapping[str, set[str]]
) -> dict[str, dict[str, object]]:
    rows_by_group: dict[str, list[dict[str, str]]] = {group: [] for group in selected}
    seen: set[tuple[str, str, str]] = set()
    for raw in dataset.records:
        try:
            group = raw["group"]
            bd_code = _text(raw["bd_code"])
            symbol = _text(raw["symbol"])
            name = _text(raw["name"])
            if group not in selected or bd_code not in selected[group]:
                raise _fail("constituent identity does not match emitted sectors")
            if raw.get("as_of", as_of) != as_of:
                raise _fail("constituent data contains mixed dates")
            identity = (group, bd_code, symbol)
            if identity in seen:
                raise _fail("constituent data contains a duplicate identity")
            seen.add(identity)
            rows_by_group[group].append(
                {
                    "symbol": symbol,
                    "name": name,
                    "bd_code": bd_code,
                    "group": group,
                    "as_of": as_of,
                }
            )
        except KeyError:
            raise _fail("constituent data contains an invalid record") from None

    result: dict[str, dict[str, object]] = {}
    for group, codes in selected.items():
        rows = sorted(
            rows_by_group[group],
            key=lambda row: (row["group"], row["bd_code"], row["symbol"]),
        )
        if {row["bd_code"] for row in rows} != codes:
            raise _fail("constituent data is missing for an emitted sector")
        result[group] = {"rows": rows, "sha256": _sha256(rows)}
    return result


def _normalize(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return Decimal("0.5") if low == high else (value - low) / (high - low)


def evaluate_sector_bundle(
    request: object,
    bundle: object,
    *,
    strategy_artifact: object = None,
) -> dict[str, object]:
    """Validate and deterministically evaluate one sector-selection bundle."""

    parsed_request, parsed_bundle = _parse_inputs(request, bundle)
    _validate_strategy(parsed_request, strategy_artifact)
    datasets = _datasets(parsed_bundle)
    as_of = parsed_request.as_of.isoformat()
    grouped = _ranking_rows(datasets["sector-ranking"], as_of)
    selected_rows = {
        group: sorted(rows, key=lambda row: (-row["cje"], row["bd_code"]))[:20]
        for group, rows in grouped.items()
    }
    selected_codes = {
        group: {row["bd_code"] for row in rows} for group, rows in selected_rows.items()
    }
    constituents = _constituents(datasets["sector-constituents"], as_of, selected_codes)

    rankings: list[dict[str, object]] = []
    for group in sorted(selected_rows):
        rows = selected_rows[group]
        ratio_min, ratio_max = min(row["ratio"] for row in rows), max(row["ratio"] for row in rows)
        cje_min, cje_max = min(row["cje"] for row in rows), max(row["cje"] for row in rows)
        zdf_min, zdf_max = min(row["bd_zdf"] for row in rows), max(row["bd_zdf"] for row in rows)
        scored = []
        for row in rows:
            score = (
                Decimal("0.40") * _normalize(row["ratio"], ratio_min, ratio_max)
                + Decimal("0.30") * _normalize(row["cje"], cje_min, cje_max)
                + Decimal("0.30") * _normalize(row["bd_zdf"], zdf_min, zdf_max)
            )
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["bd_code"]))
        for rank, (score, row) in enumerate(scored, 1):
            rankings.append(
                {
                    "group": group,
                    "rank": rank,
                    "bd_code": row["bd_code"],
                    "bd_name": row["bd_name"],
                    "cje_cny": _json_number(row["cje"]),
                    "bd_zdf_percent": _json_number(row["bd_zdf"]),
                    "limit_up_count": row["limit_up_count"],
                    "total_count": row["total_count"],
                    "limit_up_ratio": _json_number(row["ratio"]),
                    "exuberant_flag": row["ratio"] > Decimal("0.10"),
                    "score": _json_number(score),
                    "constituent_snapshot_sha256": constituents[group]["sha256"],
                }
            )

    content: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "SUCCEEDED",
        "strategy_key": STRATEGY_KEY,
        "strategy_version": STRATEGY_VERSION,
        "strategy_artifact_hash": STRATEGY_ARTIFACT_HASH,
        "request_id": parsed_request.request_id,
        "as_of": as_of,
        "groups": sorted(selected_rows),
        "rankings": rankings,
        "constituents": constituents,
    }
    stage_result_id = f"sector-stage-{_sha256(content)[:32]}"
    result = {**content, "stage_result_id": stage_result_id}
    result["stage_result_sha256"] = _sha256(result)
    return result


__all__ = ["SectorEvaluationError", "evaluate_sector_bundle"]
