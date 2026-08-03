"""Guarded historical ETF daily-bars backfill CLI.

Manual driver for replaying ``write_etf_daily_bars_raw`` and
``upsert_etf_daily_bars`` over a bounded historical date range without
ever invoking the Dagster ``personal_etf_daily_job``, the
candidate-pool / input-snapshot / evidence-pack / AI-research assets,
or any other pipeline slice that the personal daily run drives.

Invoked as::

    python -m invest_pipeline.historical_daily_bars_cli \\
        --start-date 2016-01-01 \\
        --end-date 2016-12-31 \\
        --confirm-network

The CLI is intentionally safe-by-default:

* ``--start-date`` and ``--end-date`` are both required and must parse
  as ``YYYY-MM-DD``; ``end_date`` must not be in the future and
  ``start_date`` must not be after ``end_date``. The CLI raises
  :class:`HistoricalDailyBarsCLIConfigError` (translated into exit
  code ``2``) for any of these without importing Dagster or touching
  any database state.
* ``--universe`` is an optional CLI override that maps to
  ``INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH`` **before**
  :func:`invest_pipeline.config.get_settings` is first hit (settings
  are ``lru_cache``-d). The default remains the existing
  ``config/personal-universe.yaml``.
* Real-provider / network safety preserves the ADR-0011 semantics:
  ``--confirm-network`` alone never enables
  :class:`CifangQuantInstrumentProvider`. If the selected provider key
  is ``cifangquant`` both ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and
  ``--confirm-network`` must be set; either missing produces a single
  concise ``refused:`` line on stderr and an exit code of ``2``.
  ``fixture_dev`` runs never need ``--confirm-network``.
* The CLI never prints the API key, raw payload, request headers,
  exception reprs (which may embed secrets) or absolute filesystem
  paths. Errors are surfaced as a single short stderr line plus a
  non-zero exit code; success emits one redacted JSON line per
  completed chunk followed by a single redacted final-summary line.
* Idempotency is delegated to the existing
  :func:`invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw`
  (reuses ``raw.provider_requests`` via ``get_or_create``) and
  :func:`invest_pipeline.etf_daily_bars.upsert_etf_daily_bars`
  (ADR-0006 §3 revision rules). The CLI never opens a second
  persistence path or invents its own request key — the upsert is
  keyed on the request_key the provider stamped on the
  ``raw.provider_requests`` row ``write_etf_daily_bars_raw`` just
  persisted.
* Failures are fail-closed: a chunk whose underlying attempt is
  ``failed`` or whose persisted request has no successful attempt
  stops the backfill at the first such chunk and returns a non-zero
  exit code. No chunks after the failure are attempted.

The corresponding Makefile target is ``historical-daily-bars-backfill``.
See the sibling tests (``tests/unit/test_historical_daily_bars_cli.py``)
for the supported behaviour and redaction guarantees.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol
from uuid import UUID

from invest_pipeline.clock import market_today
from invest_pipeline.config import get_settings
from invest_pipeline.etf_daily_bars import (
    upsert_etf_daily_bars,
    write_etf_daily_bars_raw,
)
from invest_pipeline.personal_universe import (
    PersonalUniverse,
    PersonalUniverseError,
    load_personal_universe,
)
from invest_pipeline.provider_factory import build_provider

_PROVIDER_KEY_ENV = "INVEST_PIPELINE_PROVIDER_KEY"
_CIFANG_ENABLED_ENV = "INVEST_PIPELINE_CIFANG_ENABLED"
_UNIVERSE_ENV = "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"

_FIXTURE_DEV_KEY = "fixture_dev"
_CIFANG_KEY = "cifangquant"
_DAILY_BARS_DATASET_KEY = "etf_daily_bars"

_REDACTED = "***"

_MAX_CHUNK_CALENDAR_DAYS = 90


class HistoricalDailyBarsCLIConfigError(Exception):
    """Raised when the CLI inputs are incomplete or unsafe.

    The CLI translates this into an exit code of ``2`` and a single
    short line on stderr. It is **not** a provider-level error; the
    CLI refuses to construct the provider or open any database
    connection whenever this is raised, so no Dagster machinery or
    provider is ever invoked on a misconfigured run.
    """


class _ChunkRunner(Protocol):
    """Surface :func:`run_backfill` needs to execute one bounded chunk.

    Tests inject a stub that records the ``(chunk_start, chunk_end)``
    pair it was asked to handle and returns canned
    :class:`_ChunkResult` records; production uses
    :class:`_DefaultChunkRunner`, which wraps a real provider plus the
    configured ``session_factory``.
    """

    @property
    def provider_key(self) -> str: ...

    def run_chunk(
        self,
        *,
        symbols: Sequence[str],
        chunk_start: date,
        chunk_end: date,
    ) -> _ChunkResult: ...


@dataclass(frozen=True, slots=True)
class _ChunkResult:
    """Return shape of :meth:`_ChunkRunner.run_chunk`.

    Mirrors the contract a successful or failed chunk exposes back to
    :func:`run_backfill` so the JSON summary builder has no need to
    introspect either the raw evidence tuple or the
    :class:`UpsertSummary` directly.
    """

    provider_key: str
    chunk_start: date
    chunk_end: date
    request_key: str
    request_id: UUID
    attempt_id: UUID
    batch_id: UUID | None
    request_status: str
    attempt_status: str
    record_count: int
    upsert_inserted: int
    upsert_skipped: int


def _scrub(message: str, token: str) -> str:
    """Return ``message`` with every ``token`` occurrence replaced by :data:`_REDACTED`.

    Used to scrub the configured Cifang API key out of any leaked text
    before it reaches stderr; the function is intentionally a no-op
    when ``token`` is empty so the test surface stays predictable.
    """

    if not token or not message:
        return message
    return message.replace(token, _REDACTED)


def _resolve_provider_key(env: Any) -> str:
    """Return the configured provider key, falling back to ``fixture_dev``.

    Reads the mapping directly so callers can drive the function in
    tests without touching :data:`os.environ`.
    """

    if env is None:
        env = os.environ
    return str(env.get(_PROVIDER_KEY_ENV, _FIXTURE_DEV_KEY) or _FIXTURE_DEV_KEY)


def _cifang_enabled(env: Any) -> bool:
    """Return whether the Cifang opt-in flag is set in ``env``.

    Accepts the same ``1`` / ``true`` / ``yes`` / ``on`` values the
    :mod:`invest_pipeline.personal_daily_cli` accepts so operators see
    one consistent convention across the opt-in CLIs.
    """

    if env is None:
        env = os.environ
    value = env.get(_CIFANG_ENABLED_ENV, "")
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _configured_cifang_token() -> str:
    """Read the configured token only for error-message scrubbing.

    The lookup is best-effort: a missing / unreadable token returns an
    empty string so the caller never crashes on configuration errors
    while attempting to scrub them.
    """

    try:
        from invest_pipeline.adapters.cifang.config import CifangSettings

        return CifangSettings().api_key.get_secret_value()
    except Exception:
        return ""


def validate_provider_opt_in(
    *,
    provider_key: str,
    cifang_enabled: bool | None,
    confirm_network: bool,
) -> None:
    """Reject the run unless the real-provider opt-in gates are aligned.

    Three independent checks mirror the ADR-0011 semantics preserved
    by :mod:`invest_pipeline.personal_daily_cli`:

    * If the selected provider is :data:`_FIXTURE_DEV_KEY` the CLI
      never reaches the network regardless of ``--confirm-network``.
    * If the selected provider is :data:`_CIFANG_KEY`,
      ``--confirm-network`` alone **never** enables the provider; both
      ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and ``--confirm-network``
      must be set.
    * Any other provider key is rejected; the contract keeps the set
      of supported providers to the factory's declared
      :data:`invest_pipeline.provider_factory.KNOWN_PROVIDER_KEYS`.

    The function never touches the network and never reads the Cifang
    API key.
    """

    if provider_key == _FIXTURE_DEV_KEY:
        return
    if provider_key == _CIFANG_KEY:
        if not cifang_enabled:
            raise HistoricalDailyBarsCLIConfigError(
                f"{_CIFANG_ENABLED_ENV}=true is required to run the "
                "historical daily-bars backfill with provider=cifangquant "
                "(ADR-0011 §3); set it to acknowledge the real-API opt-in"
            )
        if not confirm_network:
            raise HistoricalDailyBarsCLIConfigError(
                "--confirm-network is required to run the historical "
                "daily-bars backfill with provider=cifangquant"
            )
        return
    raise HistoricalDailyBarsCLIConfigError(
        f"{_PROVIDER_KEY_ENV}={provider_key!r} is not supported by the "
        "historical daily-bars CLI; expected one of "
        f"{_FIXTURE_DEV_KEY!r} or {_CIFANG_KEY!r}"
    )


def parse_iso_date(raw: str, *, field_name: str, today: date) -> date:
    """Parse a ``YYYY-MM-DD`` value into a :class:`date` and reject future dates.

    Pure so unit tests can drive it with arbitrary strings and a fake
    ``today`` without touching the environment or Dagster. The
    ``field_name`` argument carries through into error messages so the
    operator knows which argument was misconfigured.
    """

    if not isinstance(raw, str):
        raise HistoricalDailyBarsCLIConfigError(
            f"--{field_name} must be a string"
        )
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise HistoricalDailyBarsCLIConfigError(
            f"--{field_name} must be YYYY-MM-DD: {exc}"
        ) from exc
    if parsed > today:
        raise HistoricalDailyBarsCLIConfigError(
            f"--{field_name} must not be in the future "
            f"(got {parsed.isoformat()}, today is {today.isoformat()})"
        )
    return parsed


def validate_range(
    *,
    start_date: date,
    end_date: date,
    today: date,
) -> None:
    """Reject inverted or future-spanning :class:`date` ranges.

    Re-applies the same ``end_date`` future check after
    :func:`parse_iso_date` so a worker who calls this helper directly
    (e.g. from a unit test) sees the same semantic guard the CLI
    imposes. ``start_date == end_date`` (a single-day backfill) is
    accepted; the chunker simply emits a single 1-day chunk.
    """

    if start_date > end_date:
        raise HistoricalDailyBarsCLIConfigError(
            f"--start-date ({start_date.isoformat()}) must not be after "
            f"--end-date ({end_date.isoformat()})"
        )
    if end_date > today:
        raise HistoricalDailyBarsCLIConfigError(
            f"--end-date must not be in the future "
            f"(got {end_date.isoformat()}, today is {today.isoformat()})"
        )


def chunk_date_range(
    start_date: date,
    end_date: date,
    *,
    max_days: int = _MAX_CHUNK_CALENDAR_DAYS,
) -> list[tuple[date, date]]:
    """Split ``[start_date, end_date]`` into bounded inclusive chunks.

    Each emitted ``(chunk_start, chunk_end)`` tuple covers at most
    ``max_days`` calendar days inclusive of both endpoints; the chunk
    generator advances ``chunk_start`` to ``chunk_end + 1 day`` so the
    union of the chunks is exactly ``[start_date, end_date]`` with no
    gaps and no overlap. ``max_days <= 0`` is rejected so callers
    cannot accidentally request an infinite loop.

    Exposed for tests so the chunking behaviour can be pinned without
    running the full CLI pipeline; the default of 90 calendar days is
    the same maximum the production CLI enforces.
    """

    if max_days <= 0:
        raise ValueError(f"max_days must be positive, got {max_days}")
    if start_date > end_date:
        raise ValueError(
            f"start_date ({start_date.isoformat()}) must be on or before "
            f"end_date ({end_date.isoformat()})"
        )

    chunks: list[tuple[date, date]] = []
    cursor = start_date
    stride = timedelta(days=max_days - 1)
    while cursor <= end_date:
        chunk_end = min(cursor + stride, end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def validate_universe(universe: PersonalUniverse) -> tuple[str, ...]:
    """Return the tuple of symbols to backfill or raise on an empty universe.

    The personal-universe loader already returns a deduplicated sorted
    tuple; the function adds only the empty-symbols guard so the CLI
    fails closed before invoking the provider on a misconfigured YAML.
    """

    if not universe.symbols:
        raise HistoricalDailyBarsCLIConfigError(
            "personal universe is empty; refusing to backfill zero symbols"
        )
    return tuple(universe.symbols)


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI.

    Exposed for tests so they can drive :func:`parse_args` without
    going through :data:`sys.argv`.
    """

    parser = argparse.ArgumentParser(
        prog="invest_pipeline.historical_daily_bars_cli",
        description=(
            "Guarded historical ETF daily-bars backfill. Replays "
            "write_etf_daily_bars_raw + upsert_etf_daily_bars over a bounded "
            "historical date range in chunks of at most 90 calendar days; "
            "never runs the personal daily Dagster job, the candidate pool, "
            "input snapshot, evidence pack, or AI research assets. Requires "
            "--start-date, --end-date and --confirm-network (combined with "
            "INVEST_PIPELINE_CIFANG_ENABLED=true) for cifangquant; fixture "
            "runs never need --confirm-network."
        ),
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help=(
            "Earliest calendar date of the backfill window in YYYY-MM-DD; "
            "must be on or before --end-date."
        ),
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help=(
            "Latest calendar date of the backfill window in YYYY-MM-DD; "
            "must be on or after --start-date and must not be in the future."
        ),
    )
    parser.add_argument(
        "--universe",
        required=False,
        default=None,
        help=(
            "Optional path to a personal-universe YAML. Forwarded to "
            f"{_UNIVERSE_ENV} before get_settings() is first hit; the "
            "default is config/personal-universe.yaml."
        ),
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help=(
            "Explicit opt-in to hit a real provider. Required only when the "
            "selected provider (INVEST_PIPELINE_PROVIDER_KEY) is cifangquant; "
            "ignored for the deterministic fixture_dev provider."
        ),
    )
    return parser


def build_env_overrides(*, universe: str | None = None) -> dict[str, str]:
    """Return the env-var override implied by ``--universe``, if any.

    Pure so unit tests can compute the expected mapping without
    touching :data:`os.environ`; keys with a ``None`` / empty value
    are dropped so the caller can apply them without accidentally
    clearing unrelated variables.
    """

    overrides: dict[str, str] = {}
    if universe:
        overrides[_UNIVERSE_ENV] = str(universe)
    return overrides


def build_chunk_summary(result: _ChunkResult, *, chunk_index: int) -> str:
    """Return a single redacted JSON line describing one completed chunk.

    The function lifts only the documented safe fields off
    :class:`_ChunkResult` (provider key, chunk dates, request key,
    assigned UUIDs, request / attempt status, record count and
    upsert counts) and returns a deterministic ``sort_keys=True``
    JSON line that operators can scrape. The output never includes
    the API key, raw payload, headers or absolute filesystem paths.
    """

    payload = {
        "chunk_index": chunk_index,
        "chunk_start": result.chunk_start.isoformat(),
        "chunk_end": result.chunk_end.isoformat(),
        "provider": result.provider_key,
        "request_key": result.request_key,
        "request_id": str(result.request_id),
        "attempt_id": str(result.attempt_id),
        "batch_id": str(result.batch_id) if result.batch_id else None,
        "request_status": result.request_status,
        "attempt_status": result.attempt_status,
        "record_count": result.record_count,
        "upsert_inserted": result.upsert_inserted,
        "upsert_skipped": result.upsert_skipped,
        "status": (
            "succeeded" if result.attempt_status == "succeeded" else "failed"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_final_summary(
    *,
    provider_key: str,
    start_date: date,
    end_date: date,
    universe_count: int,
    total_chunks: int,
    completed_chunks: int,
    failed_chunk_index: int | None,
    status: str,
    inserted_total: int,
    skipped_total: int,
) -> str:
    """Return a single redacted JSON line describing the whole backfill.

    The function mirrors :func:`_build_chunk_summary`'s safe-by-default
    posture: only derived counts and identifiers survive into the
    output, and the keys are sorted so a downstream parser can rely
    on a stable schema. ``status`` is one of ``{"succeeded",
    "failed"}``.
    """

    payload = {
        "provider": provider_key,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "universe_count": universe_count,
        "total_chunks": total_chunks,
        "completed_chunks": completed_chunks,
        "failed_chunk_index": failed_chunk_index,
        "status": status,
        "inserted_total": inserted_total,
        "skipped_total": skipped_total,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class _DefaultChunkRunner:
    """Default :class:`_ChunkRunner` wiring the real provider + session factory.

    Each call to :meth:`run_chunk` opens one ``write_etf_daily_bars_raw``
    transaction (persisting the request, attempt and batch triple) and
    one ``upsert_etf_daily_bars`` transaction (resolving
    ``core.daily_bars`` from the sidecar). The two transactions are
    driven through the same ``session_factory`` so callers reuse the
    configured :class:`SqlAlchemyUnitOfWork` instead of inventing a new
    persistence path.

    When the runner is built by :func:`_build_default_runner` it
    receives the freshly-constructed SQLAlchemy ``engine`` as
    ``engine=``; :meth:`close` then disposes that engine so the CLI
    does not leak pool connections after ``run_backfill`` returns
    (including failure paths). Callers that supply their own engine
    (tests inject ``session_factory`` directly) pass ``engine=None``,
    which keeps ``close`` a no-op and avoids closing an engine the
    caller owns.
    """

    def __init__(
        self,
        provider: Any,
        session_factory: Any,
        *,
        engine: Any | None = None,
        dataset_key: str = _DAILY_BARS_DATASET_KEY,
        unit_of_work_factory: Any | None = None,
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._engine = engine
        self._dataset_key = dataset_key
        if unit_of_work_factory is None:
            from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

            unit_of_work_factory = SqlAlchemyUnitOfWork
        self._uow_factory = unit_of_work_factory

    @property
    def provider_key(self) -> str:
        return str(getattr(self._provider, "provider_key", _FIXTURE_DEV_KEY))

    def run_chunk(
        self,
        *,
        symbols: Sequence[str],
        chunk_start: date,
        chunk_end: date,
    ) -> _ChunkResult:
        raw = write_etf_daily_bars_raw(
            self._provider,
            self._session_factory,
            symbols=tuple(symbols),
            start_date=chunk_start,
            end_date=chunk_end,
            unit_of_work_factory=self._uow_factory,
        )

        # Re-open a fresh UoW solely to look up the request_key the
        # adapter stamped on the persisted request. We deliberately
        # avoid inventing a second persistence path: the upsert below
        # runs in another fresh UoW and reuses
        # ``invest_pipeline.etf_daily_bars.upsert_etf_daily_bars``
        # with the recovered key.
        with self._uow_factory(self._session_factory) as lookup_uow:
            stored_request = lookup_uow.provider_requests.get_by_id(raw.request_id)
        if stored_request is None:
            raise HistoricalDailyBarsCLIConfigError(
                "provider_requests row missing immediately after "
                "write_etf_daily_bars_raw; refusing to invent a "
                "request_key for the upsert"
            )
        request_key = str(stored_request.request_key)

        upsert_summary = upsert_etf_daily_bars(
            self._session_factory,
            provider_key=self.provider_key,
            dataset_key=self._dataset_key,
            request_key=request_key,
            unit_of_work_factory=self._uow_factory,
        )

        return _ChunkResult(
            provider_key=self.provider_key,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
            request_key=request_key,
            request_id=raw.request_id,
            attempt_id=raw.attempt_id,
            batch_id=raw.batch_id,
            request_status=raw.request_status,
            attempt_status=raw.attempt_status,
            record_count=raw.record_count,
            upsert_inserted=upsert_summary.inserted,
            upsert_skipped=upsert_summary.skipped,
        )

    def close(self) -> None:
        """Dispose the engine when the runner owns one.

        Only engines the runner itself constructed (via
        :func:`_build_default_runner`) are disposed here. When the
        caller supplied ``engine=None`` — the case for every test
        double that constructs ``_DefaultChunkRunner`` directly with a
        fake ``session_factory`` — the method stays a no-op so the CLI
        never closes an engine it did not create.
        """

        engine = self._engine
        if engine is None:
            return
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            dispose()


def run_backfill(
    *,
    runner: _ChunkRunner,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    today: date,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
    token: str = "",
    max_chunk_days: int = _MAX_CHUNK_CALENDAR_DAYS,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Execute the bounded historical backfill through ``runner``.

    The function is the only orchestrator the CLI needs once it has a
    validated range, a non-empty universe, and a pre-constructed
    :class:`_ChunkRunner`. It walks the date range in <=90-day
    inclusive chunks sequentially (no parallel requests, no
    concurrent provider calls), invokes ``runner.run_chunk`` once per
    chunk and emits one redacted JSON line per completed chunk plus a
    single final-summary line.

    Returns ``0`` on success, ``3`` when the underlying provider
    attempt or the post-write upsert lookup signals a failure, ``2``
    on a configuration error, and ``1`` on any other unrecoverable
    exception. ``sleep`` is exposed purely so future meta-orchestrators
    (e.g. a slow-mode runner for fixture_dev warm-up) can be injected
    without monkeypatching :data:`time.sleep`; ``None`` means "run
    back-to-back", which is the production contract.
    """

    def _scrub(message: str) -> str:
        if not token or not message:
            return message
        return message.replace(token, _REDACTED)

    if not symbols:
        print(
            "error: refusing to backfill zero symbols", file=stderr
        )
        return 2

    try:
        validate_range(start_date=start_date, end_date=end_date, today=today)
    except HistoricalDailyBarsCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    try:
        chunks = chunk_date_range(start_date, end_date, max_days=max_chunk_days)
    except ValueError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    if not chunks:
        print(
            "error: empty chunk plan for the given range; refusing to proceed",
            file=stderr,
        )
        return 2

    provider_key = runner.provider_key
    inserted_total = 0
    skipped_total = 0
    completed_chunks = 0

    for chunk_index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        try:
            result = runner.run_chunk(
                symbols=symbols,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
            )
        except HistoricalDailyBarsCLIConfigError as exc:
            print(
                f"error: chunk {chunk_index} ({chunk_start.isoformat()} -> "
                f"{chunk_end.isoformat()}): {_scrub(str(exc))}",
                file=stderr,
            )
            print(
                build_final_summary(
                    provider_key=provider_key,
                    start_date=start_date,
                    end_date=end_date,
                    universe_count=len(tuple(symbols)),
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    failed_chunk_index=chunk_index,
                    status="failed",
                    inserted_total=inserted_total,
                    skipped_total=skipped_total,
                ),
                file=stdout,
            )
            return 3
        except LookupError as exc:
            print(
                f"error: chunk {chunk_index} ({chunk_start.isoformat()} -> "
                f"{chunk_end.isoformat()}): no successful request: "
                f"{_scrub(str(exc))}",
                file=stderr,
            )
            print(
                build_final_summary(
                    provider_key=provider_key,
                    start_date=start_date,
                    end_date=end_date,
                    universe_count=len(tuple(symbols)),
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    failed_chunk_index=chunk_index,
                    status="failed",
                    inserted_total=inserted_total,
                    skipped_total=skipped_total,
                ),
                file=stdout,
            )
            return 3
        except Exception as exc:  # pragma: no cover - defensive only
            print(
                f"error: chunk {chunk_index} ({chunk_start.isoformat()} -> "
                f"{chunk_end.isoformat()}) raised "
                f"{type(exc).__name__}: {_scrub(str(exc))}",
                file=stderr,
            )
            print(
                build_final_summary(
                    provider_key=provider_key,
                    start_date=start_date,
                    end_date=end_date,
                    universe_count=len(tuple(symbols)),
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    failed_chunk_index=chunk_index,
                    status="failed",
                    inserted_total=inserted_total,
                    skipped_total=skipped_total,
                ),
                file=stdout,
            )
            return 1

        if result.attempt_status != "succeeded":
            print(
                build_chunk_summary(result, chunk_index=chunk_index),
                file=stdout,
            )
            print(
                f"error: chunk {chunk_index} ({chunk_start.isoformat()} -> "
                f"{chunk_end.isoformat()}): provider attempt failed "
                f"(attempt_status={result.attempt_status}, "
                f"request_status={result.request_status})",
                file=stderr,
            )
            print(
                build_final_summary(
                    provider_key=provider_key,
                    start_date=start_date,
                    end_date=end_date,
                    universe_count=len(tuple(symbols)),
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    failed_chunk_index=chunk_index,
                    status="failed",
                    inserted_total=inserted_total,
                    skipped_total=skipped_total,
                ),
                file=stdout,
            )
            return 3

        print(build_chunk_summary(result, chunk_index=chunk_index), file=stdout)
        completed_chunks += 1
        inserted_total += result.upsert_inserted
        skipped_total += result.upsert_skipped
        if sleep is not None:
            sleep(0.0)

    print(
        build_final_summary(
            provider_key=provider_key,
            start_date=start_date,
            end_date=end_date,
            universe_count=len(tuple(symbols)),
            total_chunks=len(chunks),
            completed_chunks=completed_chunks,
            failed_chunk_index=None,
            status="succeeded",
            inserted_total=inserted_total,
            skipped_total=skipped_total,
        ),
        file=stdout,
    )
    return 0


class _nullcontext:
    """Minimal no-op context manager used when no env override is needed."""

    def __enter__(self) -> dict[str, str]:
        return {}

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _EnvStack:
    """Context manager applying and restoring the supplied env overrides.

    Reads the *current* value of each overridden key on ``__enter__``
    and restores it on ``__exit__`` so the helper is safe to use inside
    the existing ``lru_cache``-d settings: the CLI applies the override
    before :func:`invest_pipeline.config.get_settings` is first hit.
    """

    def __init__(self, overrides: dict[str, str]) -> None:
        self._overrides = dict(overrides)
        self._previous: dict[str, str | None] = {}

    def __enter__(self) -> dict[str, str]:
        for key, value in self._overrides.items():
            self._previous[key] = os.environ.get(key)
            os.environ[key] = value
        return dict(self._overrides)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for key, previous in self._previous.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _resolve_universe_path(args_universe: str | None) -> Any:
    """Return the personal-universe path the CLI should load.

    Honours the optional ``--universe`` override (mapped to the
    ``INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH`` env var before
    :func:`invest_pipeline.config.get_settings` is first hit) and
    falls back to the configured default. Returned as a :class:`Path`
    so :func:`invest_pipeline.personal_universe.load_personal_universe`
    can fail closed on a missing file.
    """

    from pathlib import Path

    overrides = build_env_overrides(universe=args_universe)
    env_stack: Any = _EnvStack(overrides) if overrides else _nullcontext()
    with env_stack:
        settings = get_settings()
    return Path(settings.personal_universe_path)


def _build_default_runner(
    *,
    provider_key: str,
    database_url: str | None,
) -> _DefaultChunkRunner:
    """Construct the production :class:`_DefaultChunkRunner`.

    Reads ``provider_key`` and ``database_url`` from the supplied
    arguments so tests can pass fakes; ``database_url`` is required
    for the default runner because ``write_etf_daily_bars_raw`` and
    ``upsert_etf_daily_bars` both persist through the storage layer.
    Returns ``None`` when no database URL is configured so the caller
    can refuse to start the backfill.
    """

    if not isinstance(database_url, str) or not database_url:
        raise HistoricalDailyBarsCLIConfigError(
            "DATABASE_URL (or the equivalent invest-pipeline setting) is "
            "required to run the historical daily-bars backfill"
        )
    from invest_storage.database import build_engine, session_factory

    settings = get_settings()
    provider = build_provider(settings)
    engine = build_engine(database_url)
    factory = session_factory(engine)
    return _DefaultChunkRunner(provider, factory, engine=engine)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns ``0`` on success and a non-zero exit code (``2`` for
    configuration errors, ``3`` for fail-closed provider / lookup
    failures, ``1`` for any other unrecoverable error) on error.
    Never prints the API key, raw payload, exception repr or absolute
    filesystem paths; errors are surfaced as a single short stderr
    line followed by the redacted final summary.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = sys.stdout
    stderr = sys.stderr

    today = market_today()
    try:
        start_date = parse_iso_date(args.start_date, field_name="start-date", today=today)
        end_date = parse_iso_date(args.end_date, field_name="end-date", today=today)
        validate_range(start_date=start_date, end_date=end_date, today=today)
    except HistoricalDailyBarsCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    overrides = build_env_overrides(universe=args.universe)
    env_stack: Any = _EnvStack(overrides) if overrides else _nullcontext()
    with env_stack:
        provider_key = _resolve_provider_key(os.environ)
        cifang_enabled = _cifang_enabled(os.environ)
        try:
            validate_provider_opt_in(
                provider_key=provider_key,
                cifang_enabled=cifang_enabled,
                confirm_network=args.confirm_network,
            )
        except HistoricalDailyBarsCLIConfigError as exc:
            print(f"refused: {exc}", file=stderr)
            return 2

        try:
            universe_path = _resolve_universe_path(args.universe)
            universe = load_personal_universe(universe_path)
        except PersonalUniverseError as exc:
            print(f"error: failed to load personal universe: {exc}", file=stderr)
            return 2
        except HistoricalDailyBarsCLIConfigError as exc:
            print(f"error: {exc}", file=stderr)
            return 2
        except Exception as exc:
            print(
                f"error: could not read personal universe: {type(exc).__name__}",
                file=stderr,
            )
            return 2

        try:
            symbols = validate_universe(universe)
        except HistoricalDailyBarsCLIConfigError as exc:
            print(f"error: {exc}", file=stderr)
            return 2

        try:
            settings = get_settings()
        except Exception:
            settings = None
        database_url = (
            getattr(settings, "database_url", None) if settings is not None else None
        )

        try:
            runner = _build_default_runner(
                provider_key=provider_key,
                database_url=database_url,
            )
        except HistoricalDailyBarsCLIConfigError as exc:
            print(f"error: {exc}", file=stderr)
            return 2
        except Exception:
            print(
                "error: could not construct the historical daily-bars "
                "runner (provider or session factory unavailable)",
                file=stderr,
            )
            return 2

        try:
            return run_backfill(
                runner=runner,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                today=today,
                stdout=stdout,
                stderr=stderr,
                token=_configured_cifang_token(),
            )
        finally:
            with contextlib.suppress(Exception):
                runner.close()


__all__ = [
    "HistoricalDailyBarsCLIConfigError",
    "_ChunkResult",
    "_ChunkRunner",
    "_DefaultChunkRunner",
    "build_env_overrides",
    "build_chunk_summary",
    "build_final_summary",
    "build_parser",
    "chunk_date_range",
    "main",
    "parse_iso_date",
    "run_backfill",
    "validate_provider_opt_in",
    "validate_range",
    "validate_universe",
]


if __name__ == "__main__":
    raise SystemExit(main())
