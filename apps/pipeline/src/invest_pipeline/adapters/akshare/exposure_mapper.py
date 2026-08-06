"""AkShare CSIndex (Zhong Zheng) constituent-weight mapper.

Translates ``ak.index_stock_cons_weight_csindex()`` into the
``IndexProfile`` + ``IndexConstituentSnapshot`` evidence pair. Pandas-free;
raises ``ProviderDataContractError`` with ``provider_key="akshare"`` on any
contract deviation. ``industry`` is always ``None``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from invest_domain.exposure.models import (
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)

from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.errors import ProviderDataContractError

_PROVIDER_KEY = "akshare"
_OPERATION = "index_stock_cons_weight_csindex"
_DATASET_KEY = "index_stock_cons_weight_csindex"
_DATE_KEY, _INDEX_CODE_KEY, _INDEX_NAME_KEY, _STOCK_CODE_KEY, _WEIGHT_KEY = (
    "日期",
    "指数代码",
    "指数名称",
    "成分券代码",
    "权重",
)
_REQUIRED_KEYS: tuple[str, ...] = (
    _DATE_KEY,
    _INDEX_CODE_KEY,
    _INDEX_NAME_KEY,
    _STOCK_CODE_KEY,
    _WEIGHT_KEY,
)
_DATE_FORMATS: tuple[str, ...] = ("%Y%m%d", "%Y-%m-%d")


def _err(code: str, message: str) -> ProviderDataContractError:
    return ProviderDataContractError(code=code, message=message, provider_key=_PROVIDER_KEY)


def _validate_observed_at(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise _err(
            "INVALID_OBSERVED_AT", f"observed_at must be a datetime (got {type(value).__name__})"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise _err("NAIVE_OBSERVED_AT", "observed_at must be timezone-aware")
    return value


def _normalize_text(value: Any, *, row_index: int, field: str) -> str:
    if not isinstance(value, str):
        raise _err(
            "EMPTY_FIELD",
            f"row {row_index} {field} must be a non-empty string (got {type(value).__name__})",
        )
    stripped = value.strip()
    if not stripped:
        raise _err("EMPTY_FIELD", f"row {row_index} {field} must not be empty")
    return stripped


def _parse_date(value: Any, *, row_index: int, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise _err("INVALID_DATE", f"row {row_index} {field} must not be empty")
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise _err(
            "INVALID_DATE", f"row {row_index} {field}={value!r} is not YYYYMMDD or YYYY-MM-DD"
        )
    raise _err(
        "INVALID_DATE",
        f"row {row_index} {field} must be date/datetime/str (got {type(value).__name__})",
    )


def _normalize_code(value: Any, *, row_index: int, field: str) -> str:
    if isinstance(value, bool):
        raise _err("INVALID_CODE", f"row {row_index} {field} must not be bool")
    if isinstance(value, int):
        if value < 0 or value > 999_999:
            raise _err(
                "INVALID_CODE",
                f"row {row_index} {field}={value!r} integer code must lie in [0, 999999]",
            )
        return f"{value:06d}"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise _err("MISSING_REQUIRED_FIELD", f"row {row_index} {field} must not be empty")
        if not stripped.isdigit() or len(stripped) != 6:
            raise _err(
                "INVALID_CODE",
                f"row {row_index} {field}={value!r} must be a 6-digit numeric string",
            )
        return stripped
    raise _err(
        "INVALID_CODE",
        f"row {row_index} {field} must be a 6-digit string or non-negative int "
        f"(got {type(value).__name__})",
    )


def _normalize_weight(value: Any, *, row_index: int, field: str) -> Decimal:
    if isinstance(value, bool):
        raise _err("WEIGHT_IS_BOOL", f"row {row_index} {field} must not be bool")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _err("NON_FINITE_WEIGHT", f"row {row_index} {field}={value!r} must be finite")
        decimal_value = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise _err("INVALID_WEIGHT", f"row {row_index} {field} must not be empty")
        try:
            decimal_value = Decimal(text)
        except InvalidOperation as exc:
            raise _err(
                "INVALID_WEIGHT", f"row {row_index} {field}={value!r} is not a valid numeric weight"
            ) from exc
    else:
        raise _err(
            "INVALID_WEIGHT",
            f"row {row_index} {field} must be Decimal/int/float/str (got {type(value).__name__})",
        )
    if not decimal_value.is_finite():
        raise _err("NON_FINITE_WEIGHT", f"row {row_index} {field}={value!r} must be finite")
    if decimal_value < Decimal("0") or decimal_value > Decimal("100"):
        raise _err("WEIGHT_OUT_OF_RANGE", f"row {row_index} {field}={value!r} must lie in [0, 100]")
    return decimal_value / Decimal("100")


@dataclass(frozen=True, slots=True)
class CsindexExposureMapping:
    """Mapping result: profile + snapshot share one provenance."""

    profile: IndexProfile
    constituent_snapshot: IndexConstituentSnapshot


def map_csindex_constituent_weights(
    response: AkshareResponse,
    *,
    observed_at: datetime,
    source_batch_id: UUID | None = None,
    revision: int = 1,
    confidence: Decimal = Decimal("1"),
    id_factory: Callable[[], UUID] = uuid4,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CsindexExposureMapping:
    """Map an ``index_stock_cons_weight_csindex`` payload to domain evidence."""
    observed_at = _validate_observed_at(observed_at)
    if not isinstance(response, AkshareResponse):
        raise _err(
            "MALFORMED_CSINDEX_ROW",
            f"response must be an AkshareResponse (got {type(response).__name__})",
        )
    if response.operation != _OPERATION:
        raise _err(
            "WRONG_OPERATION",
            f"response.operation must be {_OPERATION!r} (got {response.operation!r})",
        )

    payload = response.raw_payload
    if isinstance(payload, (str, bytes)) or not isinstance(payload, (list, tuple)):
        raise _err(
            "MALFORMED_CSINDEX_ROW",
            f"raw_payload must be a list/tuple of dict rows (got {type(payload).__name__})",
        )
    if len(payload) == 0:
        raise _err("EMPTY_PAYLOAD", "raw_payload must contain at least one constituent row")

    constituents: list[IndexConstituent] = []
    seen_codes: set[str] = set()
    canonical_date: date | None = None
    canonical_index_code: str | None = None
    canonical_index_name: str | None = None

    for row_index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise _err(
                "MALFORMED_CSINDEX_ROW",
                f"row {row_index} must be a dict (got {type(row).__name__})",
            )
        missing = [key for key in _REQUIRED_KEYS if key not in row]
        if missing:
            raise _err(
                "MISSING_REQUIRED_FIELD", f"row {row_index} missing required keys: {missing}"
            )
        row_date = _parse_date(row[_DATE_KEY], row_index=row_index, field=_DATE_KEY)
        row_index_code = _normalize_code(
            row[_INDEX_CODE_KEY], row_index=row_index, field=_INDEX_CODE_KEY
        )
        row_index_name = _normalize_text(
            row[_INDEX_NAME_KEY], row_index=row_index, field=_INDEX_NAME_KEY
        )
        stock_code = _normalize_code(
            row[_STOCK_CODE_KEY], row_index=row_index, field=_STOCK_CODE_KEY
        )
        weight = _normalize_weight(row[_WEIGHT_KEY], row_index=row_index, field=_WEIGHT_KEY)
        if canonical_date is None:
            canonical_date, canonical_index_code, canonical_index_name = (
                row_date,
                row_index_code,
                row_index_name,
            )
        elif (row_date, row_index_code, row_index_name) != (
            canonical_date,
            canonical_index_code,
            canonical_index_name,
        ):
            raise _err("INCONSISTENT_SOURCE", f"row {row_index} identity does not match header")
        if stock_code in seen_codes:
            raise _err(
                "DUPLICATE_CONSTITUENT",
                f"row {row_index} {_STOCK_CODE_KEY}={stock_code!r} is duplicated in payload",
            )
        seen_codes.add(stock_code)
        try:
            constituent = IndexConstituent(stock_code=stock_code, weight=weight, industry=None)
        except (TypeError, ValueError) as exc:
            raise _err(
                "construction_failed", f"row {row_index} failed to build IndexConstituent: {exc}"
            ) from exc
        constituents.append(constituent)

    assert (
        canonical_date is not None
        and canonical_index_code is not None
        and canonical_index_name is not None
    )

    try:
        provenance = ExposureProvenance(
            provider_key=_PROVIDER_KEY,
            dataset_key=_DATASET_KEY,
            observed_at=observed_at,
            source_batch_id=source_batch_id,
            revision=revision,
            confidence=confidence,
        )
    except (TypeError, ValueError) as exc:
        raise _err("provenance_invalid", f"invalid provenance arguments: {exc}") from exc
    try:
        profile = IndexProfile(
            index_code=canonical_index_code,
            index_name=canonical_index_name,
            provenance=provenance,
            category=None,
            as_of_date=canonical_date,
        )
    except (TypeError, ValueError) as exc:
        raise _err("construction_failed", f"failed to build IndexProfile: {exc}") from exc
    try:
        snapshot = IndexConstituentSnapshot.create(
            index_code=canonical_index_code,
            as_of_date=canonical_date,
            observed_at=observed_at,
            constituents=constituents,
            provenance=provenance,
            id_factory=id_factory,
            now_factory=now_factory,
        )
    except (TypeError, ValueError) as exc:
        raise _err(
            "construction_failed", f"failed to build IndexConstituentSnapshot: {exc}"
        ) from exc
    return CsindexExposureMapping(profile=profile, constituent_snapshot=snapshot)


__all__ = ["CsindexExposureMapping", "map_csindex_constituent_weights"]
