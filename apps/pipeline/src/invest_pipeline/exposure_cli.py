"""DC-3 atomic slice: safe fixture-only manual Exposure persistence CLI.

This module provides a single-entry CLI for persisting an AKShare exposure
bundle from a local fixture file without ever touching the network or
constructing a live AkShare client.

Invocation::

    python -m invest_pipeline.exposure_cli --etf-id UUID [--fixture-path PATH]

Exit codes:
    0  success — one deterministic JSON line on stdout
    1  error  — a single ``error: ...`` line on stderr (no traceback)

The CLI never outputs raw payloads, database URLs, or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Never, TextIO
from uuid import UUID

from invest_storage.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.errors import RealProviderRequiresExplicitEnablementError
from invest_pipeline.adapters.exposure import AKShareExposureAdapter
from invest_pipeline.adapters.exposure.akshare_adapter import DEFAULT_FIXTURE_NAME
from invest_pipeline.config import get_settings
from invest_pipeline.exposure_service import (
    EtfIdMismatchError,
    ExposurePersistResult,
    ExposureServiceError,
    IndexCodeMismatchError,
    InstrumentNotFoundError,
    persist_exposure,
)


def _validate_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID: {value!r}") from exc


class _SilentErrorArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._error_written = False

    def error(self, message: str) -> Never:
        if not self._error_written:
            self._error_written = True
            sys.stderr.write(f"error: {message}\n")
        raise SystemExit(2)


def build_parser() -> _SilentErrorArgumentParser:
    parser = _SilentErrorArgumentParser(
        prog="invest_pipeline.exposure_cli",
        description="Persist an AKShare exposure bundle from a local fixture.",
    )
    parser.add_argument(
        "--etf-id",
        type=_validate_uuid,
        required=True,
        help="Target ETF UUID (used to rebind etf_index_mapping and etf_holdings).",
    )
    parser.add_argument(
        "--fixture-path",
        type=str,
        default=None,
        help=(
            f"Path to a JSON fixture file. "
            f"When omitted the canonical fixture ({DEFAULT_FIXTURE_NAME}) is used."
        ),
    )
    return parser


def _rebind_etf_id(payload: dict, etf_id: UUID) -> dict:
    """Return a deep copy of ``payload`` with both ETF sections rebound to ``etf_id``.

    Rebinds ``etf_index_mapping.etf_id`` and ``etf_holdings.etf_id`` in a
    fresh copy so the caller's adapter-owned payload is never mutated.
    """
    copy = deepcopy(payload)
    copy["etf_index_mapping"]["etf_id"] = str(etf_id)
    copy["etf_holdings"]["etf_id"] = str(etf_id)
    return copy


def _build_success_line(result: ExposurePersistResult) -> str:
    return json.dumps(
        {
            "index_id": str(result.index_id),
            "profile_id": str(result.profile_id),
            "profile_content_hash": result.profile_content_hash,
            "constituent_snapshot_id": str(result.constituent_snapshot_id),
            "constituent_content_hash": result.constituent_content_hash,
            "mapping_id": str(result.mapping_id),
            "mapping_content_hash": result.mapping_content_hash,
            "holding_snapshot_id": str(result.holding_snapshot_id),
            "holding_content_hash": result.holding_content_hash,
        },
        separators=(",", ":"),
    )


def _translate_error(exc: Exception) -> str:
    if isinstance(exc, RealProviderRequiresExplicitEnablementError):
        return f"adapter error: {exc}"
    if isinstance(exc, FileNotFoundError):
        return f"fixture not found: {exc}"
    if isinstance(exc, InstrumentNotFoundError):
        return f"instrument error: {exc}"
    if isinstance(exc, (EtfIdMismatchError, IndexCodeMismatchError)):
        return f"payload validation error: {exc}"
    if isinstance(exc, ExposureServiceError):
        return f"service error: {exc}"
    if isinstance(exc, ValueError):
        return f"malformed payload: {exc}"
    return "storage error: operation failed"


def run(
    *,
    etf_id: UUID,
    fixture_path: str | Path | None,
    adapter: AKShareExposureAdapter,
    uow_factory,
    stdout: TextIO | None = None,
) -> int:
    resolved_path = fixture_path if fixture_path else DEFAULT_FIXTURE_NAME
    raw_payload = adapter.fetch_standardized_payload(fixture_path=resolved_path)
    rebound = _rebind_etf_id(raw_payload, etf_id)
    result = persist_exposure(rebound, uow_factory)
    line = _build_success_line(result)
    (stdout or sys.stdout).write(line + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    etf_id: UUID = args.etf_id
    fixture_path: str | None = args.fixture_path

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def uow_factory():
        return SqlAlchemyUnitOfWork(session_factory)

    adapter = AKShareExposureAdapter()

    try:
        return run(
            etf_id=etf_id,
            fixture_path=fixture_path,
            adapter=adapter,
            uow_factory=uow_factory,
        )
    except Exception as exc:  # noqa: BLE001
        error_msg = _translate_error(exc)
        (sys.stderr).write(f"error: {error_msg}\n")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
