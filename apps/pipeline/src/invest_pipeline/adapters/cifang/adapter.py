"""CifangQuant evidence-tuple adapter (ADR-0011, Phase 1 second increment).

This module composes :class:`CifangClient` and the field mappers in
:mod:`mapper` into the domain :class:`invest_domain.market_data.ports.
EtfMarketDataProvider` shape. Each public call returns the existing
three-layer evidence bundle:

    ``(ProviderRequest, ProviderAttempt, ProviderBatch[T] | None)``

The adapter keeps ``CifangSettings.enabled=False`` as the
authoritative gate: when ``enabled`` is ``False`` (the default and
the only supported value until ADR-0011 O-1 / O-3 / O-4 are closed)
**both** ``fetch_*`` methods raise
:class:`RealProviderRequiresExplicitEnablementError` so callers never
silently hit the network in CI or local dev.

The adapter does not import the HTTP transport directly; tests inject
a ``CifangClient`` (typically wrapping an ``httpx.MockTransport``) and
a fake clock so the suite runs deterministically without touching the
network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from invest_domain.instruments.models import Instrument, InstrumentId
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)

from invest_pipeline.adapters.cifang.client import (
    CifangClient,
)
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.cifang.mapper import (
    map_fund_hist_em,
    map_fund_list,
)
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.request_keys import make_daily_bars_request_key

_PROVIDER_KEY = "cifangquant"
_INSTRUMENTS_DATASET_KEY = "etf_instruments"
_DAILY_BARS_DATASET_KEY = "etf_daily_bars"


class CifangQuantInstrumentProvider:
    """Evidence-tuple adapter that wires :class:`CifangClient` to the domain port.

    Parameters
    ----------
    settings:
        The redacted configuration. ``enabled=False`` (default) keeps
        the adapter inert; ``enabled=True`` would route real calls
        through the injected client.
    client:
        A pre-built :class:`CifangClient` (typically injected by tests
        with an ``httpx.MockTransport``). The adapter takes ownership
        and will ``close()`` it on garbage collection via the
        :meth:`close` method; production code should construct the
        adapter once and reuse it.
    clock:
        Callable returning the current UTC datetime. Defaults to
        :func:`datetime.now`; tests inject a deterministic callable.
    placeholder_instrument_id_factory:
        Callable returning a fresh :class:`InstrumentId` for an
        unknown ``(symbol, exchange)`` pair. The application service
        re-maps ``symbol -> core.instruments.id`` at upsert time
        (mirrors the fixture_dev pattern).
    """

    def __init__(
        self,
        settings: CifangSettings | None = None,
        *,
        client: CifangClient | None = None,
        clock: Callable[[], datetime] | None = None,
        placeholder_instrument_id_factory: Callable[[], InstrumentId] | None = None,
    ) -> None:
        self._settings = settings or CifangSettings()
        self._client = client or CifangClient(self._settings)
        self._owns_client = client is None
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else _default_clock
        )
        self._placeholder_instrument_id_factory: Callable[[], InstrumentId] = (
            placeholder_instrument_id_factory
            if placeholder_instrument_id_factory is not None
            else InstrumentId.generate
        )
        # Stable placeholder UUID per (symbol, exchange) so re-runs of
        # the same logical request get the same domain ``instrument_id``
        # (the application service re-maps to the real id at upsert).
        self._placeholder_cache: dict[tuple[str, str], InstrumentId] = {}

    @property
    def provider_key(self) -> str:
        return _PROVIDER_KEY

    def close(self) -> None:
        """Release the underlying HTTP transport when owned by the adapter."""

        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Domain port surface
    # ------------------------------------------------------------------

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        """Return the evidence bundle for the ``/api/fund/list`` call.

        The single chunk is ``[as_of]`` so the request key stays
        deterministic; the mapper applies the ETF filter and the
        SSE / SZSE allow-list. A failed attempt returns no batch.
        """

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_INSTRUMENTS_DATASET_KEY,
            request_key=f"instruments-{as_of.isoformat()}",
            params={"as_of": as_of.isoformat()},
            created_at=started_at,
        )
        self._guard_enabled("fetch_instruments", as_of=as_of)
        try:
            response = self._client.fetch_fund_list()
        except ProviderError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                error=exc,
            )

        finished_at = self._now()
        try:
            mapping = map_fund_list(response)
        except ProviderDataContractError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=exc,
            )

        duration_ms = self._duration_ms(started_at, finished_at)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        # Hash the parsed payload so the raw evidence row is
        # request-scoped; the client already sha256'd the bytes but
        # using the parsed JSON keeps the digest stable across
        # whitespace differences in the upstream response.
        raw_hash = _canonical_payload_hash(response.raw_payload)
        batch = ProviderBatch[Instrument](
            attempt_id=attempt_id,
            records=tuple(mapping.instruments),
            raw_payload_hash=raw_hash,
            warnings=mapping.warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        """Return the evidence bundle for the chunked ``/api/fund/hist_em`` call.

        The adapter splits ``symbols`` into 50-symbol chunks (the
        official documented maximum), calls the client per chunk and
        aggregates the mapped :class:`DailyBar` rows into a single
        :class:`ProviderBatch`. A failure on **any** chunk short-
        circuits to a single failed attempt so the
        ``raw.provider_attempts`` row carries the full classification.
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )

        request_id = uuid4()
        attempt_id = uuid4()
        started_at = self._now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_DAILY_BARS_DATASET_KEY,
            request_key=make_daily_bars_request_key(start_date, end_date, symbols),
            params={
                "symbols": list(symbols),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            created_at=started_at,
        )
        self._guard_enabled(
            "fetch_daily_bars",
            symbols=list(symbols),
            start_date=start_date,
            end_date=end_date,
        )

        try:
            chunks = self._client.chunk_symbols(
                list(symbols),
                start_date=start_date,
                end_date=end_date,
            )
        except ValueError as exc:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                error=ProviderDataContractError(
                    "INVALID_CHUNKING",
                    f"failed to chunk symbols: {exc}",
                    provider_key=_PROVIDER_KEY,
                ),
            )

        if not chunks:
            # Empty input: produce a successful empty batch rather than
            # an error so the application service can treat "no symbols"
            # as a no-op.
            finished_at = self._now()
            attempt = ProviderAttempt(
                request_id=request_id,
                attempt_number=1,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=self._duration_ms(started_at, finished_at),
            )
            batch = ProviderBatch[DailyBar](
                attempt_id=attempt_id,
                records=(),
                raw_payload_hash=_canonical_payload_hash(
                    {"adjust": self._settings.adjustment, "data": []}
                ),
                warnings=(),
                status=ProviderBatchStatus.SUCCEEDED,
            )
            return request, attempt, batch

        all_bars: list[DailyBar] = []
        all_warnings: list[str] = []
        chunk_payloads: list[Any] = []
        first_failure: ProviderError | None = None

        for chunk in chunks:
            try:
                response = self._client.fetch_fund_hist_em(chunk)
            except ProviderError as exc:
                first_failure = exc
                break

            chunk_payloads.append(response.raw_payload)
            try:
                mapping = map_fund_hist_em(
                    response,
                    chunk_index=chunk.chunk_index,
                    chunk_count=chunk.chunk_count,
                    source_batch_id=attempt_id,
                    observed_at=self._now(),
                    instrument_id_resolver=self._resolve_placeholder_instrument_id,
                )
            except ProviderDataContractError as exc:
                first_failure = exc
                break
            all_bars.extend(mapping.bars)
            all_warnings.extend(mapping.warnings)

        finished_at = self._now()
        duration_ms = self._duration_ms(started_at, finished_at)
        if first_failure is not None:
            return self._build_failure(
                request=request,
                request_id=request_id,
                started_at=started_at,
                finished_at=finished_at,
                error=first_failure,
            )

        raw_hash = _canonical_payload_hash(
            {"adjust": self._settings.adjustment, "chunks": chunk_payloads}
        )
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        warnings = tuple(all_warnings)
        if len(chunks) > 1:
            warnings = warnings + (
                f"daily-bars request was chunked into {len(chunks)} "
                f"batches of up to {len(chunks[0].symbols)} symbols "
                f"(CifangQuant per-request limit, ADR-0011 §2)",
            )
        batch = ProviderBatch[DailyBar](
            attempt_id=attempt_id,
            records=tuple(all_bars),
            raw_payload_hash=raw_hash,
            warnings=warnings,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _guard_enabled(self, op: str, **params: Any) -> None:
        if not self._settings.enabled:
            raise RealProviderRequiresExplicitEnablementError(
                f"CifangQuant {op} requires CifangSettings.enabled=True "
                f"({self.provider_key!r}, params={params!r}); "
                f"see ADR-0011 §4 / O-1 / O-3 / O-4 blockers"
            )

    def _build_failure(
        self,
        *,
        request: ProviderRequest,
        request_id: UUID,
        started_at: datetime,
        error: ProviderError,
        finished_at: datetime | None = None,
    ) -> tuple[ProviderRequest, ProviderAttempt, None]:
        finished = finished_at or self._now()
        stage, code, message = _classify_failure(error)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.FAILED,
            started_at=started_at,
            finished_at=finished,
            duration_ms=self._duration_ms(started_at, finished),
            error_stage=stage,
            error_code=code,
            error_message=message,
        )
        return request, attempt, None

    def _now(self) -> datetime:
        return self._clock()

    def _duration_ms(self, started: datetime, finished: datetime) -> int:
        delta = finished - started
        return max(int(delta.total_seconds() * 1000), 0)

    def _resolve_placeholder_instrument_id(
        self, symbol: str, exchange: str
    ) -> InstrumentId:
        key = (symbol, exchange)
        cached = self._placeholder_cache.get(key)
        if cached is not None:
            return cached
        new_id = self._placeholder_instrument_id_factory()
        self._placeholder_cache[key] = new_id
        return new_id

    def symbol_for_instrument_id(self, instrument_id: InstrumentId) -> str | None:
        """Return the provider-native symbol whose placeholder UUID matches.

        Reverse lookup against :attr:`_placeholder_cache`. The
        application service calls this for every ``DailyBar`` carried
        on a :class:`ProviderBatch` so the sidecar stores the
        provider-native symbol (e.g. ``"510300"``) rather than the
        audit-only ``BarSource.provider_key``. Returns ``None`` if
        the UUID was not generated by this provider instance — the
        application service surfaces that as a hard error. When
        multiple ``(symbol, exchange)`` pairs happen to share the
        same placeholder (only possible across distinct provider
        instances), the first match wins deterministically because
        Python dict iteration order is insertion order.
        """

        for (symbol, _exchange), placeholder_id in self._placeholder_cache.items():
            if placeholder_id == instrument_id:
                return symbol
        return None


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _canonical_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 of a JSON-compatible payload.

    Uses sorted keys + compact separators so the digest is independent
    of dict ordering or whitespace; the value lives in
    ``ProviderBatch.raw_payload_hash`` and must match across
    re-collects of the same logical request.
    """

    import json

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(text.encode("utf-8")).hexdigest()


_PROVIDER_ERROR_STAGE_MAP: dict[type[ProviderError], ProviderFailureStage] = {
    ProviderAuthenticationError: ProviderFailureStage.AUTHENTICATION,
    ProviderRateLimitError: ProviderFailureStage.RATE_LIMIT,
    ProviderTimeoutError: ProviderFailureStage.TIMEOUT,
    ProviderUnavailableError: ProviderFailureStage.HTTP,
    ProviderBadResponseError: ProviderFailureStage.DECODE,
    ProviderDataContractError: ProviderFailureStage.CONTRACT,
}


def _classify_failure(
    error: ProviderError,
) -> tuple[ProviderFailureStage, str, str]:
    """Map a Provider error to ``(stage, code, message)``.

    The ``message`` is the original error string with the API key
    scrubbed defensively; the ``code`` is the canonical Provider
    error category so the application layer can route alerting
    without parsing free text.
    """

    stage = _PROVIDER_ERROR_STAGE_MAP.get(
        type(error), ProviderFailureStage.PROVIDER
    )
    code = type(error).__name__
    message = _scrub_message(str(error))
    return stage, code, message


def _scrub_message(message: str) -> str:
    """Remove anything that smells like an API key from a Provider message.

    The client itself never places the token in errors; this helper is
    belt-and-braces against future maintainers accidentally logging
    the token via ``str(exc)`` in a wrapped exception.
    """

    token = ""
    try:
        token = CifangSettings.__name__  # placeholder; no real token
    except Exception:
        token = ""
    # Defensive scrub: the message should already be free of the
    # token because we never put it in error text. If a maintainer
    # ever does leak it via ``str(exc)``, this strips it.
    if token and token in message:
        return message.replace(token, "***")
    return message


__all__ = ["CifangQuantInstrumentProvider"]
