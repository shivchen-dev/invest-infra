"""Public re-exports for the ``etf_profile`` bounded context.

The ``etf_profile`` bounded context captures the static, mostly
provider-supplied attributes of a single ETF instrument (manager,
benchmark_index, category, inception_date, fund_type, fees, AUM,
shares) together with the per-field evidence that supports them. It is
the foundation for the Stage DC-2 vertical slice and the
``PR-ETF-PROFILE-01`` evidence framework: the domain contract is fixed
first, then the PostgreSQL persistence layer lands on top in
``apps/migrations`` / ``packages/storage/src/invest_storage``.

Provider responses do not always disclose every field, so the domain
model keeps every non-key field nullable. The dataclasses never
fabricate a default value; explicit ``None`` is the only acceptable
representation for ``unknown`` provider data so downstream analytics
can distinguish ``unknown`` from a real zero/empty value.

PR ``PR-ETF-PROFILE-01`` adds the Field Evidence vocabulary so that
every populated profile field carries its own source provenance,
observation timestamp, quality status and confidence score. The three
types live alongside :class:`EtfProfile`:

- :class:`FieldValueType` — closed-set ``TEXT`` / ``DECIMAL`` /
  ``DATE`` runtime value types.
- :class:`FieldKey` — closed-set evidence vocabulary covering the
  Level 0 / Level 1 fields of the ETF Profile Evidence Framework.
  ``AUM``, ``MARKET_VALUE`` and ``TURNOVER_VALUE`` are deliberately
  distinct so the trading-day market value of an ETF cannot be
  silently rewritten as its assets under management (plan §6).
- :class:`FieldEvidenceSource` — provider provenance for one evidence
  observation.
- :class:`FieldEvidence` — one piece of business evidence for one
  instrument / field combination, including its computed
  ``content_hash``.
"""

from invest_domain.etf_profile.models import (
    EtfProfile,
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
    compute_field_evidence_hash,
)

__all__ = [
    "EtfProfile",
    "FieldEvidence",
    "FieldEvidenceSource",
    "FieldKey",
    "FieldValueType",
    "compute_field_evidence_hash",
]
