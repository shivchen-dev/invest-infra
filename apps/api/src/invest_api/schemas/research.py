from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase
from invest_domain.research.research_run import ResearchResult, ResearchRun
from pydantic import BaseModel, Field


class ResearchCaseResponse(BaseModel):
    case_id: UUID
    instrument_id: UUID
    as_of_date: date
    question: str
    horizon: str
    status: str
    created_at: datetime
    closed_at: datetime | None = None
    candidate_pool_run_id: UUID | None = None

    @classmethod
    def from_domain(cls, case: ResearchCase) -> ResearchCaseResponse:
        return cls(
            case_id=case.case_id,
            instrument_id=case.instrument_id.value,
            as_of_date=case.as_of_date,
            question=case.question,
            horizon=case.horizon,
            status=case.status.value,
            created_at=case.created_at,
            closed_at=case.closed_at,
            candidate_pool_run_id=case.candidate_pool_run_id,
        )


class ResearchCaseListResponse(BaseModel):
    items: list[ResearchCaseResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class EvidenceCaseResponse(BaseModel):
    case_id: UUID | None = None
    instrument_id: UUID
    as_of_date: date
    question: str
    horizon: str


class EvidenceInstrumentResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    name: str
    exchange: str
    currency: str


class EvidenceMarketSnapshotResponse(BaseModel):
    latest_trade_date: date | None
    latest_close: Decimal | None
    currency: str
    observed_trading_days: int
    valid_price_days: int
    suspended_days: int


class EvidenceFactorResponse(BaseModel):
    factor_key: str
    value: Decimal | None
    unit: str = Field(
        description=(
            "Measurement unit supplied by the frozen factor contract; interpret value "
            "using this field without percentage or currency rescaling."
        )
    )
    window: int
    observed_date: date
    quality_status: str
    source_kind: str
    source_ref: str
    evidence_id: str | None


class EvidenceDataQualityResponse(BaseModel):
    freshness_status: str
    quality_status: str
    target_trading_days: int
    observed_trading_days: int
    valid_price_days: int
    invalid_days: int
    suspended_days: int
    conflict_detected: bool


class EvidenceSourceReferenceResponse(BaseModel):
    source_kind: str
    source_ref: str
    observed_date: date
    quality_status: str
    revision: int | None


class EvidencePackResponse(BaseModel):
    pack_id: UUID | None
    case: EvidenceCaseResponse
    instrument: EvidenceInstrumentResponse
    market_snapshot: EvidenceMarketSnapshotResponse
    factors: list[EvidenceFactorResponse]
    data_quality: EvidenceDataQualityResponse
    missing_fields: list[str]
    warnings: list[str]
    source_refs: list[EvidenceSourceReferenceResponse]
    schema_version: str
    factor_set_key: str
    factor_set_version: str
    pack_hash: str
    generated_at: datetime | None

    @classmethod
    def from_domain(cls, pack: EvidencePack) -> EvidencePackResponse:
        return cls(
            pack_id=pack.pack_id,
            case=EvidenceCaseResponse(
                case_id=UUID(str(pack.case.case_id)) if pack.case.case_id else None,
                instrument_id=pack.case.instrument_id.value,
                as_of_date=pack.case.as_of_date,
                question=pack.case.question,
                horizon=pack.case.horizon,
            ),
            instrument=EvidenceInstrumentResponse(
                instrument_id=pack.instrument.instrument_id.value,
                symbol=pack.instrument.symbol,
                name=pack.instrument.name,
                exchange=pack.instrument.exchange,
                currency=pack.instrument.currency,
            ),
            market_snapshot=EvidenceMarketSnapshotResponse.model_validate(
                pack.market_snapshot, from_attributes=True
            ),
            factors=[
                EvidenceFactorResponse.model_validate(item, from_attributes=True)
                for item in pack.factors
            ],
            data_quality=EvidenceDataQualityResponse.model_validate(
                pack.data_quality, from_attributes=True
            ),
            missing_fields=list(pack.missing_fields),
            warnings=list(pack.warnings),
            source_refs=[
                EvidenceSourceReferenceResponse.model_validate(item, from_attributes=True)
                for item in pack.source_refs
            ],
            schema_version=pack.schema_version,
            factor_set_key=pack.factor_set.key,
            factor_set_version=pack.factor_set.version,
            pack_hash=pack.pack_hash,
            generated_at=pack.generated_at,
        )


class ResearchRunResponse(BaseModel):
    run_id: UUID
    case_id: UUID
    evidence_pack_id: UUID
    runner_key: str
    playbook_key: str
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None

    @classmethod
    def from_domain(cls, run: ResearchRun) -> ResearchRunResponse:
        return cls.model_validate(run, from_attributes=True)


class ResearchRunListResponse(BaseModel):
    items: list[ResearchRunResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ResearchResultResponse(BaseModel):
    result_id: UUID
    run_id: UUID
    evidence_pack_id: UUID
    conclusion: str
    risks: list[str]
    evidence_ids: list[str]
    report_markdown: str
    model_key: str
    model_version: str
    playbook_version: str
    adapter_version: str
    created_at: datetime

    @classmethod
    def from_domain(cls, result: ResearchResult) -> ResearchResultResponse:
        return cls(
            result_id=result.result_id,
            run_id=result.run_id,
            evidence_pack_id=result.evidence_pack_id,
            conclusion=result.conclusion,
            risks=list(result.risks),
            evidence_ids=list(result.evidence_ids),
            report_markdown=result.report_markdown,
            model_key=result.model_key,
            model_version=result.model_version,
            playbook_version=result.playbook_version,
            adapter_version=result.adapter_version,
            created_at=result.created_at,
        )


__all__ = [
    "EvidencePackResponse",
    "ResearchCaseListResponse",
    "ResearchCaseResponse",
    "ResearchResultResponse",
    "ResearchRunListResponse",
    "ResearchRunResponse",
]
