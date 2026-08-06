"""JSON / row codec for ``analytics.research_evidence_packs`` (Phase 2B).

This module owns the bidirectional conversion between the domain
:class:`invest_domain.research.models.EvidencePack` and the
:class:`invest_storage.models.ResearchEvidencePackRow` SQLAlchemy row
that persists it.

Scope:

- :func:`coerce_optional_uuid` — turn a permissive ``case_id`` value
  into a real :class:`UUID` or ``None`` and reject malformed values
  before they reach the ``research_case_id`` FK column.
- :func:`evidence_pack_to_payload` — build the canonical JSON-safe
  payload for the JSONB column.
- :func:`row_to_evidence_pack` — reconstruct the domain
  :class:`~invest_domain.research.models.EvidencePack` from a persisted
  row, with fail-closed cross-checks against the database columns.
- Internal payload inspectors used by :func:`row_to_evidence_pack`.

Runtime metadata fields the audit contract forbids as content facts
(``workspace_path``, ``e2a_request_id``, ``e2a_session_id`` and the
domain-side ``generated_at``) are intentionally excluded from the
persisted JSONB payload. The storage layer re-attaches the
storage-side ``pack_id`` and ``generated_at`` from the database row
when the pack is reconstructed.

The module imports only from ``invest_domain`` and the storage-side
``invest_storage.models`` (the ORM row class). It does **not** import
``invest_storage.repositories`` so the repository can depend on the
codec without creating an import cycle.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.research import (
    CandidateContext,
    CaseContext,
    DataQuality,
    EvidencePack,
    FactorObservation,
    FactorSetMetadata,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    SourceReference,
    pack_content_projection,
)
from invest_domain.shared.canonical import canonical_json

from invest_storage.models import ResearchEvidencePackRow

__all__ = [
    "coerce_optional_uuid",
    "evidence_pack_to_payload",
    "row_to_evidence_pack",
]


def coerce_optional_uuid(value: Any, *, field_name: str) -> UUID | None:
    """Convert a permissive ``case_id`` value to UUID or ``None``.

    Accepts a real :class:`UUID`, a canonical 8-4-4-4-12 hex string, or
    ``None``. Anything else (including the empty string, the literal
    ``"None"``, or a non-UUID sentinel) raises
    :class:`ValueError` so a malformed ``CaseContext.case_id`` cannot
    smuggle a non-UUID value into the ``research_case_id`` FK column.
    """

    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(
                f"{field_name} {value!r} is not a UUID-compatible string: {exc}"
            ) from exc
    raise ValueError(f"{field_name} must be UUID, str, or None; got {type(value).__name__}")


def evidence_pack_to_payload(pack: EvidencePack) -> dict[str, Any]:
    """Build the canonical JSON-safe payload for an :class:`EvidencePack`.

    The payload is the canonical content projection (the exact dict
    ``pack_hash`` is computed from) plus non-hashed presentation
    fields (``case.case_id``, per-factor ``evidence_id`` and a
    ``pack_hash`` echo token). Runtime metadata that the contract
    forbids as content facts (``workspace_path``, ``e2a_request_id``,
    ``e2a_session_id``, ``generated_at``) is intentionally omitted;
    the storage layer re-attaches the storage-side ``pack_id`` and
    ``generated_at`` from the database row when the pack is
    reconstructed.

    All values are converted through :func:`invest_domain.shared.canonical.canonical_json`
    so ``Decimal``, :class:`date`, :class:`UUID` and friends become
    JSON-safe primitives before the row hits PostgreSQL JSONB. The
    PostgreSQL driver (psycopg) does not accept :class:`Decimal` or
    :class:`date` objects directly, so an in-memory JSON round-trip is
    the cheapest deterministic encoder we can use.
    """

    projection = pack_content_projection(pack)
    safe = json.loads(canonical_json(projection))
    raw_case_id = pack.case.case_id
    case_uuid = coerce_optional_uuid(raw_case_id, field_name="CaseContext.case_id")
    safe["case"]["case_id"] = None if case_uuid is None else str(case_uuid)
    safe["factors"] = [
        {**factor, "evidence_id": observation.evidence_id}
        for factor, observation in zip(safe["factors"], pack.factors, strict=True)
    ]
    safe["pack_hash"] = pack.pack_hash
    return safe


def _extract_payload_pack_hash(payload: dict[str, Any]) -> str:
    raw = payload.get("pack_hash")
    if raw is None:
        raise ValueError("payload.pack_hash is required for reconstruction")
    if not isinstance(raw, str) or len(raw) != 64:
        raise ValueError(
            f"payload.pack_hash must be a 64-character hex string, "
            f"got {type(raw).__name__} of length "
            f"{len(raw) if isinstance(raw, str) else 'n/a'}"
        )
    return raw


def _extract_payload_case_id(payload: dict[str, Any]) -> str | None:
    case_section = payload.get("case")
    if not isinstance(case_section, dict):
        raise ValueError("payload.case must be an object")
    raw = case_section.get("case_id")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("payload.case.case_id must be a string or None")
    return raw


def _extract_payload_evidence_ids(payload: dict[str, Any]) -> list[str | None]:
    factors_section = payload.get("factors")
    if not isinstance(factors_section, list):
        raise ValueError("payload.factors must be a list")
    evidence_ids: list[str | None] = []
    for index, item in enumerate(factors_section):
        if not isinstance(item, dict):
            raise ValueError(
                f"payload.factors[{index}] must be an object, got {type(item).__name__}"
            )
        eid = item.get("evidence_id")
        if eid is not None and not isinstance(eid, str):
            raise ValueError(f"payload.factors[{index}].evidence_id must be a string or None")
        evidence_ids.append(eid)
    return evidence_ids


def _check_payload_db_columns(payload: dict[str, Any], row: ResearchEvidencePackRow) -> None:
    """Fail closed if the database columns disagree with the JSONB payload."""

    payload_schema_version = payload.get("schema_version")
    if payload_schema_version != row.schema_version:
        raise ValueError(
            "research_evidence_packs row column mismatch on schema_version: "
            f"db={row.schema_version!r} payload={payload_schema_version!r}"
        )
    factor_set = payload.get("factor_set")
    if not isinstance(factor_set, dict):
        raise ValueError("payload.factor_set must be an object")
    if factor_set.get("key") != row.factor_set_key:
        raise ValueError(
            "research_evidence_packs row column mismatch on factor_set.key: "
            f"db={row.factor_set_key!r} payload={factor_set.get('key')!r}"
        )
    if factor_set.get("version") != row.factor_set_version:
        raise ValueError(
            "research_evidence_packs row column mismatch on factor_set.version: "
            f"db={row.factor_set_version!r} payload={factor_set.get('version')!r}"
        )
    data_quality = payload.get("data_quality")
    if not isinstance(data_quality, dict):
        raise ValueError("payload.data_quality must be an object")
    if data_quality.get("freshness_status") != row.freshness_status:
        raise ValueError(
            "research_evidence_packs row column mismatch on freshness_status: "
            f"db={row.freshness_status!r} "
            f"payload={data_quality.get('freshness_status')!r}"
        )
    if data_quality.get("quality_status") != row.quality_status:
        raise ValueError(
            "research_evidence_packs row column mismatch on quality_status: "
            f"db={row.quality_status!r} "
            f"payload={data_quality.get('quality_status')!r}"
        )
    instrument = payload.get("instrument")
    if not isinstance(instrument, dict):
        raise ValueError("payload.instrument must be an object")
    if instrument.get("instrument_id") != str(row.instrument_id):
        raise ValueError(
            "research_evidence_packs row column mismatch on instrument_id: "
            f"db={row.instrument_id!s} payload={instrument.get('instrument_id')!r}"
        )
    case_section = payload.get("case")
    if not isinstance(case_section, dict):
        raise ValueError("payload.case must be an object")
    if case_section.get("instrument_id") != str(row.instrument_id):
        raise ValueError("research_evidence_packs row column mismatch on case.instrument_id")
    if case_section.get("as_of_date") != row.as_of_date.isoformat():
        raise ValueError(
            "research_evidence_packs row column mismatch on case.as_of_date: "
            f"db={row.as_of_date.isoformat()!r} "
            f"payload={case_section.get('as_of_date')!r}"
        )


def _check_payload_case_id(
    payload_case_id_str: str | None, row: ResearchEvidencePackRow
) -> UUID | None:
    payload_case_uuid = coerce_optional_uuid(payload_case_id_str, field_name="payload.case.case_id")
    if row.research_case_id != payload_case_uuid:
        raise ValueError(
            "research_evidence_packs row column mismatch on research_case_id: "
            f"db={row.research_case_id!s} payload={payload_case_uuid!s}"
        )
    return row.research_case_id


def row_to_evidence_pack(row: ResearchEvidencePackRow) -> EvidencePack:
    """Reconstruct the domain :class:`EvidencePack` from a persisted row.

    The payload is the canonical content projection augmented with
    non-hashed presentation fields. Every column on the row is
    cross-checked against the corresponding payload field so a corrupt
    row fails closed via :class:`ValueError` rather than silently
    normalizing. The domain :meth:`EvidencePack.__post_init__` then
    re-asserts the canonical hash, the case/instrument invariant and
    the factor-set completeness.
    """

    payload = row.payload
    if not isinstance(payload, dict):
        raise ValueError(
            f"research_evidence_packs.payload must be a JSON object, got {type(payload).__name__}"
        )
    payload_hash = _extract_payload_pack_hash(payload)
    payload_case_id = _extract_payload_case_id(payload)
    evidence_ids = _extract_payload_evidence_ids(payload)
    _check_payload_db_columns(payload, row)
    payload_case_uuid = _check_payload_case_id(payload_case_id, row)

    instrument_raw = payload["instrument"]
    if not isinstance(instrument_raw, dict):
        raise ValueError("payload.instrument must be an object")
    instrument = InstrumentSnapshot(
        instrument_id=InstrumentId(UUID(instrument_raw["instrument_id"])),
        symbol=str(instrument_raw["symbol"]),
        name=str(instrument_raw["name"]),
        exchange=str(instrument_raw["exchange"]),
        currency=str(instrument_raw.get("currency") or "CNY"),
    )

    case_raw = payload["case"]
    if not isinstance(case_raw, dict):
        raise ValueError("payload.case must be an object")
    case = CaseContext(
        instrument_id=InstrumentId(UUID(case_raw["instrument_id"])),
        as_of_date=date.fromisoformat(case_raw["as_of_date"]),
        question=str(case_raw["question"]),
        horizon=str(case_raw["horizon"]),
        case_id=payload_case_uuid,
    )

    market_raw = payload["market_snapshot"]
    if not isinstance(market_raw, dict):
        raise ValueError("payload.market_snapshot must be an object")
    latest_trade_raw = market_raw.get("latest_trade_date")
    market_snapshot = MarketSnapshot(
        latest_trade_date=(date.fromisoformat(latest_trade_raw) if latest_trade_raw else None),
        latest_close=(
            Decimal(str(market_raw["latest_close"]))
            if market_raw.get("latest_close") is not None
            else None
        ),
        currency=str(market_raw["currency"]),
        observed_trading_days=int(market_raw["observed_trading_days"]),
        valid_price_days=int(market_raw["valid_price_days"]),
        suspended_days=int(market_raw.get("suspended_days") or 0),
    )

    factors_raw = payload["factors"]
    if not isinstance(factors_raw, list):
        raise ValueError("payload.factors must be a list")
    factors = tuple(
        FactorObservation(
            factor_key=str(item["factor_key"]),
            instrument_id=instrument.instrument_id,
            value=(Decimal(str(item["value"])) if item.get("value") is not None else None),
            unit=str(item["unit"]),
            window=int(item["window"]),
            observed_date=date.fromisoformat(item["observed_date"]),
            quality_status=QualityStatus(item["quality_status"]),
            source_kind=str(item["source_kind"]),
            source_ref=str(item["source_ref"]),
            evidence_id=evidence_ids[index],
        )
        for index, item in enumerate(factors_raw)
    )

    data_quality_raw = payload["data_quality"]
    if not isinstance(data_quality_raw, dict):
        raise ValueError("payload.data_quality must be an object")
    data_quality = DataQuality(
        freshness_status=FreshnessStatus(data_quality_raw["freshness_status"]),
        quality_status=QualityStatus(data_quality_raw["quality_status"]),
        target_trading_days=int(data_quality_raw["target_trading_days"]),
        observed_trading_days=int(data_quality_raw["observed_trading_days"]),
        valid_price_days=int(data_quality_raw["valid_price_days"]),
        invalid_days=int(data_quality_raw.get("invalid_days") or 0),
        suspended_days=int(data_quality_raw.get("suspended_days") or 0),
        conflict_detected=bool(data_quality_raw.get("conflict_detected") or False),
    )

    candidate_raw = payload.get("candidate_context")
    candidate_context: CandidateContext | None = None
    if candidate_raw is not None:
        if not isinstance(candidate_raw, dict):
            raise ValueError("payload.candidate_context must be an object or None")
        total_score_raw = candidate_raw.get("total_score")
        candidate_context = CandidateContext(
            included=candidate_raw.get("included"),
            rank=candidate_raw.get("rank"),
            total_score=(Decimal(str(total_score_raw)) if total_score_raw is not None else None),
            exclusion_codes=tuple(candidate_raw.get("exclusion_codes") or ()),
        )

    factor_set_raw = payload["factor_set"]
    if not isinstance(factor_set_raw, dict):
        raise ValueError("payload.factor_set must be an object")
    factor_set = FactorSetMetadata(
        key=str(factor_set_raw["key"]),
        version=str(factor_set_raw["version"]),
    )

    source_refs_raw = payload.get("source_refs")
    if source_refs_raw is None:
        source_refs_raw = []
    if not isinstance(source_refs_raw, list):
        raise ValueError("payload.source_refs must be a list")
    for index, item in enumerate(source_refs_raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"payload.source_refs[{index}] must be an object, got {type(item).__name__}"
            )
    source_refs = tuple(
        SourceReference(
            source_kind=str(item["source_kind"]),
            source_ref=str(item["source_ref"]),
            observed_date=date.fromisoformat(item["observed_date"]),
            quality_status=QualityStatus(item["quality_status"]),
            revision=item.get("revision"),
        )
        for item in source_refs_raw
    )

    missing_fields = tuple(payload.get("missing_fields") or ())
    warnings = tuple(payload.get("warnings") or ())

    return EvidencePack(
        case=case,
        instrument=instrument,
        market_snapshot=market_snapshot,
        factors=factors,
        data_quality=data_quality,
        candidate_context=candidate_context,
        missing_fields=missing_fields,
        warnings=warnings,
        source_refs=source_refs,
        schema_version=str(payload["schema_version"]),
        factor_set=factor_set,
        pack_hash=payload_hash,
        pack_id=row.id,
        generated_at=row.created_at,
    )
