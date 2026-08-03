"""Deterministic provider selection (PR-05).

The :func:`select_providers` helper is a pure, side-effect free
function that takes a sequence of
:class:`invest_pipeline.provider_catalog.ProviderDeclaration` and a
:class:`invest_pipeline.provider_routing.datasets.Dataset` and
returns the sorted tuple of declarations eligible to serve that
dataset.

The selection applies three documented rules:

1. **Capability match.** The declaration must advertise the
   :class:`invest_pipeline.provider_catalog.ProviderCapability` the
   dataset requires. A declaration missing the capability is filtered
   out before any other rule is evaluated.
2. **Default-enable gate.** When ``enabled_only=True`` (the default)
   the declaration's ``enabled_by_default`` flag must be ``True``.
   Real providers in V2 default to ``False`` per
   ``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`` §6, so the
   default gate keeps the function safe to call in tests and dev
   without ever silently enabling a third-party API.
3. **Research-only rejection for ETF daily bars.** When
   ``exclude_research_only_for_etf_daily_bars=True`` (the default) a
   declaration whose role is
   :attr:`invest_pipeline.provider_catalog.ProviderRole.RESEARCH_ONLY`
   is rejected for the ETF daily-bars / ETF instruments surfaces
   even when it advertises the required capability. This mirrors the
   matrix §5.4 "no research-only source as production SLA" rule and
   the plan PR-05 "rejects research-only providers for ETF daily
   bars" constraint. The rule is **not** applied to
   ``INDEX_DAILY_BARS`` / ``RESEARCH`` / ``MARKET_SNAPSHOT`` because
   the only research-only source for those surfaces is the MCP
   research feed itself (RssCast for index / research, Quicktiny for
   market snapshot), and the V2 plan reserves those roles for it.

The output is a tuple sorted by ``provider_key`` in ascending order
so two callers running the same input receive bit-for-bit identical
results — a property the
:mod:`invest_pipeline.provider_routing.coverage` module relies on for
its deterministic output.

The module deliberately does **not** consult the network, the
database or any other side-effecting source. It also does not
construct adapters; :func:`select_providers` only filters
declarations, leaving the existing
:func:`invest_pipeline.provider_factory.build_provider` as the
authoritative runtime construction path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from invest_pipeline.provider_catalog import (
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)
from invest_pipeline.provider_routing.datasets import (
    Dataset,
    required_capability_for,
)


class NoEligibleProviderError(LookupError):
    """Raised when no provider declaration matches the routing request.

    The exception carries the :class:`Dataset` value (or its string
    form) as the first argument so callers and tests can assert on
    the request without re-parsing the error message.
    """

    def __init__(self, dataset: Dataset, message: str) -> None:
        super().__init__(dataset.value, message)
        self.dataset = dataset


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    """Immutable description of a single routing decision.

    The dataclass pins the inputs the routing layer needs so a future
    PR can extend the selection (for example with per-symbol
    policies) without breaking the public tuple signature. The
    :func:`select_providers` function also accepts the two raw
    arguments (:class:`Dataset` and
    :class:`Sequence`\\ [:class:`ProviderDeclaration`]) directly for
    convenience; the dataclass is the explicit form.
    """

    dataset: Dataset
    declarations: tuple[ProviderDeclaration, ...]
    enabled_only: bool = True
    exclude_research_only_for_etf_daily_bars: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.dataset, Dataset):
            raise TypeError(
                f"RoutingRequest.dataset must be a Dataset instance, "
                f"got {type(self.dataset).__name__}"
            )
        for declaration in self.declarations:
            if not isinstance(declaration, ProviderDeclaration):
                raise TypeError(
                    "RoutingRequest.declarations must contain only "
                    "ProviderDeclaration instances, got "
                    f"{type(declaration).__name__}"
                )


_ETF_DAILY_BARS_DATASETS: frozenset[Dataset] = frozenset(
    {Dataset.ETF_DAILY_BARS, Dataset.ETF_INSTRUMENTS}
)
"""Datasets the research-only-rejection rule applies to.

The set is the explicit list of "ETF production" surfaces; the rule
must be applied to ETF daily bars and ETF master data (which is what
``etf_instruments`` resolves to in the routing layer) but **not** to
the index / research / market-snapshot surfaces where the
research-only MCP sources are the intended providers.
"""


def _is_research_only(declaration: ProviderDeclaration) -> bool:
    """Return ``True`` iff ``declaration`` carries the research-only role."""

    return declaration.role is ProviderRole.RESEARCH_ONLY


def _required_capability(dataset: Dataset) -> ProviderCapability:
    """Thin wrapper over :func:`required_capability_for` for testability."""

    return required_capability_for(dataset)


def select_providers(
    declarations: Sequence[ProviderDeclaration] | RoutingRequest,
    dataset: Dataset | None = None,
    *,
    enabled_only: bool = True,
    exclude_research_only_for_etf_daily_bars: bool = True,
) -> tuple[ProviderDeclaration, ...]:
    """Return the eligible provider declarations for ``dataset``.

    Parameters
    ----------
    declarations:
        Either a sequence of :class:`ProviderDeclaration` instances or
        a pre-built :class:`RoutingRequest`. When a
        :class:`RoutingRequest` is passed, the remaining keyword
        arguments are ignored; the dataclass' own flags win.
    dataset:
        Dataset to select for. Required when ``declarations`` is a
        raw sequence; ignored when ``declarations`` is a
        :class:`RoutingRequest`.
    enabled_only:
        When ``True`` (the default) declarations with
        ``enabled_by_default=False`` are filtered out so the function
        never silently enables a third-party API. Pass ``False`` for
        operator-facing flows that want to inspect the full eligible
        set (the matrix §6 default-off rule is then re-imposed
        downstream by the runtime factory).
    exclude_research_only_for_etf_daily_bars:
        When ``True`` (the default) a declaration whose role is
        :attr:`ProviderRole.RESEARCH_ONLY` is rejected for the ETF
        daily-bars and ETF-instruments surfaces, mirroring matrix §5.4
        and the plan PR-05 "rejects research-only providers for ETF
        daily bars" rule. The rule is **not** applied to the index /
        research / market-snapshot surfaces.

    Returns
    -------
    tuple[ProviderDeclaration, ...]
        Eligible declarations, sorted by ``provider_key`` in
        ascending order. The result is always a tuple (never a list)
        so callers cannot accidentally mutate it, and the order is
        deterministic across Python sessions and platforms.

    Raises
    ------
    TypeError
        When ``declarations`` is neither a
        :class:`RoutingRequest` nor a sequence of
        :class:`ProviderDeclaration`, or when ``dataset`` is not a
        :class:`Dataset` instance.
    ValueError
        When ``declarations`` is a raw sequence but ``dataset`` is
        ``None``.
    NoEligibleProviderError
        When no declaration matches the routing request. The error
        carries the dataset string as its first argument so tests can
        assert on the request directly.
    """

    if isinstance(declarations, RoutingRequest):
        request = declarations
    else:
        if dataset is None:
            raise ValueError(
                "select_providers requires a dataset when declarations "
                "is a raw sequence; pass RoutingRequest(dataset=...) "
                "for the explicit form"
            )
        request = RoutingRequest(
            dataset=dataset,
            declarations=tuple(declarations),
            enabled_only=enabled_only,
            exclude_research_only_for_etf_daily_bars=exclude_research_only_for_etf_daily_bars,
        )

    required_capability: ProviderCapability = _required_capability(request.dataset)
    reject_research_only = (
        request.exclude_research_only_for_etf_daily_bars
        and request.dataset in _ETF_DAILY_BARS_DATASETS
    )

    eligible: list[ProviderDeclaration] = []
    for declaration in request.declarations:
        if required_capability not in declaration.capabilities:
            continue
        if request.enabled_only and not declaration.enabled_by_default:
            continue
        if reject_research_only and _is_research_only(declaration):
            continue
        eligible.append(declaration)

    if not eligible:
        raise NoEligibleProviderError(
            request.dataset,
            f"no provider declaration matches dataset {request.dataset.value!r} "
            f"(required capability {required_capability.value!r}, "
            f"enabled_only={request.enabled_only}, "
            f"exclude_research_only_for_etf_daily_bars="
            f"{request.exclude_research_only_for_etf_daily_bars})",
        )

    eligible.sort(key=lambda declaration: declaration.provider_key)
    return tuple(eligible)


__all__ = [
    "NoEligibleProviderError",
    "RoutingRequest",
    "select_providers",
]
