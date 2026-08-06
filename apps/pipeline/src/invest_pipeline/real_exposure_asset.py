"""DC-3 Dagster orchestration slice: opt-in real AkShare exposure asset.

This module hosts the dedicated Dagster asset (and nothing else) that
wraps :func:`invest_pipeline.real_exposure_service.collect_and_persist_real_exposure`
for the ``real_exposure_job`` (manual, no schedule, no sensor).

Design rules (DC-3 §3):

* **Opt-in by default.** The asset config carries an explicit ``enabled``
  boolean that defaults to ``False``. When ``enabled`` is ``False`` the
  asset raises :class:`RealExposureAssetDisabledError` BEFORE
  constructing the :class:`AkshareClient` or opening any network
  connection. The failure is fail-closed: a Dagster run that omits the
  flag cannot silently reach the network.
* **Explicit operator inputs.** ``etf_symbol``, ``etf_exchange``,
  ``index_code``, ``mapping_effective_from`` and ``observed_at`` are
  required Dagster config fields. ``holding_year``,
  ``mapping_effective_to``, ``revision`` and ``confidence`` are
  optional with safe defaults. Observation time is never substituted
  for the mapping effective date.
* **Engine lifecycle.** The asset builds a fresh SQLAlchemy
  ``Engine`` via :func:`invest_storage.database.build_engine`, wraps a
  :class:`SqlAlchemyUnitOfWork` factory around its
  :func:`session_factory`, and disposes the engine in a ``finally``
  block so a network or persistence failure cannot leak connections.
* **No Dagster globals at import time.** The module never imports
  ``akshare``; the network is only touched inside the asset body,
  behind the ``enabled`` gate.
"""

# Note: ``from __future__ import annotations`` is intentionally omitted.
# Dagster's pythonic ``dg.Config`` layer introspects the annotation
# namespace at class definition time; PEP 563 string annotations break
# the ``Config`` schema inference for this file.

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import dagster as dg
from invest_storage.database import build_engine, session_factory
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

from invest_pipeline.adapters.akshare.client import AkshareClient
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.config import get_settings
from invest_pipeline.real_exposure_service import (
    RealExposureClientProtocol,
    collect_and_persist_real_exposure,
)


class RealExposureAssetDisabledError(RuntimeError):
    """Raised when the real-exposure asset is invoked without the opt-in flag.

    The error is translated into a Dagster run failure so a misconfigured
    launch (missing ``enabled: true``) never reaches the AkShare SDK or
    the network. The message names the exact config key operators must
    set to authorise the real run.
    """


class RealExposureAssetConfig(dg.Config):
    """Dagster config schema for the real-exposure asset.

    All fields are explicit operator inputs; the slice never derives
    effective dates from observation time. ``enabled`` defaults to
    ``False`` so a launch that omits it cannot trigger a network call.

    Dagster's pythonic ``Config`` layer only resolves a small set of
    primitive types (``int`` / ``float`` / ``bool`` / ``str`` / ``list``
    and nested shapes). The asset therefore accepts ``mapping_effective_from``,
    ``observed_at`` and ``mapping_effective_to`` as ISO-8601 strings and
    converts them to :class:`datetime.date` /
    :class:`datetime.datetime` inside the asset body before delegating
    to the service. ``confidence`` is exposed as a ``float`` for the
    same reason and converted back to :class:`decimal.Decimal` to honour
    the service's domain contract.
    """

    enabled: bool = False
    etf_symbol: str
    etf_exchange: str
    index_code: str
    mapping_effective_from: str
    observed_at: str
    holding_year: str = ""
    mapping_effective_to: str | None = None
    revision: int = 1
    confidence: float = 1.0


def _build_akshare_client() -> AkshareClient:
    """Construct the real AkShare client.

    Kept as a thin wrapper so tests can patch the client construction
    seam without reaching for ``importlib`` hacks. The construction is
    intentionally cheap (no network); the SDK is resolved lazily on the
    first fetch.
    """
    return AkshareClient(AkshareSettings())


class RealExposureAssetConfigError(RuntimeError):
    """Raised when an operator-supplied config string is malformed.

    Dagster's pythonic ``Config`` layer only accepts primitive types
    (``str`` / ``float`` / ``int`` / ``bool``), so the asset accepts
    the mapping-effective-from / -to / observed-at as ISO-8601 strings
    and parses them here. A malformed value is translated into this
    error so a misconfigured launch fails before any DB or network
    work happens.
    """


def _parse_effective_from(value: str) -> date:
    """Parse a YYYY-MM-DD mapping-effective-from string."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RealExposureAssetConfigError(
            f"mapping_effective_from must be an ISO-8601 date (YYYY-MM-DD); "
            f"got {value!r}"
        ) from exc


def _parse_effective_to(value: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD mapping-effective-to string."""
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RealExposureAssetConfigError(
            f"mapping_effective_to must be an ISO-8601 date (YYYY-MM-DD) "
            f"or empty; got {value!r}"
        ) from exc


def _parse_observed_at(value: str) -> datetime:
    """Parse a timezone-aware ISO-8601 observed_at string."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RealExposureAssetConfigError(
            f"observed_at must be a timezone-aware ISO-8601 datetime; "
            f"got {value!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RealExposureAssetConfigError(
            f"observed_at must include a timezone offset; got {value!r}"
        )
    return parsed


@dg.asset(
    group_name="exposure",
    compute_kind="python",
    description=(
        "Opt-in DC-3 real-exposure asset: resolves the ETF by business key, "
        "fetches CSIndex constituents and AkShare reported holdings, and "
        "persists profile / constituents / mapping / holdings in one "
        "transaction. Disabled by default; requires `enabled: true`."
    ),
)
def real_exposure(
    context: dg.AssetExecutionContext,
    config: RealExposureAssetConfig,
) -> dg.MaterializeResult:
    """Materialise the opt-in real AkShare exposure bundle for one ETF.

    The asset is registered behind the dedicated ``real_exposure_job``
    and is NEVER scheduled or sensor-triggered. Operators must launch
    it manually through the Dagster UI / CLI with ``enabled: true`` in
    the run config; the slice fails closed otherwise.
    """

    if not config.enabled:
        raise RealExposureAssetDisabledError(
            "real_exposure asset is disabled by default; set "
            "`enabled: true` in the asset's Dagster run config to authorise "
            "a real AkShare collection. The asset will not construct the "
            "AkshareClient or open any network connection while disabled."
        )

    effective_from_date = _parse_effective_from(config.mapping_effective_from)
    effective_to_date = _parse_effective_to(config.mapping_effective_to)
    observed_at_dt = _parse_observed_at(config.observed_at)

    client: RealExposureClientProtocol = _build_akshare_client()

    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = session_factory(engine)
    try:
        result = collect_and_persist_real_exposure(
            client=client,
            etf_symbol=config.etf_symbol,
            etf_exchange=config.etf_exchange,
            index_code=config.index_code,
            mapping_effective_from=effective_from_date,
            observed_at=observed_at_dt,
            uow_factory=lambda: SqlAlchemyUnitOfWork(factory),
            holding_year=config.holding_year,
            mapping_effective_to=effective_to_date,
            revision=config.revision,
            confidence=Decimal(str(config.confidence)),
        )
    finally:
        engine.dispose()

    context.log.info(
        "real_exposure: etf_id=%s index_id=%s profile_id=%s mapping_id=%s "
        "holding_id=%s effective_from=%s effective_to=%s revision=%s",
        result.etf_id,
        result.index_id,
        result.profile_id,
        result.mapping_id,
        result.holding_snapshot_id,
        effective_from_date.isoformat(),
        effective_to_date.isoformat() if effective_to_date is not None else "",
        config.revision,
    )

    metadata: dict[str, Any] = {
        "etf_id": str(result.etf_id),
        "index_id": str(result.index_id),
        "profile_id": str(result.profile_id),
        "profile_content_hash": result.profile_content_hash,
        "constituent_snapshot_id": str(result.constituent_snapshot_id),
        "constituent_content_hash": result.constituent_content_hash,
        "mapping_id": str(result.mapping_id),
        "mapping_content_hash": result.mapping_content_hash,
        "holding_snapshot_id": str(result.holding_snapshot_id),
        "holding_content_hash": result.holding_content_hash,
        "constituents_raw_payload_hash": result.constituents_raw_payload_hash,
        "holdings_raw_payload_hash": result.holdings_raw_payload_hash,
        "etf_symbol": config.etf_symbol,
        "etf_exchange": config.etf_exchange,
        "index_code": config.index_code,
        "mapping_effective_from": effective_from_date.isoformat(),
        "mapping_effective_to": (
            effective_to_date.isoformat() if effective_to_date is not None else ""
        ),
        "observed_at": observed_at_dt.isoformat(),
        "holding_year": config.holding_year,
        "revision": config.revision,
        "confidence": str(config.confidence),
        "enabled": config.enabled,
    }
    return dg.MaterializeResult(metadata=metadata)


__all__ = [
    "RealExposureAssetConfig",
    "RealExposureAssetConfigError",
    "RealExposureAssetDisabledError",
    "real_exposure",
]
