"""AkShare reported ETF holdings mapper (DC-3).

Maps periodic ``fund_portfolio_hold_em`` rows—not real-time/full PCF—to
an :class:`invest_domain.exposure.EtfHoldingSnapshot`.

- ``股票代码`` — six-digit numeric code (string or non-negative int).
- ``占净值比例`` — percentage weight in ``[0, 100]``; the mapper
  divides by 100 so the domain stores the canonical ratio form.
- ``季度`` — trimmed ``YYYY年{1,2,3,4}季度`` label; parsed to the
  natural quarter-end date (``YYYY-03-31`` / ``-06-30`` / ``-09-30`` /
  ``-12-31``) which becomes ``EtfHoldingSnapshot.as_of_date``.

Rows in older quarters are silently dropped — only the latest quarter
present in the response survives. Same-stock duplicates inside the
latest quarter fail closed with ``DUPLICATE_HOLDING``; the same stock
in older quarters is fine because the older rows are filtered out
before the duplicate check runs. Pandas-free; raises
:class:`ProviderDataContractError` (``provider_key="akshare"``) on any
contract deviation. ``industry`` is always ``None``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from invest_domain.exposure.models import (
    EtfHolding,
    EtfHoldingSnapshot,
    ExposureProvenance,
)

from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.errors import ProviderDataContractError

_PROVIDER_KEY = "akshare"
_OPERATION = "fund_portfolio_hold_em"
_DATASET_KEY = "fund_portfolio_hold_em:reported_portfolio_holdings"
_CODE_KEY = "股票代码"
_WEIGHT_KEY = "占净值比例"
_QUARTER_KEY = "季度"

_QUARTER_END_DAY: dict[int, int] = {1: 31, 2: 30, 3: 30, 4: 31}
_QUARTER_END_MONTH: dict[int, int] = {1: 3, 2: 6, 3: 9, 4: 12}
_QUARTER_PATTERN = re.compile(r"^([0-9]{4})年([1-4])季度$")
_UUID_INT_ZERO = 0


def _err(code: str, message: str) -> ProviderDataContractError:
    return ProviderDataContractError(code=code, message=message, provider_key=_PROVIDER_KEY)


def _validate_observed_at(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise _err(
            "INVALID_OBSERVED_AT",
            f"observed_at must be a datetime (got {type(value).__name__})",
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise _err("NAIVE_OBSERVED_AT", "observed_at must be timezone-aware")
    return value


def _validate_etf_id(value: Any) -> UUID:
    if not isinstance(value, UUID):
        raise _err(
            "INVALID_ETF_ID",
            f"etf_id must be a UUID (got {type(value).__name__})",
        )
    if value.int == _UUID_INT_ZERO:
        raise _err("INVALID_ETF_ID", "etf_id must not be the all-zero UUID")
    return value


def _parse_quarter(value: Any, *, row_index: int) -> date:
    if not isinstance(value, str):
        raise _err(
            "INVALID_QUARTER",
            f"row {row_index} 季度 must be a non-empty string (got {type(value).__name__})",
        )
    text = value.strip()
    if not text:
        raise _err("INVALID_QUARTER", f"row {row_index} 季度 must not be empty")
    match = _QUARTER_PATTERN.match(text)
    if match is None:
        raise _err(
            "INVALID_QUARTER",
            f"row {row_index} 季度={value!r} is not the trimmed Chinese form 'YYYY年[1-4]季度'",
        )
    year = int(match.group(1))
    quarter = int(match.group(2))
    try:
        return date(year, _QUARTER_END_MONTH[quarter], _QUARTER_END_DAY[quarter])
    except ValueError as exc:
        raise _err("INVALID_QUARTER", f"row {row_index} 季度 has an invalid year") from exc


def _normalize_code(value: Any, *, row_index: int) -> str:
    if isinstance(value, bool):
        raise _err("INVALID_CODE", f"row {row_index} 股票代码 must not be bool")
    if isinstance(value, int):
        if value < 0 or value > 999_999:
            raise _err(
                "INVALID_CODE",
                f"row {row_index} 股票代码={value!r} integer code must lie in [0, 999999]",
            )
        return f"{value:06d}"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise _err("INVALID_CODE", f"row {row_index} 股票代码 must not be empty")
        if not text.isdigit() or len(text) != 6:
            raise _err(
                "INVALID_CODE",
                f"row {row_index} 股票代码={value!r} must be a 6-digit numeric string",
            )
        return text
    raise _err(
        "INVALID_CODE",
        f"row {row_index} 股票代码 must be a 6-digit string or non-negative int "
        f"(got {type(value).__name__})",
    )


def _normalize_weight(value: Any, *, row_index: int) -> Decimal:
    if isinstance(value, bool):
        raise _err("WEIGHT_IS_BOOL", f"row {row_index} 占净值比例 must not be bool")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _err(
                "NON_FINITE_WEIGHT",
                f"row {row_index} 占净值比例={value!r} must be finite",
            )
        decimal_value = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise _err(
                "INVALID_WEIGHT",
                f"row {row_index} 占净值比例 must not be empty",
            )
        try:
            decimal_value = Decimal(text)
        except InvalidOperation as exc:
            raise _err(
                "INVALID_WEIGHT",
                f"row {row_index} 占净值比例={value!r} is not a valid numeric weight",
            ) from exc
    else:
        raise _err(
            "INVALID_WEIGHT",
            f"row {row_index} 占净值比例 must be Decimal/int/float/str "
            f"(got {type(value).__name__})",
        )
    if not decimal_value.is_finite():
        raise _err(
            "NON_FINITE_WEIGHT",
            f"row {row_index} 占净值比例={value!r} must be finite",
        )
    if decimal_value < Decimal("0") or decimal_value > Decimal("100"):
        raise _err(
            "WEIGHT_OUT_OF_RANGE",
            f"row {row_index} 占净值比例={value!r} must lie in [0, 100]",
        )
    return decimal_value / Decimal("100")


def map_reported_etf_holdings(
    response: AkshareResponse,
    *,
    etf_id: UUID,
    observed_at: datetime,
    source_batch_id: UUID | None = None,
    revision: int = 1,
    confidence: Decimal = Decimal("1"),
    id_factory: Callable[[], UUID] = uuid4,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EtfHoldingSnapshot:
    """Map a ``fund_portfolio_hold_em`` payload to ``EtfHoldingSnapshot``."""
    observed_at = _validate_observed_at(observed_at)
    etf_id = _validate_etf_id(etf_id)
    if not isinstance(response, AkshareResponse):
        raise _err(
            "MALFORMED_HOLDINGS_ROW",
            f"response must be an AkshareResponse (got {type(response).__name__})",
        )
    if response.operation != _OPERATION:
        raise _err(
            "WRONG_OPERATION",
            f"response.operation must be {_OPERATION!r} (got {response.operation!r})",
        )

    payload = response.raw_payload
    if not isinstance(payload, list):
        raise _err(
            "MALFORMED_HOLDINGS_ROW",
            f"raw_payload must be a list of dict rows (got {type(payload).__name__})",
        )
    if len(payload) == 0:
        raise _err("EMPTY_PAYLOAD", "raw_payload must contain at least one holding row")

    parsed_rows: list[tuple[str, Decimal, date]] = []
    for row_index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise _err(
                "MALFORMED_HOLDINGS_ROW",
                f"row {row_index} must be a dict (got {type(row).__name__})",
            )
        missing = [key for key in (_CODE_KEY, _WEIGHT_KEY, _QUARTER_KEY) if key not in row]
        if missing:
            raise _err(
                "MISSING_REQUIRED_FIELD",
                f"row {row_index} missing required keys: {missing}",
            )
        stock_code = _normalize_code(row[_CODE_KEY], row_index=row_index)
        weight = _normalize_weight(row[_WEIGHT_KEY], row_index=row_index)
        quarter_date = _parse_quarter(row[_QUARTER_KEY], row_index=row_index)
        parsed_rows.append((stock_code, weight, quarter_date))

    as_of_date = max(row[2] for row in parsed_rows)
    latest_rows = [row for row in parsed_rows if row[2] == as_of_date]

    seen_codes: set[str] = set()
    holdings: list[EtfHolding] = []
    for stock_code, weight, _ in latest_rows:
        if stock_code in seen_codes:
            raise _err(
                "DUPLICATE_HOLDING",
                f"latest-quarter stock_code={stock_code!r} appears in multiple rows",
            )
        seen_codes.add(stock_code)
        holdings.append(EtfHolding(stock_code=stock_code, weight=weight, industry=None))

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
        raise _err("PROVENANCE_INVALID", f"invalid provenance arguments: {exc}") from exc
    try:
        return EtfHoldingSnapshot.create(
            etf_id=etf_id,
            as_of_date=as_of_date,
            observed_at=observed_at,
            holdings=holdings,
            provenance=provenance,
            id_factory=id_factory,
            now_factory=now_factory,
        )
    except (TypeError, ValueError) as exc:
        raise _err(
            "CONSTRUCTION_FAILED",
            f"failed to build EtfHoldingSnapshot: {exc}",
        ) from exc


__all__ = ["map_reported_etf_holdings"]
