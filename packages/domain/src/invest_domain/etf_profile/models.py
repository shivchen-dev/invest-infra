"""Pure domain model for the ``etf_profile`` bounded context.

The ``etf_profile`` bounded context captures the static, mostly
provider-supplied attributes of a single ETF instrument together with
the per-field evidence that supports them. The Stage DC-2 contract was
:class:`EtfProfile` — a single canonical record per instrument. PR
``PR-ETF-PROFILE-01`` extends that contract with the
:class:`FieldEvidence` value object so that every populated profile
field carries its own source provenance, observation timestamp,
quality status and confidence score. The model remains
infrastructure-free:

- No SQLAlchemy, Alembic, FastAPI, Dagster, httpx or Provider SDK imports.
- No environment access (``os.environ``) and no clock access.
- No field defaults that would fabricate values when the Provider
  response omits them; ``None`` is the canonical ``unknown`` carrier.

The module exposes:

- :class:`EtfProfile` — the Stage DC-2 canonical record.
- :class:`FieldValueType` — closed-set ``TEXT`` / ``DECIMAL`` / ``DATE``
  vocabulary for evidence values.
- :class:`FieldKey` — closed-set evidence vocabulary covering the
  Level 0 / Level 1 fields of the ETF Profile Evidence Framework
  (``symbol`` / ``name`` / ``exchange`` / ``status`` / ``manager`` /
  ``benchmark_index`` / ``category`` / ``inception_date`` /
  ``fund_type`` / ``management_fee`` / ``custody_fee`` / ``aum`` /
  ``shares`` plus the evidence-only ``market_value`` and
  ``turnover_value`` keys).
- :class:`FieldEvidenceSource` — provider provenance for one evidence
  row (provider_key / dataset_key / observed_at / source_batch_id /
  revision).
- :class:`FieldEvidence` — one piece of business evidence for one
  instrument / field combination, including its computed
  ``content_hash``.

EtfProfile validation policy (Stage DC-2):

- ``instrument_id`` is the stable 1-1 primary key. It must be a non-zero
  UUID (the same invariant :class:`invest_domain.instruments.models.
  InstrumentId` enforces on :class:`Instrument.id`) so a stored profile
  row always points back at a known instrument.
- All textual fields (``manager``, ``benchmark_index``, ``category``,
  ``fund_type``) are optional and rejected as empty when supplied,
  matching the ``length(...) > 0`` database check constraints.
- ``inception_date`` is optional and stored as a calendar date. Provider
  publication timing is not imposed in the pure domain model; any
  freshness or as-of-date policy belongs to the collection/application
  layer.
- ``management_fee`` and ``custody_fee`` are optional percentage rates
  expressed as ``Decimal`` fractions in the inclusive range
  ``[0, 1)`` so ``0.0015`` correctly represents the contractual
  ``0.15 %`` management fee. The exclusive upper bound rejects the
  meaningless ``100 %``+ total-fee rows a buggy provider response
  could otherwise introduce.
- ``aum`` (assets under management, in fund currency) and ``shares``
  (units outstanding) are optional and must be strictly positive
  finite ``Decimal`` values when supplied. ``Decimal`` carries full
  precision through the storage layer; the application service never
  rounds them before they reach the database.

FieldEvidence validation policy (PR-ETF-PROFILE-01):

- ``instrument_id`` mirrors the same non-zero UUID contract as
  :class:`EtfProfile` so a field-evidence row always points back at a
  known instrument.
- The runtime type of ``value`` must match ``value_type``: ``TEXT``
  requires ``str`` (non-empty after stripping, with surrounding
  whitespace normalised the same way as :class:`EtfProfile`), ``DECIMAL``
  requires a finite ``Decimal``, ``DATE`` requires a ``date`` that is
  explicitly not a ``datetime`` (since ``datetime`` is a subclass of
  ``date`` in Python and cannot be smuggled into a calendar-date slot).
- ``QualityStatus.MISSING`` forces ``value`` to ``None``; every other
  ``QualityStatus`` may carry a value or ``None`` (a Provider may
  publish a value that is later flagged as ``CONFLICT`` or ``INVALID``
  without losing the original observation).
- ``confidence_score`` is a finite ``Decimal`` in the inclusive range
  ``[0, 1]``. The same value goes through the canonical hash so it
  round-trips through the audit chain without precision loss.
- ``source.observed_at`` and the optional ``created_at`` must be
  timezone-aware ``datetime`` values so the canonical hash stays
  deterministic across processes and time zones.
- ``content_hash`` is the 64-character lowercase hex digest of the
  business evidence content (instrument_id, field_key, value,
  value_type, source provenance, quality_status, confidence_score)
  computed through ``invest_domain.shared.canonical.content_hash`` so
  the hash schema version is embedded in the digest. ``created_at`` is
  intentionally excluded from the digest because it is an audit
  timestamp that must not invalidate the hash when the same evidence
  row is observed at slightly different wall-clock times.
- :class:`FieldKey` keeps ``AUM``, ``MARKET_VALUE`` and
  ``TURNOVER_VALUE`` distinct (per plan §6): the trading-day market
  value of an ETF and its turnover value are not interchangeable with
  assets under management, and no helper in this module aliases one
  to another.

The same field set is reflected 1-1 in the ``core.etf_profiles``
SQLAlchemy model added in PR for DC-2 and in the
``20260804_0008_etf_profiles`` Alembic migration. The new
``analytics.etf_profile_fields`` table introduced by
``PR-ETF-PROFILE-01`` is intentionally defined downstream; this module
remains a pure-domain contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from invest_domain.research.models import QualityStatus
from invest_domain.shared.canonical import content_hash

_INSTRUMENT_ID_NONE = UUID("00000000-0000-0000-0000-000000000000")
_CONTENT_HASH_HEX_LEN: int = 64


def _require_optional_text(value: str | None, *, field_name: str) -> str | None:
    """Accept ``None`` or a non-empty ``str``; reject blank/whitespace strings."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"EtfProfile.{field_name} must be a str or None, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise ValueError(
            f"EtfProfile.{field_name} must not be empty when supplied"
        )
    return stripped


def _require_optional_fee_rate(
    value: Decimal | None, *, field_name: str
) -> Decimal | None:
    """Accept ``None`` or a finite ``Decimal`` in ``[0, 1)``.

    The fund management fee is recorded as a fractional rate
    (``0.0015`` for a contractual ``0.15 %``). An upper bound of
    ``1`` excludes the meaningless ``100 %``+ total-fee rows a buggy
    provider response could otherwise introduce; a lower bound of
    ``0`` keeps a legitimate zero-fee fund fundable for promotional
    products that the candidate pool may need to inspect.

    A ``None`` value is the documented carrier for ``unknown`` /
    ``not disclosed`` and never triggers a default.
    """

    if value is None:
        return None
    if not isinstance(value, Decimal) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a Decimal or None, "
            f"got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(
            f"EtfProfile.{field_name} must be a finite Decimal, got {value!s}"
        )
    if value < 0:
        raise ValueError(
            f"EtfProfile.{field_name} must be >= 0, got {value!s}"
        )
    if value >= 1:
        raise ValueError(
            f"EtfProfile.{field_name} must be < 1 (exclusive), got {value!s}"
        )
    return value


def _require_optional_positive_decimal(
    value: Decimal | None, *, field_name: str
) -> Decimal | None:
    """Accept ``None`` or a finite, strictly-positive ``Decimal``.

    Used for ``aum`` and ``shares``: both represent physical quantities
    that are unambiguously positive when disclosed. A ``None`` value is
    the carrier for ``unknown`` / ``not disclosed`` and never triggers
    a default.
    """

    if value is None:
        return None
    if not isinstance(value, Decimal) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a Decimal or None, "
            f"got {type(value).__name__}"
        )
    if not value.is_finite():
        raise ValueError(
            f"EtfProfile.{field_name} must be a finite Decimal, got {value!s}"
        )
    if value <= 0:
        raise ValueError(
            f"EtfProfile.{field_name} must be > 0, got {value!s}"
        )
    return value


def _require_instrument_uuid(value: Any, *, field_name: str) -> UUID:
    """Reject non-UUID or all-zero UUIDs.

    The instrument id is the 1-1 primary key of ``core.etf_profiles``
    and MUST always refer to a known row in ``core.instruments``. The
    all-zero UUID is explicitly rejected because it can only ever mean
    ``unknown`` here, which would silently break the foreign key
    constraint at insert time.
    """

    if not isinstance(value, UUID) or isinstance(value, bool):
        raise TypeError(
            f"EtfProfile.{field_name} must be a UUID, got {type(value).__name__}"
        )
    if value == _INSTRUMENT_ID_NONE:
        raise ValueError(
            f"EtfProfile.{field_name} must not be the all-zero UUID"
        )
    return value


@dataclass(frozen=True, slots=True)
class EtfProfile:
    """Immutable, pure-domain record of one ETF's static metadata.

    The field set mirrors the Stage DC-2 plan
    (``docs/plan/invest-infra-data-collection-enhancement-plan-v1.0.md``
    §"DC-2 ETF 基础研究数据 / ETF Profile") and the
    ``core.etf_profiles`` storage row introduced in the
    ``20260804_0008_etf_profiles`` Alembic migration. The natural key
    is ``instrument_id`` (one profile per listed instrument).

    Construction rules:

    - ``instrument_id`` (UUID, required) must be a non-zero UUID. It is
      the storage primary key and the foreign key to
      ``core.instruments.id``.
    - ``manager`` (str | None) — the fund manager's name as disclosed
      by the Provider; ``None`` when undisclosed. An empty or
      whitespace-only string is rejected.
    - ``benchmark_index`` (str | None) — the underlying benchmark
      identifier; ``None`` when undisclosed.
    - ``category`` (str | None) — the Provider's coarse
      classification (``Equity``, ``Bond``, ``Commodity`` ...);
      ``None`` when undisclosed.
    - ``inception_date`` (date | None) — the listing / inception date.
      ``None`` when undisclosed. It is validated as a calendar date;
      collection-time freshness policy is outside this value object.
    - ``fund_type`` (str | None) — the legal/open-end/closed-end
      taxonomy; ``None`` when undisclosed.
    - ``management_fee`` (Decimal | None) — annual management fee as a
      fractional rate (``0.0015`` = 0.15%); ``None`` when undisclosed.
      Inclusive lower bound ``0``, exclusive upper bound ``1``.
    - ``custody_fee`` (Decimal | None) — annual custody fee as a
      fractional rate. Same bounds as ``management_fee``.
    - ``aum`` (Decimal | None) — assets under management in fund
      currency; ``None`` when undisclosed. Strictly positive when
      supplied.
    - ``shares`` (Decimal | None) — units outstanding; ``None`` when
      undisclosed. Strictly positive when supplied.

    The dataclass is ``frozen=True`` + ``slots=True``; every assignment
    path passes through :meth:`__post_init__` so the validation cannot
    be bypassed via ``object.__setattr__``.
    """

    instrument_id: UUID
    manager: str | None = None
    benchmark_index: str | None = None
    category: str | None = None
    inception_date: date | None = None
    fund_type: str | None = None
    management_fee: Decimal | None = None
    custody_fee: Decimal | None = None
    aum: Decimal | None = None
    shares: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _require_instrument_uuid(self.instrument_id, field_name="instrument_id"),
        )
        object.__setattr__(
            self, "manager", _require_optional_text(self.manager, field_name="manager")
        )
        object.__setattr__(
            self,
            "benchmark_index",
            _require_optional_text(self.benchmark_index, field_name="benchmark_index"),
        )
        object.__setattr__(
            self, "category", _require_optional_text(self.category, field_name="category")
        )
        object.__setattr__(
            self, "fund_type", _require_optional_text(self.fund_type, field_name="fund_type")
        )
        if self.inception_date is not None and (
            # ``datetime`` is a subclass of ``date``; explicitly reject
            # it so callers cannot smuggle in a timezone-aware timestamp
            # where the schema only stores a calendar date.
            isinstance(self.inception_date, datetime)
            or not isinstance(self.inception_date, date)
        ):
            raise TypeError(
                "EtfProfile.inception_date must be a date or None, "
                f"got {type(self.inception_date).__name__}"
            )
        object.__setattr__(
            self,
            "management_fee",
            _require_optional_fee_rate(
                self.management_fee, field_name="management_fee"
            ),
        )
        object.__setattr__(
            self,
            "custody_fee",
            _require_optional_fee_rate(self.custody_fee, field_name="custody_fee"),
        )
        object.__setattr__(
            self,
            "aum",
            _require_optional_positive_decimal(self.aum, field_name="aum"),
        )
        object.__setattr__(
            self,
            "shares",
            _require_optional_positive_decimal(self.shares, field_name="shares"),
        )


class FieldValueType(StrEnum):
    """Closed-set runtime value types carried by one field-evidence row.

    Mirrors the three storage layouts used by
    ``analytics.etf_profile_fields`` (``field_value`` may be stored as
    text / numeric / date depending on the field). Adding a new value
    type requires extending the ``analytics.etf_profile_fields``
    migration as well — this module is the upstream contract, the
    migration is downstream.
    """

    TEXT = "text"
    DECIMAL = "decimal"
    DATE = "date"


class FieldKey(StrEnum):
    """Closed-set vocabulary for ETF Profile field-evidence keys.

    Covers the Level 0 / Level 1 ETF Profile fields of the ETF Profile
    Evidence Framework plan §3:

    - ``symbol`` / ``name`` / ``exchange`` / ``status`` / ``fund_type``
      are the Level 0 trading-identity fields required for any ETF
      profile to be stored.
    - ``manager`` / ``benchmark_index`` / ``category`` /
      ``inception_date`` / ``aum`` / ``shares`` are the Level 1
      research-baseline fields.
    - ``management_fee`` / ``custody_fee`` are Level 1 fee disclosures.
    - ``market_value`` and ``turnover_value`` are evidence-only keys:
      they live on :class:`FieldEvidence` rows and are deliberately
      distinct from ``aum`` so the trading-day market value of an ETF
      cannot be silently rewritten as its assets under management (plan
      §6). No constructor or helper in this module aliases the three
      keys.
    """

    SYMBOL = "symbol"
    NAME = "name"
    EXCHANGE = "exchange"
    STATUS = "status"
    MANAGER = "manager"
    BENCHMARK_INDEX = "benchmark_index"
    CATEGORY = "category"
    INCEPTION_DATE = "inception_date"
    FUND_TYPE = "fund_type"
    MANAGEMENT_FEE = "management_fee"
    CUSTODY_FEE = "custody_fee"
    AUM = "aum"
    SHARES = "shares"
    MARKET_VALUE = "market_value"
    TURNOVER_VALUE = "turnover_value"


@dataclass(frozen=True, slots=True)
class FieldEvidenceSource:
    """Provider provenance for one field-evidence observation.

    Captures the minimum required to trace a piece of evidence back to
    the upstream provider pipeline (PR-ETF-PROFILE-01 / plan §2.2):

    - ``provider_key`` (non-empty ``str``) — stable identifier of the
      adapter that produced the observation (e.g. ``"akshare"``,
      ``"eastmoney"``). Mirrors the ``source.provider_key`` taxonomy.
    - ``dataset_key`` (non-empty ``str``) — stable identifier of the
      dataset inside that provider (e.g. ``"etf_profile_snapshot"``).
      A Provider may publish multiple datasets; the combination
      ``(provider_key, dataset_key)`` is the canonical reference.
    - ``observed_at`` (timezone-aware ``datetime``) — wall-clock time at
      which the Provider attached the observation to the upstream data
      store. ``datetime`` must be timezone-aware so the canonical hash
      remains deterministic across processes and time zones.
    - ``source_batch_id`` (``UUID | None``) — surrogate identifier of
      the upstream provider batch, when known. ``None`` is acceptable
      for sources that do not batch their responses.
    - ``revision`` (``int >= 1``) — provider revision counter so two
      observations with the same ``observed_at`` but a different
      upstream revision produce different content hashes. The lower
      bound ``1`` rejects accidental ``0`` revisions.
    """

    provider_key: str
    dataset_key: str
    observed_at: datetime
    source_batch_id: UUID | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.provider_key, str):
            raise TypeError(
                "FieldEvidenceSource.provider_key must be a str, "
                f"got {type(self.provider_key).__name__}"
            )
        if not self.provider_key.strip():
            raise ValueError("FieldEvidenceSource.provider_key must not be empty")
        if not isinstance(self.dataset_key, str):
            raise TypeError(
                "FieldEvidenceSource.dataset_key must be a str, "
                f"got {type(self.dataset_key).__name__}"
            )
        if not self.dataset_key.strip():
            raise ValueError("FieldEvidenceSource.dataset_key must not be empty")
        if not isinstance(self.observed_at, datetime) or isinstance(self.observed_at, bool):
            raise TypeError(
                "FieldEvidenceSource.observed_at must be a datetime, "
                f"got {type(self.observed_at).__name__}"
            )
        if self.observed_at.tzinfo is None or self.observed_at.tzinfo.utcoffset(self.observed_at) is None:
            raise ValueError("FieldEvidenceSource.observed_at must be a timezone-aware datetime")
        if self.source_batch_id is not None and (
            not isinstance(self.source_batch_id, UUID)
            or isinstance(self.source_batch_id, bool)
        ):
            raise TypeError(
                "FieldEvidenceSource.source_batch_id must be a UUID or None, "
                f"got {type(self.source_batch_id).__name__}"
            )
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise TypeError(
                "FieldEvidenceSource.revision must be an int, "
                f"got {type(self.revision).__name__}"
            )
        if self.revision < 1:
            raise ValueError(
                f"FieldEvidenceSource.revision must be >= 1, got {self.revision}"
            )


def _hash_payload(evidence: "FieldEvidence") -> dict[str, Any]:
    """Compose the canonical business payload for ``FieldEvidence.content_hash``.

    Includes instrument identity, the field key, the runtime value and
    its declared type, the full source provenance, the quality status
    and the confidence score. Excludes ``created_at`` (audit timestamp)
    so two observations of the same business content at different
    wall-clock times still share a single digest.
    """

    source = evidence.source
    return {
        "confidence_score": evidence.confidence_score,
        "field_key": evidence.field_key.value,
        "instrument_id": str(evidence.instrument_id),
        "quality_status": evidence.quality_status.value,
        "source": {
            "dataset_key": source.dataset_key,
            "observed_at": source.observed_at,
            "provider_key": source.provider_key,
            "revision": source.revision,
            "source_batch_id": (
                str(source.source_batch_id) if source.source_batch_id is not None else None
            ),
        },
        "value": evidence.value,
        "value_type": evidence.value_type.value,
    }


def compute_field_evidence_hash(evidence: "FieldEvidence") -> str:
    """Return the canonical ``FieldEvidence.content_hash`` for ``evidence``.

    Convenience wrapper used both inside the dataclass's
    :meth:`~FieldEvidence.__post_init__` (so the value stored on
    ``self.content_hash`` always matches the business content) and from
    tests that pin the digest for a controlled input.
    """

    return content_hash(_hash_payload(evidence))


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    """One piece of evidence for one ETF-profile field.

    Mirrors ``analytics.etf_profile_fields`` (PR-ETF-PROFILE-01 / plan
    §2.2). The dataclass is the smallest infrastructure-free contract
    for evidence-backed profile attributes; no Provider adapter, no
    Resolver and no Storage layer is required to construct or validate
    one.

    Construction rules:

    - ``instrument_id`` (``UUID``, required) must be a non-zero UUID,
      matching the same invariant :class:`EtfProfile` enforces so the
      evidence row always references a known instrument.
    - ``field_key`` (:class:`FieldKey`) — the closed-set vocabulary
      described above. ``AUM``, ``MARKET_VALUE`` and ``TURNOVER_VALUE``
      are distinct members of the same enum and are never rewritten
      into one another by this module.
    - ``value_type`` (:class:`FieldValueType`) — the closed-set runtime
      type of ``value``. The runtime type of ``value`` must match:
      ``TEXT`` ↔ ``str``, ``DECIMAL`` ↔ ``Decimal``, ``DATE`` ↔
      ``date``. ``None`` is allowed regardless of ``value_type`` when
      ``quality_status`` is not ``MISSING``; ``MISSING`` forces
      ``value`` to ``None``.
    - ``value`` (``str | Decimal | date | None``) — the disclosed value.
      ``TEXT`` values are stripped of surrounding whitespace exactly
      like :class:`EtfProfile` does so a Provider publishing
      ``" 华夏基金 "`` is stored as ``"华夏基金"``. ``DECIMAL`` values
      must be finite; ``DATE`` values must be ``date`` (and explicitly
      not ``datetime``).
    - ``source`` (:class:`FieldEvidenceSource`) — provider provenance
      for the observation. Validated in its own ``__post_init__``.
    - ``quality_status`` (:class:`~invest_domain.research.models.
      QualityStatus`) — closed-set vocabulary reused from the
      research context. ``MISSING`` requires ``value`` is ``None``.
    - ``confidence_score`` (finite ``Decimal`` in ``[0, 1]``) — the
      Provider's self-reported confidence for this evidence row.
    - ``content_hash`` (lowercase 64-character hex SHA-256 digest) —
      computed from the business content via
      :func:`compute_field_evidence_hash`. If the caller supplies a
      hash, it must match the computed digest; if it supplies ``""``
      the dataclass computes and stores it. The hash schema version
      (see ``CANONICAL_HASH_SCHEMA_VERSION``) is embedded into the
      digest so future canonical encoding changes do not silently
      invalidate historical rows.
    - ``created_at`` (timezone-aware ``datetime | None``) — audit
      timestamp populated by the application layer when the evidence
      row is written to storage. Excluded from ``content_hash`` because
      it is an audit-only signal and must not change the digest when
      the underlying business content is identical.

    The dataclass is ``frozen=True`` + ``slots=True``; every assignment
    path passes through :meth:`__post_init__` so the validation cannot
    be bypassed via ``object.__setattr__``.
    """

    instrument_id: UUID
    field_key: FieldKey
    value: str | Decimal | date | None
    value_type: FieldValueType
    source: FieldEvidenceSource
    quality_status: QualityStatus
    confidence_score: Decimal
    content_hash: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, UUID) or isinstance(self.instrument_id, bool):
            raise TypeError(
                "FieldEvidence.instrument_id must be a UUID, "
                f"got {type(self.instrument_id).__name__}"
            )
        if self.instrument_id == _INSTRUMENT_ID_NONE:
            raise ValueError("FieldEvidence.instrument_id must not be the all-zero UUID")

        if not isinstance(self.field_key, FieldKey):
            raise TypeError(
                "FieldEvidence.field_key must be a FieldKey, "
                f"got {type(self.field_key).__name__}"
            )

        if not isinstance(self.value_type, FieldValueType):
            raise TypeError(
                "FieldEvidence.value_type must be a FieldValueType, "
                f"got {type(self.value_type).__name__}"
            )

        normalized_value: str | Decimal | date | None = _normalize_value(
            self.value, self.value_type
        )

        if not isinstance(self.source, FieldEvidenceSource):
            raise TypeError(
                "FieldEvidence.source must be a FieldEvidenceSource, "
                f"got {type(self.source).__name__}"
            )

        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError(
                "FieldEvidence.quality_status must be a QualityStatus, "
                f"got {type(self.quality_status).__name__}"
            )
        if self.quality_status is QualityStatus.MISSING and normalized_value is not None:
            raise ValueError(
                "FieldEvidence.value must be None when quality_status is MISSING"
            )

        if (
            not isinstance(self.confidence_score, Decimal)
            or isinstance(self.confidence_score, bool)
        ):
            raise TypeError(
                "FieldEvidence.confidence_score must be a Decimal, "
                f"got {type(self.confidence_score).__name__}"
            )
        if not self.confidence_score.is_finite():
            raise ValueError(
                "FieldEvidence.confidence_score must be a finite Decimal, "
                f"got {self.confidence_score!s}"
            )
        if self.confidence_score < 0 or self.confidence_score > 1:
            raise ValueError(
                "FieldEvidence.confidence_score must be in [0, 1], "
                f"got {self.confidence_score!s}"
            )

        if self.content_hash:
            if not isinstance(self.content_hash, str):
                raise TypeError(
                    "FieldEvidence.content_hash must be a str, "
                    f"got {type(self.content_hash).__name__}"
                )
            if len(self.content_hash) != _CONTENT_HASH_HEX_LEN:
                raise ValueError(
                    "FieldEvidence.content_hash must be exactly "
                    f"{_CONTENT_HASH_HEX_LEN} lowercase hex characters, "
                    f"got length {len(self.content_hash)}"
                )
            try:
                int(self.content_hash, 16)
            except ValueError as exc:
                raise ValueError(
                    "FieldEvidence.content_hash must be a lowercase hex digest, "
                    f"got {self.content_hash!r}"
                ) from exc
            if self.content_hash != self.content_hash.lower():
                raise ValueError(
                    "FieldEvidence.content_hash must be lowercase hex, "
                    f"got {self.content_hash!r}"
                )

        if self.created_at is not None:
            if not isinstance(self.created_at, datetime) or isinstance(self.created_at, bool):
                raise TypeError(
                    "FieldEvidence.created_at must be a datetime or None, "
                    f"got {type(self.created_at).__name__}"
                )
            if (
                self.created_at.tzinfo is None
                or self.created_at.tzinfo.utcoffset(self.created_at) is None
            ):
                raise ValueError(
                    "FieldEvidence.created_at must be a timezone-aware datetime"
                )

        object.__setattr__(self, "value", normalized_value)
        computed = compute_field_evidence_hash(self)
        if self.content_hash and self.content_hash != computed:
            raise ValueError(
                "FieldEvidence.content_hash does not match its business content"
            )
        object.__setattr__(self, "content_hash", computed)


def _normalize_value(
    value: str | Decimal | date | None,
    value_type: FieldValueType,
) -> str | Decimal | date | None:
    """Validate ``value`` against ``value_type`` and normalise it.

    - ``TEXT``: ``str`` required, surrounding whitespace stripped
      (consistent with :class:`EtfProfile`'s ``_require_optional_text``).
      Empty strings are rejected so a Provider cannot publish a blank
      evidence row.
    - ``DECIMAL``: finite ``Decimal`` required; ``bool`` is explicitly
      rejected because ``bool`` is not a numeric value type for the
      evidence framework.
    - ``DATE``: ``date`` required; ``datetime`` is explicitly rejected
      because ``datetime`` is a subclass of ``date`` in Python and
      callers must not smuggle a timezone-aware timestamp into a
      calendar-date slot.
    - ``None`` is always accepted as the carrier for ``unknown`` /
      ``not disclosed``, provided ``quality_status`` is not ``MISSING``
      (the latter is enforced in :meth:`FieldEvidence.__post_init__`).
    """

    if value is None:
        return None
    if value_type is FieldValueType.TEXT:
        if not isinstance(value, str) or isinstance(value, bool):
            raise TypeError(
                "FieldEvidence.value must be a str when value_type is TEXT, "
                f"got {type(value).__name__}"
            )
        stripped = value.strip()
        if not stripped:
            raise ValueError("FieldEvidence.value must not be empty when value_type is TEXT")
        return stripped
    if value_type is FieldValueType.DECIMAL:
        if not isinstance(value, Decimal) or isinstance(value, bool):
            raise TypeError(
                "FieldEvidence.value must be a Decimal when value_type is DECIMAL, "
                f"got {type(value).__name__}"
            )
        if not value.is_finite():
            raise ValueError(
                "FieldEvidence.value must be a finite Decimal when value_type is DECIMAL, "
                f"got {value!s}"
            )
        return value
    if value_type is FieldValueType.DATE:
        if isinstance(value, datetime):
            raise TypeError(
                "FieldEvidence.value must be a date (not datetime) "
                f"when value_type is DATE, got {type(value).__name__}"
            )
        if not isinstance(value, date) or isinstance(value, bool):
            raise TypeError(
                "FieldEvidence.value must be a date when value_type is DATE, "
                f"got {type(value).__name__}"
            )
        return value
    raise ValueError(f"unsupported FieldValueType: {value_type!r}")


__all__ = [
    "EtfProfile",
    "FieldEvidence",
    "FieldEvidenceSource",
    "FieldKey",
    "FieldValueType",
    "compute_field_evidence_hash",
]
