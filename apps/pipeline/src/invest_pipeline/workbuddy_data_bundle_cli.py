"""Manual one-shot ingestion for WorkBuddy DataBundle deliveries."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from invest_domain.strategy import DataRequest
from invest_storage import build_engine, session_factory
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

from invest_pipeline.config import Settings, get_settings
from invest_pipeline.integrations.workbuddy_data_bundle_intake import (
    DataBundleIntakeError,
    ingest_data_bundle,
)

_INVALID_INPUT_CODE = "data_bundle_invalid_input"
_INVALID_INPUT_MESSAGE = "Data bundle CLI input is not a regular file."
_INVALID_REQUEST_CODE = "data_bundle_invalid_request"
_INVALID_REQUEST_MESSAGE = "Data bundle request JSON does not match the DataRequest contract."
_INGEST_FAILED_CODE = "data_bundle_intake_failed"
_INGEST_FAILED_MESSAGE = "Data bundle intake failed."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invest_pipeline.workbuddy_data_bundle_cli",
        description="Process a single WorkBuddy DataBundle delivery once (no scheduler).",
    )
    parser.add_argument(
        "--request-json-file",
        type=Path,
        required=True,
        help="path to the sanitized DataRequest JSON file",
    )
    parser.add_argument(
        "--bundle-json-file",
        type=Path,
        required=True,
        help="path to the raw DataBundle payload bytes",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        help="immutable archive root (defaults to the pipeline WorkBuddy bridge root)",
    )
    return parser


def _read_input(path: Path, *, label: str) -> bytes:
    try:
        is_symlink = path.is_symlink()
    except OSError:
        raise DataBundleIntakeError(_INVALID_INPUT_CODE, _INVALID_INPUT_MESSAGE) from None
    if is_symlink or not path.is_file():
        raise DataBundleIntakeError(_INVALID_INPUT_CODE, _INVALID_INPUT_MESSAGE) from None
    try:
        return path.read_bytes()
    except OSError:
        raise DataBundleIntakeError(_INVALID_INPUT_CODE, _INVALID_INPUT_MESSAGE) from None


def _load_request(raw_bytes: bytes, *, loader: Callable[[Any], DataRequest]) -> DataRequest:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise DataBundleIntakeError(_INVALID_REQUEST_CODE, _INVALID_REQUEST_MESSAGE) from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise DataBundleIntakeError(_INVALID_REQUEST_CODE, _INVALID_REQUEST_MESSAGE) from None
    if not isinstance(payload, dict):
        raise DataBundleIntakeError(_INVALID_REQUEST_CODE, _INVALID_REQUEST_MESSAGE) from None
    try:
        return loader(payload)
    except Exception:
        raise DataBundleIntakeError(_INVALID_REQUEST_CODE, _INVALID_REQUEST_MESSAGE) from None


def _success_payload(outcome: Any, request: DataRequest) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "archive_uri": outcome.archive.archive_uri,
        "run_id": str(outcome.run.run_id),
        "artifact_id": str(outcome.artifact.artifact_id),
        "idempotent": bool(outcome.idempotent),
    }


def _error_payload(exc: Exception) -> dict[str, str]:
    code = getattr(exc, "code", None) or _INGEST_FAILED_CODE
    return {"error": str(code), "status": "error"}


def run_ingest(
    request_file: Path,
    bundle_file: Path,
    archive_root: Path,
    *,
    settings: Settings | None = None,
    engine_builder: Callable[[str], Any] = build_engine,
    session_factory_builder: Callable[[Any], Any] = session_factory,
    uow_factory: Callable[[Any], Any] = SqlAlchemyUnitOfWork,
    request_loader: Callable[[Any], DataRequest] = DataRequest.from_mapping,
    bundle_reader: Callable[[Path, str], bytes] = _read_input,
    ingestor: Callable[..., Any] = ingest_data_bundle,
) -> int:
    try:
        request_bytes = bundle_reader(request_file, label="request")
        bundle_bytes = bundle_reader(bundle_file, label="bundle")
        request = _load_request(request_bytes, loader=request_loader)
        configured = settings or get_settings()
        engine = engine_builder(configured.database_url)
        try:
            sessions = session_factory_builder(engine)
            uow = uow_factory(sessions)
            outcome = ingestor(request, bundle_bytes, archive_root, uow)
        finally:
            dispose = getattr(engine, "dispose", None)
            if dispose is not None:
                dispose()
    except Exception as exc:
        print(
            json.dumps(_error_payload(exc), separators=(",", ":"), sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            _success_payload(outcome, request),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    archive_root = (
        args.archive_root.resolve()
        if args.archive_root is not None
        else settings.workbuddy_bridge_root
    )
    return run_ingest(
        args.request_json_file,
        args.bundle_json_file,
        archive_root,
        settings=settings,
    )


if __name__ == "__main__":
    raise SystemExit(main())
