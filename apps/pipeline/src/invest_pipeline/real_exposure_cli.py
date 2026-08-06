"""Explicit live CLI for collecting and persisting real ETF exposure.

This CLI hits the real AkShare HTTP endpoints via
:class:`~invest_pipeline.adapters.akshare.client.AkshareClient` and
persists the resulting exposure rows into PostgreSQL. It is therefore
intentionally safe-by-default and mirrors the
:mod:`invest_pipeline.cifang_smoke` double-gate contract:

* ``INVEST_PIPELINE_AKSHARE_ENABLED=true`` is required so the adapter
  refuses a missing deployment configuration (Cifang-style opt-in, see
  :class:`AkshareSettings.enabled`).
* The explicit ``--confirm-network`` opt-in flag must be supplied on
  the command line. ``--confirm-network`` alone never enables the
  adapter; both gates must be present.

If either gate is missing the CLI exits non-zero with a concise
sanitized error before reaching the network, and never constructs
:class:`Settings`, the SQLAlchemy ``Engine`` or the
:class:`AkshareClient`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Never, TextIO

from invest_storage.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.akshare.client import AkshareClient
from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.config import get_settings
from invest_pipeline.real_exposure_service import (
    RealExposurePersistResult,
    collect_and_persist_real_exposure,
)

_AKSHARE_ENABLED_ENV = "INVEST_PIPELINE_AKSHARE_ENABLED"


class RealExposureCLIConfigError(Exception):
    """Raised when the CLI inputs are incomplete or unsafe.

    The CLI translates this into a non-zero exit code (``2``) and a
    single short ``refused:`` / ``error:`` line on stderr. It is
    **never** raised when the network is reached; only the
    pre-flight gates surface this error.
    """


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        print(f"error: invalid arguments: {message}", file=sys.stderr)
        raise SystemExit(2)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _observed(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO-8601 timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("must include a timezone")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="invest_pipeline.real_exposure_cli",
        description=(
            "Explicit live driver for collecting and persisting real ETF "
            "exposure. Requires INVEST_PIPELINE_AKSHARE_ENABLED=true and "
            "--confirm-network; either missing refuses the run before "
            "settings, engine and client are constructed."
        ),
    )
    parser.add_argument("--etf-symbol", required=True)
    parser.add_argument("--etf-exchange", required=True)
    parser.add_argument("--index-code", required=True)
    parser.add_argument("--mapping-effective-from", required=True, type=_date)
    parser.add_argument("--observed-at", required=True, type=_observed)
    parser.add_argument("--holding-year", default="")
    parser.add_argument("--mapping-effective-to", type=_date)
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--confidence", type=Decimal, default=Decimal("1"))
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help=(
            "Required explicit confirmation that this run will hit the "
            "real AkShare HTTP endpoints. The CLI refuses to start "
            "without it."
        ),
    )
    return parser


def _success(result: RealExposurePersistResult) -> str:
    values = {name: getattr(result, name) for name in result.__dataclass_fields__}
    return json.dumps(
        values,
        default=lambda value: str(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def run(*, args: argparse.Namespace, client: AkshareClient, uow_factory, stdout: TextIO) -> int:
    result = collect_and_persist_real_exposure(
        client=client,
        etf_symbol=args.etf_symbol,
        etf_exchange=args.etf_exchange,
        index_code=args.index_code,
        mapping_effective_from=args.mapping_effective_from,
        observed_at=args.observed_at,
        holding_year=args.holding_year,
        mapping_effective_to=args.mapping_effective_to,
        revision=args.revision,
        confidence=args.confidence,
        uow_factory=uow_factory,
    )
    stdout.write(_success(result) + "\n")
    return 0


def validate_opt_in(settings: AkshareSettings, *, confirm_network: bool) -> None:
    """Reject the run unless every opt-in lever is on.

    Mirrors the Cifang smoke double-gate: ``--confirm-network`` alone
    never enables the adapter, and ``enabled=True`` alone never
    satisfies the CLI. Either missing produces a sanitized
    :class:`RealExposureCLIConfigError` with no exception repr and no
    settings values printed — the CLI never reaches the network and
    never constructs engine / client when this raises.
    """

    if not settings.enabled:
        raise RealExposureCLIConfigError(
            f"{_AKSHARE_ENABLED_ENV}=true is required to run real "
            "exposure collection; set it to acknowledge the real AkShare "
            "opt-in"
        )
    if not confirm_network:
        raise RealExposureCLIConfigError(
            "--confirm-network is required to run real exposure collection"
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    stdout = sys.stdout
    stderr = sys.stderr

    try:
        akshare_settings = AkshareSettings()
        validate_opt_in(akshare_settings, confirm_network=args.confirm_network)
    except RealExposureCLIConfigError as exc:
        print(f"refused: {exc}", file=stderr)
        return 2

    try:
        settings = get_settings()
        engine = create_engine(settings.database_url, future=True)
    except Exception as exc:
        print(
            f"error: failed to construct settings/engine: {type(exc).__name__}",
            file=stderr,
        )
        return 2
    try:
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        client = AkshareClient(akshare_settings)
        return run(
            args=args,
            client=client,
            uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
            stdout=stdout,
        )
    except Exception:
        print("error: operation failed", file=stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
