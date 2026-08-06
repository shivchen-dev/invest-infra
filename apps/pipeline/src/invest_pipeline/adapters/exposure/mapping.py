"""Pure mapping from a standardized AKShare exposure payload to domain objects.

This module is the single source of truth for turning a JSON-shaped
``AKShareExposureStandardizedPayload`` (a flat dict with the four
sections plus the provenance envelope) into the four pure domain value
objects from :mod:`invest_domain.exposure`:

- :func:`map_index_profile` -> :class:`IndexProfile`
- :func:`map_index_constituent_snapshot` -> :class:`IndexConstituentSnapshot`
- :func:`map_etf_index_mapping` -> :class:`EtfIndexMapping`
- :func:`map_etf_holding_snapshot` -> :class:`EtfHoldingSnapshot`
- :func:`map_standardized_payload` -> the four mapped domain objects

The module is deliberately pure: no I/O, no clock access, no
environment access, no network. JSON loading is handled by
:func:`load_payload`; runtime clock / ID factories are injected via
keyword arguments on the snapshot factories so unit tests can pin the
deterministic UUIDs and timestamps used in DC-3A. Decimal weights are
normalised via :func:`_coerce_decimal` so a fixture carrying a JSON
``"0.10"`` string or a Python ``int`` reaches the domain layer as a
finite ``Decimal`` in ``[0, 1]``.

Each ``map_*`` function accepts either the standardized ``payload``
alone, in which case it builds the shared
:class:`ExposureProvenance` from the payload's provenance envelope,
or ``(payload, provenance)`` for callers that have already built the
provenance (e.g. when several sections share a single instance). The
explicit-provenance form is preserved for callers that depend on it.

The slice intentionally never imports the optional ``akshare`` SDK
(matrix §10 / DC-3B "no akshare dep") and never touches the network
(matrix §6). The AKShare adapter in
:mod:`invest_pipeline.adapters.exposure.akshare_adapter` re-uses these
pure helpers and gates the real call behind an explicit
``AKShareExposureConfig.enabled`` flag.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from invest_domain.exposure import (
    EtfHolding,
    EtfHoldingSnapshot,
    EtfIndexMapping,
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)

_PROVIDER_KEY_FIELD = "provider_key"
_DATASET_KEY_FIELD = "dataset_key"
_OBSERVED_AT_FIELD = "observed_at"
_REVISION_FIELD = "revision"
_CONFIDENCE_FIELD = "confidence"
_INDEX_PROFILE_SECTION = "index_profile"
_INDEX_CONSTITUENTS_SECTION = "index_constituents"
_ETF_INDEX_MAPPING_SECTION = "etf_index_mapping"
_ETF_HOLDINGS_SECTION = "etf_holdings"

_REQUIRED_TOP_KEYS: frozenset[str] = frozenset(
    {
        _PROVIDER_KEY_FIELD,
        _DATASET_KEY_FIELD,
        _OBSERVED_AT_FIELD,
        _INDEX_PROFILE_SECTION,
        _INDEX_CONSTITUENTS_SECTION,
        _ETF_INDEX_MAPPING_SECTION,
        _ETF_HOLDINGS_SECTION,
    }
)


class AKShareExposureMappingError(ValueError):
    """Raised when a standardized payload violates the DC-3B mapping contract.

    Surfaces a single, machine-readable category (``code``) and a
    human-readable message so the AKShare adapter can route alerts
    through the canonical :class:`invest_pipeline.adapters.errors.
    ProviderDataContractError` without re-parsing free text. The
    constructor matches the domain error contract: ``code`` is required
    while ``field`` is optional so the same exception can carry either
    a top-level ("missing_required_top_keys") or nested
    ("etf_holdings.holdings[2].weight") diagnostic.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
    ) -> None:
        combined = f"[{code}] {message}" if code else message
        super().__init__(combined)
        self.code = code
        self.message = message
        self.field = field


AKShareExposureStandardizedPayload = dict
"""Runtime alias for the standardized payload mapping produced by
:func:`map_standardized_payload`.

The alias points at the built-in :class:`dict` so callers can keep
using ``isinstance(payload, AKShareExposureStandardizedPayload)``
against the four-key ``dict`` returned by the mapping layer.
"""


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise AKShareExposureMappingError(
            "missing_required_top_key",
            f"missing required key: {key!r}",
            field=key,
        )
    return mapping[key]


def _coerce_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise AKShareExposureMappingError(
            "field_not_string",
            f"{field!r} must be a str, got {type(value).__name__}",
            field=field,
        )
    text = value.strip()
    if not text:
        raise AKShareExposureMappingError(
            "empty_text",
            f"{field!r} must not be empty",
            field=field,
        )
    return text


def _coerce_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise AKShareExposureMappingError(
            "weight_is_bool",
            f"{field!r} must not be a bool",
            field=field,
        )
    if isinstance(value, Decimal):
        decimal = value
    else:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise AKShareExposureMappingError(
                "invalid_decimal",
                f"{field!r} is not a valid decimal: {value!r}",
                field=field,
            ) from exc
    if not decimal.is_finite():
        raise AKShareExposureMappingError(
            "non_finite_decimal",
            f"{field!r} must be finite",
            field=field,
        )
    if not Decimal("0") <= decimal <= Decimal("1"):
        raise AKShareExposureMappingError(
            "weight_out_of_range",
            f"{field!r} must be in [0, 1]",
            field=field,
        )
    return decimal


def _coerce_optional_decimal(value: Any, field: str) -> Decimal:
    if value is None:
        return Decimal("1")
    return _coerce_decimal(value, field)


def _coerce_date(value: Any, field: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise AKShareExposureMappingError(
            "invalid_date",
            f"{field!r} must be an ISO date string or date, got {type(value).__name__}",
            field=field,
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AKShareExposureMappingError(
            "invalid_date",
            f"{field!r} is not a valid ISO date: {value!r}",
            field=field,
        ) from exc


def _coerce_observed_at(value: Any, field: str = _OBSERVED_AT_FIELD) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise AKShareExposureMappingError(
                "naive_datetime",
                f"{field!r} must be timezone-aware",
                field=field,
            )
        return value.astimezone(UTC)
    if not isinstance(value, str):
        raise AKShareExposureMappingError(
            "invalid_observed_at",
            f"{field!r} must be an ISO-8601 string or datetime, got {type(value).__name__}",
            field=field,
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AKShareExposureMappingError(
            "invalid_observed_at",
            f"{field!r} is not ISO-8601: {value!r}",
            field=field,
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AKShareExposureMappingError(
            "naive_datetime",
            f"{field!r} must be timezone-aware",
            field=field,
        )
    return parsed.astimezone(UTC)


def _coerce_uuid(value: Any, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise AKShareExposureMappingError(
            "invalid_uuid",
            f"{field!r} must be a UUID string, got {type(value).__name__}",
            field=field,
        )
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise AKShareExposureMappingError(
            "invalid_uuid",
            f"{field!r} is not a valid UUID: {value!r}",
            field=field,
        ) from exc


def _coerce_optional_revision(value: Any, field: str) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise AKShareExposureMappingError(
            "invalid_revision",
            f"{field!r} must be an int, got {type(value).__name__}",
            field=field,
        )
    if value < 1:
        raise AKShareExposureMappingError(
            "invalid_revision",
            f"{field!r} must be >= 1, got {value!r}",
            field=field,
        )
    return value


def _coerce_constituent(item: Any, index: int, section: str) -> IndexConstituent:
    field_prefix = f"{section}[{index}]"
    if not isinstance(item, Mapping):
        raise AKShareExposureMappingError(
            "entry_not_mapping",
            f"{field_prefix} must be a mapping",
            field=field_prefix,
        )
    stock_code = _coerce_text(
        _require(item, "stock_code"),
        f"{field_prefix}.stock_code",
    )
    weight = _coerce_decimal(
        _require(item, "weight"),
        f"{field_prefix}.weight",
    )
    industry_raw = item.get("industry")
    industry: str | None
    if industry_raw is None:
        industry = None
    elif isinstance(industry_raw, str):
        industry = _coerce_text(industry_raw, f"{field_prefix}.industry")
    else:
        raise AKShareExposureMappingError(
            "industry_not_string",
            f"{field_prefix}.industry must be a string or null",
            field=f"{field_prefix}.industry",
        )
    return IndexConstituent(stock_code=stock_code, weight=weight, industry=industry)


def _coerce_holding(item: Any, index: int, section: str) -> EtfHolding:
    field_prefix = f"{section}[{index}]"
    if not isinstance(item, Mapping):
        raise AKShareExposureMappingError(
            "entry_not_mapping",
            f"{field_prefix} must be a mapping",
            field=field_prefix,
        )
    stock_code = _coerce_text(
        _require(item, "stock_code"),
        f"{field_prefix}.stock_code",
    )
    weight = _coerce_decimal(
        _require(item, "weight"),
        f"{field_prefix}.weight",
    )
    industry_raw = item.get("industry")
    industry: str | None
    if industry_raw is None:
        industry = None
    elif isinstance(industry_raw, str):
        industry = _coerce_text(industry_raw, f"{field_prefix}.industry")
    else:
        raise AKShareExposureMappingError(
            "industry_not_string",
            f"{field_prefix}.industry must be a string or null",
            field=f"{field_prefix}.industry",
        )
    return EtfHolding(stock_code=stock_code, weight=weight, industry=industry)


def _build_provenance(payload: Mapping[str, Any]) -> ExposureProvenance:
    """Build the shared :class:`ExposureProvenance` from the top-level envelope."""

    provider_key = _coerce_text(_require(payload, _PROVIDER_KEY_FIELD), _PROVIDER_KEY_FIELD)
    dataset_key = _coerce_text(_require(payload, _DATASET_KEY_FIELD), _DATASET_KEY_FIELD)
    observed_at = _coerce_observed_at(_require(payload, _OBSERVED_AT_FIELD))
    revision = _coerce_optional_revision(payload.get(_REVISION_FIELD), _REVISION_FIELD)
    confidence = _coerce_optional_decimal(payload.get(_CONFIDENCE_FIELD), _CONFIDENCE_FIELD)
    source_batch_raw = payload.get("source_batch_id")
    source_batch_id = (
        _coerce_uuid(source_batch_raw, "source_batch_id") if source_batch_raw is not None else None
    )
    return ExposureProvenance(
        provider_key=provider_key,
        dataset_key=dataset_key,
        observed_at=observed_at,
        source_batch_id=source_batch_id,
        revision=revision,
        confidence=confidence,
    )


def _resolve_provenance(
    payload: Mapping[str, Any],
    provenance: ExposureProvenance | None,
) -> ExposureProvenance:
    """Return the shared provenance record.

    Callers may either supply a pre-built :class:`ExposureProvenance`
    (the legacy ``(payload, provenance)`` form) or omit it and have the
    helper build one from the payload's provenance envelope. The
    An explicit ``None`` is treated the same as an omitted argument.
    """

    if provenance is None:
        return _build_provenance(payload)
    if not isinstance(provenance, ExposureProvenance):
        raise AKShareExposureMappingError(
            "invalid_provenance",
            "provenance must be an ExposureProvenance or omitted",
            field="provenance",
        )
    return provenance


def map_index_profile(
    payload: Mapping[str, Any],
    provenance: ExposureProvenance | None = None,
) -> IndexProfile:
    """Return an :class:`IndexProfile` from the ``index_profile`` section.

    The ``provenance`` argument is optional: when omitted, the
    function rebuilds the shared :class:`ExposureProvenance` from the
    payload envelope. Pass an explicit ``provenance`` to share a
    pre-built instance across the four ``map_*`` functions.

    The ``as_of_date`` field is optional (DC-3A keeps it nullable on the
    domain model); the ``category`` field is optional too. Both go
    through the standard text / date coercion rules.
    """

    prov = _resolve_provenance(payload, provenance)
    section = _require(payload, _INDEX_PROFILE_SECTION)
    if not isinstance(section, Mapping):
        raise AKShareExposureMappingError(
            "section_not_mapping",
            f"{_INDEX_PROFILE_SECTION!r} must be a mapping",
            field=_INDEX_PROFILE_SECTION,
        )
    index_code = _coerce_text(
        _require(section, "index_code"),
        f"{_INDEX_PROFILE_SECTION}.index_code",
    )
    index_name = _coerce_text(
        _require(section, "index_name"),
        f"{_INDEX_PROFILE_SECTION}.index_name",
    )
    category_raw = section.get("category")
    category: str | None
    if category_raw is None:
        category = None
    elif isinstance(category_raw, str):
        category = _coerce_text(category_raw, f"{_INDEX_PROFILE_SECTION}.category")
    else:
        raise AKShareExposureMappingError(
            "category_not_string",
            f"{_INDEX_PROFILE_SECTION}.category must be a string or null",
            field=f"{_INDEX_PROFILE_SECTION}.category",
        )
    as_of_date: date | None = None
    if section.get("as_of_date") is not None:
        as_of_date = _coerce_date(section["as_of_date"], f"{_INDEX_PROFILE_SECTION}.as_of_date")
    return IndexProfile(
        index_code=index_code,
        index_name=index_name,
        category=category,
        provenance=prov,
        as_of_date=as_of_date,
    )


def map_index_constituent_snapshot(
    payload: Mapping[str, Any],
    provenance: ExposureProvenance | None = None,
    *,
    id_factory: Callable[[], UUID] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> IndexConstituentSnapshot:
    """Return an :class:`IndexConstituentSnapshot` from the payload section.

    ``provenance`` may be omitted (the helper builds it from the
    payload), or supplied explicitly to share a pre-built instance.
    ``id_factory`` and ``now_factory`` are passed through to the
    domain factory so tests can pin the snapshot UUID and
    ``created_at`` timestamp without monkey-patching :func:`uuid.uuid4`
    or :func:`datetime.now`.
    """

    prov = _resolve_provenance(payload, provenance)
    section = _require(payload, _INDEX_CONSTITUENTS_SECTION)
    if not isinstance(section, Mapping):
        raise AKShareExposureMappingError(
            "section_not_mapping",
            f"{_INDEX_CONSTITUENTS_SECTION!r} must be a mapping",
            field=_INDEX_CONSTITUENTS_SECTION,
        )
    raw_items = _require(section, "constituents")
    if not isinstance(raw_items, list) or not raw_items:
        raise AKShareExposureMappingError(
            "empty_or_invalid_list",
            f"{_INDEX_CONSTITUENTS_SECTION}.constituents must be a non-empty list",
            field=f"{_INDEX_CONSTITUENTS_SECTION}.constituents",
        )
    constituents = tuple(
        _coerce_constituent(item, index, f"{_INDEX_CONSTITUENTS_SECTION}.constituents")
        for index, item in enumerate(raw_items)
    )
    kwargs: dict[str, Any] = {
        "index_code": _coerce_text(
            _require(section, "index_code"),
            f"{_INDEX_CONSTITUENTS_SECTION}.index_code",
        ),
        "as_of_date": _coerce_date(
            _require(section, "as_of_date"),
            f"{_INDEX_CONSTITUENTS_SECTION}.as_of_date",
        ),
        "observed_at": prov.observed_at,
        "constituents": constituents,
        "provenance": prov,
    }
    if id_factory is not None:
        kwargs["id_factory"] = id_factory
    elif "id_factory" not in kwargs:
        kwargs["id_factory"] = uuid4
    if now_factory is not None:
        kwargs["now_factory"] = now_factory
    return IndexConstituentSnapshot.create(**kwargs)


def map_etf_index_mapping(
    payload: Mapping[str, Any],
    provenance: ExposureProvenance | None = None,
) -> EtfIndexMapping:
    """Return an :class:`EtfIndexMapping` from the payload section.

    ``provenance`` may be omitted (the helper builds it from the
    payload) or supplied explicitly to share a pre-built instance.
    ``effective_to`` is optional (a still-in-effect mapping has
    ``effective_to=None``); ``effective_from`` and the two UUIDs are
    mandatory.
    """

    prov = _resolve_provenance(payload, provenance)
    section = _require(payload, _ETF_INDEX_MAPPING_SECTION)
    if not isinstance(section, Mapping):
        raise AKShareExposureMappingError(
            "section_not_mapping",
            f"{_ETF_INDEX_MAPPING_SECTION!r} must be a mapping",
            field=_ETF_INDEX_MAPPING_SECTION,
        )
    etf_id = _coerce_uuid(
        _require(section, "etf_id"),
        f"{_ETF_INDEX_MAPPING_SECTION}.etf_id",
    )
    index_id = _coerce_uuid(
        _require(section, "index_id"),
        f"{_ETF_INDEX_MAPPING_SECTION}.index_id",
    )
    effective_from = _coerce_date(
        _require(section, "effective_from"),
        f"{_ETF_INDEX_MAPPING_SECTION}.effective_from",
    )
    raw_to = section.get("effective_to")
    effective_to: date | None = None
    if raw_to is not None:
        effective_to = _coerce_date(raw_to, f"{_ETF_INDEX_MAPPING_SECTION}.effective_to")
    return EtfIndexMapping(
        etf_id=etf_id,
        index_id=index_id,
        effective_from=effective_from,
        effective_to=effective_to,
        observed_at=prov.observed_at,
        provenance=prov,
    )


def map_etf_holding_snapshot(
    payload: Mapping[str, Any],
    provenance: ExposureProvenance | None = None,
    *,
    id_factory: Callable[[], UUID] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> EtfHoldingSnapshot:
    """Return an :class:`EtfHoldingSnapshot` from the payload section.

    ``provenance`` may be omitted (the helper builds it from the
    payload) or supplied explicitly to share a pre-built instance.
    """

    prov = _resolve_provenance(payload, provenance)
    section = _require(payload, _ETF_HOLDINGS_SECTION)
    if not isinstance(section, Mapping):
        raise AKShareExposureMappingError(
            "section_not_mapping",
            f"{_ETF_HOLDINGS_SECTION!r} must be a mapping",
            field=_ETF_HOLDINGS_SECTION,
        )
    raw_items = _require(section, "holdings")
    if not isinstance(raw_items, list) or not raw_items:
        raise AKShareExposureMappingError(
            "empty_or_invalid_list",
            f"{_ETF_HOLDINGS_SECTION}.holdings must be a non-empty list",
            field=f"{_ETF_HOLDINGS_SECTION}.holdings",
        )
    holdings = tuple(
        _coerce_holding(item, index, f"{_ETF_HOLDINGS_SECTION}.holdings")
        for index, item in enumerate(raw_items)
    )
    kwargs: dict[str, Any] = {
        "etf_id": _coerce_uuid(
            _require(section, "etf_id"),
            f"{_ETF_HOLDINGS_SECTION}.etf_id",
        ),
        "as_of_date": _coerce_date(
            _require(section, "as_of_date"),
            f"{_ETF_HOLDINGS_SECTION}.as_of_date",
        ),
        "observed_at": prov.observed_at,
        "holdings": holdings,
        "provenance": prov,
    }
    if id_factory is not None:
        kwargs["id_factory"] = id_factory
    elif "id_factory" not in kwargs:
        kwargs["id_factory"] = uuid4
    if now_factory is not None:
        kwargs["now_factory"] = now_factory
    return EtfHoldingSnapshot.create(**kwargs)


def map_standardized_payload(
    payload: Mapping[str, Any],
    *,
    id_factory: Callable[[], UUID] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> AKShareExposureStandardizedPayload:
    """Return the four mapped domain objects keyed by section name.

    Single entry point used by both the fixture adapter and the
    AKShare adapter. The returned dict carries exactly the four
    DC-3B domain objects under their section keys
    (``index_profile``, ``index_constituents``, ``etf_index_mapping``,
    ``etf_holdings``) so callers can iterate without depending on the
    provenance record. The full standardized bundle validation runs
    first; payloads missing any of the four sections raise
    :class:`AKShareExposureMappingError`.
    """

    missing = _REQUIRED_TOP_KEYS - payload.keys()
    if missing:
        raise AKShareExposureMappingError(
            "missing_required_top_keys",
            f"missing required top-level keys: {sorted(missing)}",
            field=",".join(sorted(missing)),
        )
    provenance = _build_provenance(payload)
    result: dict[str, Any] = {
        _INDEX_PROFILE_SECTION: map_index_profile(payload, provenance),
        _INDEX_CONSTITUENTS_SECTION: map_index_constituent_snapshot(
            payload,
            provenance,
            id_factory=id_factory,
            now_factory=now_factory,
        ),
        _ETF_INDEX_MAPPING_SECTION: map_etf_index_mapping(payload, provenance),
        _ETF_HOLDINGS_SECTION: map_etf_holding_snapshot(
            payload,
            provenance,
            id_factory=id_factory,
            now_factory=now_factory,
        ),
    }
    return AKShareExposureStandardizedPayload(**result)


def load_payload(path: str | Path) -> dict[str, Any]:
    """Load a JSON payload from a filesystem path.

    Accepts any JSON object root; the mapping layer enforces the
    DC-3B top-level keys. The loader never imports the optional
    ``akshare`` SDK and never reaches the network.
    """

    file_path = Path(path)
    if not file_path.exists():
        raise AKShareExposureMappingError(
            "fixture_not_found",
            f"exposure payload file not found: {file_path}",
            field=str(file_path),
        )
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AKShareExposureMappingError(
            "invalid_json",
            f"invalid JSON in {file_path}: {exc}",
            field=str(file_path),
        ) from exc
    if not isinstance(data, dict):
        raise AKShareExposureMappingError(
            "invalid_root",
            "payload root must be a JSON object",
            field=str(file_path),
        )
    return data


__all__ = [
    "AKShareExposureMappingError",
    "AKShareExposureStandardizedPayload",
    "load_payload",
    "map_etf_holding_snapshot",
    "map_etf_index_mapping",
    "map_index_constituent_snapshot",
    "map_index_profile",
    "map_standardized_payload",
]
