"""Manual ``personal_etf_daily_job`` CLI (ADR-0011, Stage 1 PR-4).

Stage 1 ships a manual one-command driver for the personal ETF daily
job: ``personal-daily-run`` resolves the registered job from
:mod:`invest_pipeline.definitions`, executes it for a single
caller-supplied trade date, and emits a single redacted JSON line on
success.

Invoked as::

    python -m invest_pipeline.personal_daily_cli \\
        --trade-date 2026-07-31 \\
        --universe /path/to/personal-universe.yaml \\
        --policy /path/to/candidate-pool-personal.yaml \\
        --confirm-network

The CLI is intentionally minimal and intentionally safe-by-default:

* ``--trade-date`` is required and validated as ``YYYY-MM-DD``; dates
  after today are rejected without ever importing or initialising any
  Dagster execution state.
* ``--universe`` and ``--policy`` are optional CLI overrides that are
  mapped to ``INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH`` and
  ``INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH`` **before**
  :mod:`invest_pipeline.definitions` is imported (and therefore before
  :func:`invest_pipeline.config.get_settings` is first hit, since
  settings are ``lru_cache``-d). Defaults remain the existing
  ``config/personal-universe.yaml`` and
  ``config/candidate-pool-personal.yaml``.
* Real-provider / network safety preserves the existing ADR-0011
  semantics: ``--confirm-network`` alone never enables
  :class:`CifangQuantInstrumentProvider`. If the selected provider key
  is ``cifangquant`` **both** ``INVEST_PIPELINE_CIFANG_ENABLED=true``
  and ``--confirm-network`` must be set; either missing produces a
  single concise ``refused:`` line on stderr and a non-zero exit code.
  Fixture / dev runs never need ``--confirm-network``.
* The CLI never prints the API key, raw payload, request headers or
  exception reprs that may embed secrets. Errors are surfaced as a
  single short stderr line plus a non-zero exit code; success emits
  exactly one JSON line on stdout with the safe counts and IDs lifted
  from Dagster materialization metadata.

The corresponding Makefile target is ``personal-daily-run``. See the
sibling CLI tests (``tests/unit/test_personal_daily_cli.py``) for the
supported behaviour and redaction guarantees.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from invest_pipeline.clock import market_today

_UNIVERSE_ENV = "INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH"
_POLICY_ENV = "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH"
_PROVIDER_KEY_ENV = "INVEST_PIPELINE_PROVIDER_KEY"
_CIFANG_ENABLED_ENV = "INVEST_PIPELINE_CIFANG_ENABLED"

_FIXTURE_DEV_KEY = "fixture_dev"
_CIFANG_KEY = "cifangquant"

_REDACTED = "***"

_PERSONAL_DAILY_JOB_KEY = "personal_etf_daily_job"
_TRIGGER_TYPE_MANUAL = "manual"


class DailyCLIConfigError(Exception):
    """Raised when the CLI inputs are incomplete or unsafe.

    The CLI translates this into a non-zero exit code (2) and a single
    short line on stderr. It is **not** a provider-level error; the CLI
    refuses to start ``defs`` whenever this is raised, so no Dagster
    machinery or provider is ever invoked on a misconfigured run.
    """


class _JobRunner(Protocol):
    """Surface :func:`run_daily` needs to execute the personal job.

    Tests substitute a stub that captures the partition key and returns
    a fake :class:`object` whose ``get_asset_materialization_events``
    yields canned events; production uses
    ``defs.resolve_job_def('personal_etf_daily_job')``.
    """

    def execute_in_process(self, partition_key: str, raise_on_error: bool) -> Any: ...


class _DefinitionsLoader(Protocol):
    """Surface :func:`run_daily` needs to obtain the job definition.

    Splitting this out of :func:`main` keeps the import side effect
    (``defs`` instantiates Dagster ``Definitions``) out of unit tests;
    a stub simply returns a fake job runner.
    """

    def resolve_job_def(self, job_name: str) -> _JobRunner: ...


class PipelineRunRecorder(Protocol):
    """Persist :class:`invest_domain.pipeline.PipelineRun` audit records.

    The CLI writes one ``ops.pipeline_runs`` row per invocation of
    :func:`run_daily` so the operational dashboard can attribute
    successes and failures to a unique run id. The three calls
    mirror the lifecycle encoded by
    :class:`invest_domain.pipeline.PipelineRunStatus`:
    ``running`` (set by :meth:`start`) → ``succeeded`` or ``failed``.

    The recorder is fully optional. :func:`run_daily` falls back to a
    no-op when none is supplied, so existing unit tests that inject
    only ``defs`` + ``stdout``/``stderr`` continue to pass without
    ever touching a database.
    """

    def start(
        self,
        *,
        job_key: str,
        trigger_type: str,
        started_at: datetime,
        partition_key: str | None,
        dagster_run_id: str | None,
        config_snapshot: Mapping[str, Any] | None,
    ) -> UUID | None:
        """Insert a ``running`` row; return the assigned run id (or ``None`` on failure)."""

    def mark_succeeded(self, run_id: UUID, *, finished_at: datetime) -> None: ...

    def mark_failed(
        self,
        run_id: UUID,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None: ...


class _NoopPipelineRunRecorder:
    """Default recorder used when :func:`run_daily` receives no injection.

    All methods silently succeed without persisting anything. The
    no-op keeps the unit-test surface hermetic so test suites do not
    have to wire a database just to exercise the JSON / exit-code
    contracts. :func:`run_daily` checks for ``None`` explicitly so
    the no-op is never instantiated unless the caller asks for it.
    """

    def start(self, **_kwargs: Any) -> None:
        return None

    def mark_succeeded(self, _run_id: UUID, *, finished_at: datetime) -> None:
        return None

    def mark_failed(
        self,
        _run_id: UUID,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _scrub_token(message: str, token: str) -> str:
    """Return ``message`` with every ``token`` occurrence replaced by :data:`_REDACTED`."""

    if not token or not message:
        return message
    return message.replace(token, _REDACTED)


def _safe_record(
    fn: Callable[[], None],
    *,
    context: str,
    stderr=sys.stderr,
) -> None:
    """Invoke ``fn`` swallowing any exception, never masking the real result.

    Audit persistence failures must never change the JSON summary the
    operator sees or the exit code the shell consumes; the worst case
    is a lost ``pipeline_runs`` row, which the on-call reviewer can
    backfill from the asset-side audit trail. The defensive
    ``context`` string is appended to a stderr comment so the missing
    audit is at least visible in the run log.
    """

    try:
        fn()
    except Exception as exc:  # pragma: no cover - defensive only
        print(
            f"warning: pipeline_runs audit persistence failed ({context}): "
            f"{type(exc).__name__}",
            file=stderr,
        )


class SqlAlchemyPipelineRunRecorder:
    """SQLAlchemy-backed :class:`PipelineRunRecorder` writing to ``ops.pipeline_runs``.

    Each call opens its own :class:`SqlAlchemyUnitOfWork` so the audit
    insert and the terminal-state update land in independent
    transactions — the run is still recorded even when the main job
    fails halfway through. ``start`` returns the assigned
    :class:`UUID` (or ``None`` if the insert fails) so :func:`run_daily`
    can decide whether to call :meth:`mark_succeeded` /
    :meth:`mark_failed`.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        unit_of_work_factory: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Imported lazily so the CLI module remains importable in
        # environments where SQLAlchemy is optional.
        from invest_domain.pipeline import PipelineRun, PipelineRunStatus
        from invest_storage import SqlAlchemyUnitOfWork

        self._unit_of_work_factory = unit_of_work_factory or SqlAlchemyUnitOfWork
        self._PipelineRun = PipelineRun
        self._PipelineRunStatus = PipelineRunStatus

    def start(
        self,
        *,
        job_key: str,
        trigger_type: str,
        started_at: datetime,
        partition_key: str | None,
        dagster_run_id: str | None,
        config_snapshot: Mapping[str, Any] | None,
    ) -> UUID | None:
        try:
            with self._unit_of_work_factory(self._session_factory) as uow:
                existing = uow.pipeline_runs.get_latest_by_job_and_partition(
                    job_key=job_key,
                    partition_key=partition_key,
                )
                if (
                    existing is not None
                    and existing.status_value
                    == self._PipelineRunStatus.SUCCEEDED.value
                ):
                    # Idempotency: the partition already has a successful
                    # manual run on record. Skip the new ``running`` row
                    # so the dashboard does not see a duplicate
                    # successful entry; the caller already treats a
                    # ``None`` return as "no recording this time" and
                    # the job still proceeds so the operator sees a
                    # fresh JSON summary.
                    return None
                run = uow.pipeline_runs.start(
                    self._PipelineRun(
                        job_key=job_key,
                        trigger_type=trigger_type,
                        status=self._PipelineRunStatus.RUNNING,
                        started_at=started_at,
                        partition_key=partition_key,
                        dagster_run_id=dagster_run_id,
                        config_snapshot=dict(config_snapshot or {}),
                    )
                )
                run_id = run.id
            return run_id if isinstance(run_id, UUID) else None
        except Exception:
            return None

    def mark_succeeded(self, run_id: UUID, *, finished_at: datetime) -> None:
        with self._unit_of_work_factory(self._session_factory) as uow:
            uow.pipeline_runs.mark_succeeded(run_id, finished_at=finished_at)

    def mark_failed(
        self,
        run_id: UUID,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None:
        with self._unit_of_work_factory(self._session_factory) as uow:
            uow.pipeline_runs.mark_failed(
                run_id,
                error=error_summary,
                finished_at=finished_at,
            )


def build_default_pipeline_run_recorder(
    database_url: str | None,
) -> PipelineRunRecorder | None:
    """Return a :class:`SqlAlchemyPipelineRunRecorder` or ``None`` if the URL is unusable.

    Returned recorder is wrapped so construction-time failures
    (e.g. the database is unreachable at CLI start) degrade to a
    no-op rather than blocking the personal job. The caller already
    swallows every recorder-call failure, so a ``None`` return here is
    safe — :func:`run_daily` treats it as the absence of recording.
    """

    if not database_url or not isinstance(database_url, str):
        return None
    try:
        from invest_storage import build_engine, session_factory
    except Exception:
        return None
    try:
        engine = build_engine(database_url)
    except Exception:
        return None
    factory = session_factory(engine)
    return SqlAlchemyPipelineRunRecorder(factory)


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by the CLI.

    Exposed for tests so they can drive :func:`parse_args` without going
    through ``sys.argv``.
    """

    parser = argparse.ArgumentParser(
        prog="invest_pipeline.personal_daily_cli",
        description=(
            "Manual driver for the personal_etf_daily_job. "
            "Requires --trade-date; --universe and --policy override the "
            "default config paths via INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH "
            "and INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH. "
            "--confirm-network is required only when the selected provider is "
            "cifangquant (combined with INVEST_PIPELINE_CIFANG_ENABLED=true); "
            "fixture runs never need it."
        ),
    )
    parser.add_argument(
        "--trade-date",
        required=True,
        help=(
            "Single completed trading date in YYYY-MM-DD. The CLI never "
            "silently re-targets today's data; future dates are rejected "
            "before Dagster is initialised."
        ),
    )
    parser.add_argument(
        "--universe",
        required=False,
        default=None,
        help=(
            "Optional path to a personal-universe YAML. Forwarded to "
            f"{_UNIVERSE_ENV} before Dagster settings are read."
        ),
    )
    parser.add_argument(
        "--policy",
        required=False,
        default=None,
        help=(
            "Optional path to a candidate-pool policy YAML. Forwarded to "
            f"{_POLICY_ENV} before Dagster settings are read."
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


def parse_trade_date(raw: str, today: date) -> date:
    """Parse ``--trade-date`` into a :class:`date` and reject future dates.

    Pure so unit tests can drive it with arbitrary strings and a fake
    ``today`` without touching the environment or Dagster.
    """

    if not isinstance(raw, str):
        raise DailyCLIConfigError("--trade-date must be a string")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise DailyCLIConfigError(
            f"--trade-date must be YYYY-MM-DD: {exc}"
        ) from exc
    if parsed > today:
        raise DailyCLIConfigError(
            f"--trade-date must not be in the future "
            f"(got {parsed.isoformat()}, today is {today.isoformat()})"
        )
    return parsed


def build_env_overrides(
    *,
    universe: str | None = None,
    policy: str | None = None,
) -> dict[str, str]:
    """Return the env-var overrides implied by the supplied CLI flags.

    Only keys with a non-``None`` value are returned so the caller can
    apply them with :class:`contextlib.ExitStack` / a captured
    ``os.environ`` patch without accidentally clearing unrelated
    variables. The function is pure: it does not mutate ``os.environ``
    itself so unit tests can compute the expected mapping without
    touching the process environment.
    """

    overrides: dict[str, str] = {}
    if universe:
        overrides[_UNIVERSE_ENV] = str(universe)
    if policy:
        overrides[_POLICY_ENV] = str(policy)
    return overrides


def validate_provider_opt_in(
    *,
    provider_key: str,
    cifang_enabled: bool | None,
    confirm_network: bool,
) -> None:
    """Reject the run unless the real-provider opt-in gates are aligned.

    Three independent checks preserve the ADR-0011 semantics:

    * If the selected provider is :data:`_FIXTURE_DEV_KEY` the CLI never
      reaches the network, regardless of ``--confirm-network``. The
      flag is intentionally inert for fixture runs (the requirement
      says "Fixture/dev runs must work without confirm-network").
    * If the selected provider is :data:`_CIFANG_KEY`,
      ``--confirm-network`` alone **never** enables the provider; both
      ``INVEST_PIPELINE_CIFANG_ENABLED=true`` and ``--confirm-network``
      must be set. The CLI does not invent a second API-key policy.
    * Any other provider key is rejected; the PR-4 contract keeps the
      set of supported providers to the factory's declared
      :data:`invest_pipeline.provider_factory.KNOWN_PROVIDER_KEYS`.

    The function never touches the network and never reads the Cifang
    API key.
    """

    if provider_key == _FIXTURE_DEV_KEY:
        return
    if provider_key == _CIFANG_KEY:
        if not cifang_enabled:
            raise DailyCLIConfigError(
                f"{_CIFANG_ENABLED_ENV}=true is required to run personal_etf_daily_job "
                "with provider=cifangquant (ADR-0011 §3); set it to acknowledge "
                "the real-API opt-in"
            )
        if not confirm_network:
            raise DailyCLIConfigError(
                "--confirm-network is required to run personal_etf_daily_job "
                "with provider=cifangquant"
            )
        return
    raise DailyCLIConfigError(
        f"INVEST_PIPELINE_PROVIDER_KEY={provider_key!r} is not supported by the "
        f"personal daily CLI; expected one of {_FIXTURE_DEV_KEY!r} or {_CIFANG_KEY!r}"
    )


def _materialization_metadata(event: Any) -> Mapping[str, Any] | None:
    """Return the materialization metadata mapping on a Dagster event.

    Returns ``None`` when the event lacks metadata so callers can
    distinguish between ``null``-valued entries and missing assets.
    """

    materialization = getattr(event, "materialization", None)
    if materialization is None:
        return None
    metadata = getattr(materialization, "metadata", None)
    if metadata is None:
        return None
    if hasattr(metadata, "items"):
        try:
            return dict(metadata.items())
        except Exception:
            return None
    return None


def _metadata_text(value: Any) -> str | None:
    """Return the textual form of a metadata entry, or ``None``.

    Used to lift the ``snapshot_id`` / ``run_id`` strings out of the
    ``TextMetadataValue`` wrapper without leaking the wrapper class
    into the JSON summary.
    """

    candidate = value
    if hasattr(candidate, "value"):
        candidate = candidate.value
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _coerce_int(value: Any) -> int | None:
    """Best-effort coercion of a Dagster metadata value to ``int``.

    Dagster wraps materialization metadata in typed ``*MetadataValue``
    entries (e.g. ``IntMetadataValue(value=1)``,
    ``TextMetadataValue(text='1')``); the helper transparently unwraps
    the ``.value`` attribute when present so the summary builder does
    not have to special-case each wrapper. Falls back to ``None``
    rather than raising so a missing or misshapen metadata entry
    degrades to a safe ``null`` in the summary payload rather than
    aborting the post-execution step.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return _coerce_int(value.value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    if isinstance(value, float):
        if value != value:
            return None
        return int(value)
    return None


def _materialization_counts(event: Any) -> tuple[Mapping[str, Any] | None, int | None]:
    """Return ``(metadata, row_count)`` for a materialization event.

    The Dagster convention for asset row counts in this codebase is
    that ``etf_instruments_raw`` / ``etf_daily_bars_raw`` publish
    ``record_count`` while ``etf_input_snapshot`` publishes
    ``row_count`` and ``universe_size``. This helper normalises across
    the two conventions so the summary can map either to a single
    numeric count.
    """

    metadata = _materialization_metadata(event)
    if metadata is None:
        return None, None
    for key in ("record_count", "row_count", "universe_size", "symbol_count"):
        if key in metadata:
            coerced = _coerce_int(metadata[key])
            if coerced is not None:
                return metadata, coerced
    return metadata, None


def build_summary(
    *,
    trade_date: date,
    materialization_events: Sequence[Any],
    provider_key: str,
) -> str:
    """Return a redacted, JSON-encoded summary line for a successful run.

    The function inspects the materialization events emitted by the
    run, lifts the documented safe fields (counts, run id, snapshot id,
    status) from Dagster metadata, and returns a deterministic
    ``sort_keys=True`` JSON line that can be scraped by operators.

    Unknown metadata entries are discarded: the summary never echoes
    arbitrary Dagster metadata into operator-facing output. Counts and
    IDs that are not safely available degrade to ``null`` rather than
    being guessed.
    """

    extracted: dict[str, int | str | None] = {
        "trade_date": trade_date.isoformat(),
        "provider": provider_key,
        "status": None,
        "universe_count": None,
        "daily_bar_count": None,
        "snapshot_id": None,
        "candidate_pool_run_id": None,
        "included_count": None,
        "excluded_count": None,
    }

    for event in materialization_events:
        asset_key = getattr(event, "asset_key", None)
        if asset_key is None:
            continue
        asset_path = getattr(asset_key, "path", None)
        asset_name: str | None = None
        if isinstance(asset_path, (list, tuple)) and asset_path:
            asset_name = asset_path[-1]
        if asset_name is None:
            to_py = getattr(asset_key, "to_user_string", None)
            if callable(to_py):
                try:
                    candidate = to_py()
                    if isinstance(candidate, str) and candidate:
                        asset_name = candidate.split("/")[-1]
                except Exception:
                    asset_name = None
        if not isinstance(asset_name, str):
            continue

        metadata, normalised_count = _materialization_counts(event)
        if metadata is None:
            continue

        if asset_name == "etf_input_snapshot":
            if extracted["universe_count"] is None and normalised_count is not None:
                extracted["universe_count"] = normalised_count
            universe_in_meta = _coerce_int(metadata.get("universe_size"))
            if universe_in_meta is not None:
                extracted["universe_count"] = universe_in_meta
            snapshot_id = _metadata_text(metadata.get("snapshot_id"))
            if snapshot_id is not None:
                extracted["snapshot_id"] = snapshot_id
        elif asset_name in {"etf_daily_bars_raw", "etf_daily_bars"}:
            record_count = _coerce_int(metadata.get("record_count"))
            if record_count is not None and extracted["daily_bar_count"] is None:
                extracted["daily_bar_count"] = record_count
            symbol_count = _coerce_int(metadata.get("symbol_count"))
            if symbol_count is not None and extracted["universe_count"] is None:
                extracted["universe_count"] = symbol_count
        elif asset_name == "personal_candidate_pool":
            status_value = _metadata_text(metadata.get("status"))
            if status_value is not None:
                extracted["status"] = status_value
            run_id = _metadata_text(metadata.get("run_id"))
            if run_id is not None:
                extracted["candidate_pool_run_id"] = run_id
            included = _coerce_int(metadata.get("included_count"))
            if included is not None:
                extracted["included_count"] = included
                extracted["excluded_count"] = _compute_excluded(
                    metadata, included
                )

    payload = {key: extracted[key] for key in sorted(extracted)}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _compute_excluded(
    metadata: Mapping[str, Any], included: int
) -> int | None:
    """Return ``input_count - included`` when both are safely available.

    Falls back to ``None`` so a missing metadata entry never produces a
    misleading negative or zero in the operator-facing summary.
    """

    input_count = _coerce_int(metadata.get("input_count"))
    if input_count is None:
        item_count = _coerce_int(metadata.get("item_count"))
        if item_count is None:
            return None
        return max(item_count - included, 0)
    return max(input_count - included, 0)


def summarise_failure(result: Any, *, token: str = "") -> str:
    """Return a single, secret-scrubbed stderr line for a failed run.

    The function deliberately avoids echoing the exception ``repr``,
    raw payload or headers; it returns only the run id and a short
    dagger pointing operators at the failed step list. The optional
    ``token`` is scrubbed from any incidental leakage that may have
    slipped into the event message text.
    """

    run_id = getattr(result, "run_id", None) if result is not None else None
    failed_steps = (
        list(result.get_failed_step_keys())
        if result is not None and hasattr(result, "get_failed_step_keys")
        else []
    )

    def _scrub(message: str) -> str:
        if not token or not message:
            return message
        return message.replace(token, _REDACTED)

    base = (
        f"personal_etf_daily_job failed (run_id={run_id!s}, "
        f"failed_steps={failed_steps!r})"
    )
    return _scrub(base)


def run_daily(
    *,
    trade_date: date,
    defs: _DefinitionsLoader,
    provider_key: str,
    stdout=sys.stdout,
    stderr=sys.stderr,
    token: str = "",
    pipeline_run_recorder: PipelineRunRecorder | None = None,
) -> int:
    """Execute the personal job for ``trade_date`` and emit one JSON line.

    Returns ``0`` when the job succeeds, ``2`` when the run was
    refused by the in-process executor (no materializations emitted),
    and ``1`` for any other unrecoverable failure. This mirror the
    contract of the Cifang smoke CLI so operators can rely on a single
    exit-code convention across opt-in commands.

    When ``pipeline_run_recorder`` is supplied the CLI also writes a
    matching row to ``ops.pipeline_runs`` so the operator dashboard
    can attribute the run to a stable id; ``start`` is called before
    the job executes and :meth:`mark_succeeded` / :meth:`mark_failed`
    flip the row to its terminal state on the way out. Recorder
    failures (DB unavailable, broken schema, etc.) are swallowed so
    they never mask the original CLI outcome — see
    :func:`_safe_record`.
    """

    def _scrub(message: str) -> str:
        if not token or not message:
            return message
        return message.replace(token, _REDACTED)

    recorder: PipelineRunRecorder = (
        pipeline_run_recorder
        if pipeline_run_recorder is not None
        else _NoopPipelineRunRecorder()
    )

    try:
        job_def = defs.resolve_job_def(_PERSONAL_DAILY_JOB_KEY)
    except KeyError as exc:
        print(
            "error: personal_etf_daily_job is not registered in "
            f"invest_pipeline.definitions: {_scrub(str(exc))}",
            file=stderr,
        )
        return 1
    except Exception as exc:  # pragma: no cover - defensive only
        print(
            f"error: failed to resolve personal_etf_daily_job: {_scrub(str(exc))}",
            file=stderr,
        )
        return 1

    started_at = _now()
    run_id: UUID | None = None
    try:
        run_id = recorder.start(
            job_key=_PERSONAL_DAILY_JOB_KEY,
            trigger_type=_TRIGGER_TYPE_MANUAL,
            started_at=started_at,
            partition_key=trade_date.isoformat(),
            dagster_run_id=None,
            config_snapshot={
                "provider_key": provider_key,
                "trade_date": trade_date.isoformat(),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive only
        run_id = None
        print(
            "warning: pipeline_runs audit insert raised before execution: "
            f"{type(exc).__name__}",
            file=stderr,
        )
    if not isinstance(run_id, UUID):
        run_id = None

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            result = job_def.execute_in_process(
                partition_key=trade_date.isoformat(),
                raise_on_error=False,
            )
    except Exception:
        finished_at = _now()
        print(
            "error: personal_etf_daily_job could not start or complete",
            file=stderr,
        )
        if run_id is not None:
            error_summary = _scrub(
                "personal_etf_daily_job could not start or complete"
            )
            _safe_record(
                lambda: recorder.mark_failed(
                    run_id,  # type: ignore[arg-type]
                    error_summary=error_summary,
                    finished_at=finished_at,
                ),
                context="mark_failed after execute_in_process raised",
                stderr=stderr,
            )
        return 1

    materialization_events = tuple(
        result.get_asset_materialization_events()
        if hasattr(result, "get_asset_materialization_events")
        else []
    )
    if not result.success or not materialization_events:
        failure_message = summarise_failure(result, token=token)
        print(failure_message, file=stderr)
        rc = 2 if result.success else 1
        if run_id is not None:
            error_summary = _scrub(failure_message)
            finished_at = _now()
            _safe_record(
                lambda: recorder.mark_failed(
                    run_id,  # type: ignore[arg-type]
                    error_summary=error_summary,
                    finished_at=finished_at,
                ),
                context="mark_failed after job produced no materializations",
                stderr=stderr,
            )
        return rc

    print(
        build_summary(
            trade_date=trade_date,
            materialization_events=materialization_events,
            provider_key=provider_key,
        ),
        file=stdout,
    )
    if run_id is not None:
        finished_at = _now()
        _safe_record(
            lambda: recorder.mark_succeeded(
                run_id,  # type: ignore[arg-type]
                finished_at=finished_at,
            ),
            context="mark_succeeded after successful job",
            stderr=stderr,
        )
    return 0


def _resolve_provider_key(env: Mapping[str, str] | None) -> str:
    """Return the configured provider key, falling back to ``fixture_dev``.

    Reads the mapping directly so callers can drive the function in
    tests without touching ``os.environ``.
    """

    if env is None:
        env = os.environ
    return env.get(_PROVIDER_KEY_ENV, _FIXTURE_DEV_KEY)


def _cifang_enabled(env: Mapping[str, str] | None) -> bool:
    """Return whether the Cifang opt-in flag is set in ``env``."""

    if env is None:
        env = os.environ
    value = env.get(_CIFANG_ENABLED_ENV, "")
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _configured_cifang_token() -> str:
    """Read the configured token only for error-message scrubbing."""

    try:
        from invest_pipeline.adapters.cifang.config import CifangSettings

        return CifangSettings().api_key.get_secret_value()
    except Exception:
        return ""


class _nullcontext:
    """Minimal no-op context manager used when no env override is needed.

    Inline so ``main`` does not depend on ``contextlib.nullcontext`` at
    import time (the function is also part of the Python 3.7 standard
    library, but defining our own keeps the runtime surface flat).
    """

    def __enter__(self) -> dict[str, str]:
        return {}

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _EnvStack:
    """Context manager applying and restoring the supplied env-var overrides.

    Reads the *current* value of each overridden key on ``__enter__``
    and restores it on ``__exit__`` so the helper is safe to use inside
    the existing ``lru_cache``-d settings: the CLI applies the override
    before :mod:`invest_pipeline.definitions` is imported (and therefore
    before ``get_settings()`` is first hit).
    """

    def __init__(self, overrides: Mapping[str, str]) -> None:
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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns ``0`` on success and a non-zero exit code (``1`` for
    execution failures, ``2`` for misconfiguration) on error. Never
    prints the API key, raw payload or exception reprs that may embed
    secrets; errors are surfaced as a single short stderr line.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = sys.stdout
    stderr = sys.stderr

    try:
        trade_date = parse_trade_date(args.trade_date, market_today())
    except DailyCLIConfigError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    overrides = build_env_overrides(
        universe=args.universe,
        policy=args.policy,
    )
    if overrides:
        env_stack: _EnvStack | Any = _EnvStack(overrides)
    else:
        env_stack = _nullcontext()

    with env_stack:
        provider_key = _resolve_provider_key(os.environ)
        cifang_enabled = _cifang_enabled(os.environ)

        try:
            validate_provider_opt_in(
                provider_key=provider_key,
                cifang_enabled=cifang_enabled,
                confirm_network=args.confirm_network,
            )
        except DailyCLIConfigError as exc:
            print(f"refused: {exc}", file=stderr)
            return 2

        try:
            from invest_pipeline.definitions import defs as defs_obj
        except Exception:
            print(
                "error: could not load personal_etf_daily_job definitions",
                file=stderr,
            )
            return 2

        recorder = _build_pipeline_run_recorder_from_settings()
        return run_daily(
            trade_date=trade_date,
            defs=defs_obj,
            provider_key=provider_key,
            stdout=stdout,
            stderr=stderr,
            token=_configured_cifang_token(),
            pipeline_run_recorder=recorder,
        )


def _build_pipeline_run_recorder_from_settings() -> PipelineRunRecorder | None:
    """Resolve the ``ops.pipeline_runs`` recorder configured for the CLI.

    Reads ``DATABASE_URL`` from :func:`invest_pipeline.config.get_settings`
    and constructs a :class:`SqlAlchemyPipelineRunRecorder`. Any failure
    (settings uninitialisable, missing dependency, broken URL) degrades
    to ``None`` so the CLI can still execute the personal job. The
    recorder injection is optional — :func:`run_daily` falls back to a
    no-op when ``None`` is supplied so unit tests that bypass ``main``
    never have to wire a database.
    """

    try:
        from invest_pipeline.config import get_settings
    except Exception:
        return None
    try:
        settings = get_settings()
    except Exception:
        return None
    database_url = getattr(settings, "database_url", None)
    if not isinstance(database_url, str) or not database_url:
        return None
    return build_default_pipeline_run_recorder(database_url)


__all__ = [
    "DailyCLIConfigError",
    "PipelineRunRecorder",
    "SqlAlchemyPipelineRunRecorder",
    "build_default_pipeline_run_recorder",
    "build_env_overrides",
    "build_parser",
    "build_summary",
    "main",
    "parse_trade_date",
    "run_daily",
    "summarise_failure",
    "validate_provider_opt_in",
]


if __name__ == "__main__":
    raise SystemExit(main())
