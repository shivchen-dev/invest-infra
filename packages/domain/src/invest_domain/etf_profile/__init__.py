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

PR ``PR-ETF-PROFILE-03`` adds the :class:`ProfileResolver` so that one
or more :class:`FieldEvidence` rows for a single instrument can be
collapsed into the canonical ``EtfProfile`` row used by the API. The
resolver carries:

- :class:`ProviderPriorityPolicy` — audit-friendly provider-tier
  ordering for the prioritised fields (``manager`` /
  ``benchmark_index`` / ``aum``). Fields outside the explicit table
  use a stable conservative fallback rule.
- :class:`ResolvedField` / :class:`ProfileResolution` — frozen /
  slotted per-field and per-instrument results with all candidate
  evidence preserved verbatim and any conflict rows flagged instead
  of silently overwritten (plan §5).
"""

from invest_domain.etf_profile.models import (
    EtfProfile,
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
    compute_field_evidence_hash,
)
from invest_domain.etf_profile.resolver import (
    DEFAULT_PROVIDER_PRIORITY_POLICY,
    ProfileResolution,
    ProfileResolver,
    ProviderPriorityPolicy,
    ResolutionPolicyError,
    ResolutionStatus,
    ResolvedField,
    resolve_etf_profile_evidence,
)

__all__ = [
    "DEFAULT_PROVIDER_PRIORITY_POLICY",
    "EtfProfile",
    "FieldEvidence",
    "FieldEvidenceSource",
    "FieldKey",
    "FieldValueType",
    "ProfileResolution",
    "ProfileResolver",
    "ProviderPriorityPolicy",
    "ResolutionPolicyError",
    "ResolutionStatus",
    "ResolvedField",
    "compute_field_evidence_hash",
    "resolve_etf_profile_evidence",
]
