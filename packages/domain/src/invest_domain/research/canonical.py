from __future__ import annotations

from typing import Any

from invest_domain.research.models import EvidencePack, FactorObservation
from invest_domain.shared.canonical import canonical_json, canonical_sha256


def item_content_projection(observation: FactorObservation) -> dict[str, Any]:
    return {
        "evidence_key": observation.evidence_key,
        "evidence_type": "factor_observation",
        "instrument_id": str(observation.instrument_id),
        "observed_date": observation.observed_date,
        "payload": {
            "factor_key": observation.factor_key,
            "unit": observation.unit,
            "value": observation.value,
            "window": observation.window,
        },
        "quality_status": observation.quality_status.value,
        "source_kind": observation.source_kind,
        "source_ref": observation.source_ref,
    }


def compute_item_hash(observation: FactorObservation) -> str:
    return canonical_sha256(item_content_projection(observation))


def _factor_projection(observation: FactorObservation) -> dict[str, Any]:
    return {
        "factor_key": observation.factor_key,
        "item_hash": observation.item_hash,
        "observed_date": observation.observed_date,
        "quality_status": observation.quality_status.value,
        "source_kind": observation.source_kind,
        "source_ref": observation.source_ref,
        "unit": observation.unit,
        "value": observation.value,
        "window": observation.window,
    }


def pack_content_projection(pack: EvidencePack) -> dict[str, Any]:
    candidate = pack.candidate_context
    return {
        "candidate_context": None
        if candidate is None
        else {
            "exclusion_codes": list(candidate.exclusion_codes),
            "included": candidate.included,
            "rank": candidate.rank,
            "total_score": candidate.total_score,
        },
        "case": {
            "as_of_date": pack.case.as_of_date,
            "horizon": pack.case.horizon,
            "instrument_id": str(pack.case.instrument_id),
            "question": pack.case.question,
        },
        "data_quality": {
            "conflict_detected": pack.data_quality.conflict_detected,
            "freshness_status": pack.data_quality.freshness_status.value,
            "invalid_days": pack.data_quality.invalid_days,
            "observed_trading_days": pack.data_quality.observed_trading_days,
            "quality_status": pack.data_quality.quality_status.value,
            "suspended_days": pack.data_quality.suspended_days,
            "target_trading_days": pack.data_quality.target_trading_days,
            "valid_price_days": pack.data_quality.valid_price_days,
        },
        "factor_set": {"key": pack.factor_set.key, "version": pack.factor_set.version},
        "factors": [_factor_projection(item) for item in pack.factors],
        "instrument": {
            "currency": pack.instrument.currency,
            "exchange": pack.instrument.exchange,
            "instrument_id": str(pack.instrument.instrument_id),
            "name": pack.instrument.name,
            "symbol": pack.instrument.symbol,
        },
        "market_snapshot": {
            "currency": pack.market_snapshot.currency,
            "latest_close": pack.market_snapshot.latest_close,
            "latest_trade_date": pack.market_snapshot.latest_trade_date,
            "observed_trading_days": pack.market_snapshot.observed_trading_days,
            "suspended_days": pack.market_snapshot.suspended_days,
            "valid_price_days": pack.market_snapshot.valid_price_days,
        },
        "missing_fields": list(pack.missing_fields),
        "schema_version": pack.schema_version,
        "source_refs": [
            {
                "observed_date": item.observed_date,
                "quality_status": item.quality_status.value,
                "revision": item.revision,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
            }
            for item in pack.source_refs
        ],
        "warnings": list(pack.warnings),
    }


def canonical_pack_json(pack: EvidencePack) -> str:
    return canonical_json(pack_content_projection(pack))


def compute_pack_hash(pack: EvidencePack) -> str:
    return canonical_sha256(pack_content_projection(pack))


def make_evidence_id(pack_hash: str, observation: FactorObservation) -> str:
    if len(pack_hash) != 64 or len(observation.item_hash) != 64:
        raise ValueError("pack_hash and item_hash must be 64-character hashes")
    return f"evi:{pack_hash[:12]}:{observation.evidence_key}:{observation.item_hash[:12]}"


def pack_view(pack: EvidencePack) -> dict[str, Any]:
    payload = pack_content_projection(pack)
    payload["case"]["case_id"] = None if pack.case.case_id is None else str(pack.case.case_id)
    payload["factors"] = [
        {**factor, "evidence_id": observation.evidence_id}
        for factor, observation in zip(payload["factors"], pack.factors, strict=True)
    ]
    payload["pack_hash"] = pack.pack_hash
    payload["pack_id"] = None if pack.pack_id is None else str(pack.pack_id)
    payload["pipeline_run_id"] = (
        None if pack.pipeline_run_id is None else str(pack.pipeline_run_id)
    )
    payload["e2a_request_id"] = pack.e2a_request_id
    payload["e2a_session_id"] = pack.e2a_session_id
    payload["generated_at"] = pack.generated_at
    payload["workspace_path"] = pack.workspace_path
    return payload
