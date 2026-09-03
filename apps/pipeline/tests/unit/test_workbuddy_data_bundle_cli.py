from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from invest_domain.integration import (
    ExternalArtifact,
    ExternalWorkflowRun,
    IntakeStatus,
    ProducerStatus,
)
from invest_domain.strategy import DataRequest
from invest_pipeline import workbuddy_data_bundle_cli as cli
from invest_pipeline.config import Settings
from invest_pipeline.integrations.workbuddy_data_bundle_intake import (
    DataBundleIntakeError,
    DataBundleIntakeOutcome,
)

REQUEST_ID = "archive-cli-001"
RUN_ID = UUID("9931e5a0-6bb3-5073-902c-bad147a7cd08")
ARTIFACT_ID = UUID("88d4b9a5-6e88-527b-9297-9c3da70068b4")


def _request_bytes() -> bytes:
    payload = {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": REQUEST_ID,
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "as_of": "2026-09-02",
        "max_delivery_lag_days": 2,
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "required_fields": ["sector_code", "change_percent"],
                "allowed_connectors": ["tdx-connector"],
            }
        ],
        "output_contract": "workbuddy-data-bundle/1.0",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _bundle_bytes() -> bytes:
    payload = {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": REQUEST_ID,
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "attempts": [
                    {
                        "connector": "tdx-connector",
                        "tool": "get_sector_ranking",
                        "parameters": {"market": "cn", "page": 1},
                        "status": "succeeded",
                        "error_code": None,
                    }
                ],
                "as_of": "2026-09-02",
                "pagination": {"complete": True},
                "sample_count": 1,
                "fields": ["sector_code", "change_percent"],
                "units": {"change_percent": "percent"},
                "records": [{"sector_code": "BK1036", "change_percent": 2.5}],
            }
        ],
        "warnings": [],
        "errors": [],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, bytes]:
    request_path = tmp_path / "request.json"
    bundle_path = tmp_path / "bundle.json"
    bundle_raw = _bundle_bytes()
    request_path.write_bytes(_request_bytes())
    bundle_path.write_bytes(bundle_raw)
    return request_path, bundle_path, bundle_raw


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _make_outcome() -> DataBundleIntakeOutcome:
    generated_at = datetime(2026, 9, 3, 4, 0, 0, tzinfo=UTC)
    run = ExternalWorkflowRun(
        run_id=RUN_ID,
        producer="workbuddy",
        schema_version="workbuddy-data-bundle/1.0",
        producer_status=ProducerStatus.SUCCEEDED,
        intake_status=IntakeStatus.ACCEPTED,
        started_at=generated_at,
        finished_at=generated_at,
        metadata={},
    )
    artifact = ExternalArtifact(
        artifact_id=ARTIFACT_ID,
        run_id=RUN_ID,
        logical_uri=f"archive://runs/{REQUEST_ID}/data-bundle.json",
        content_hash="a" * 64,
        media_type="application/json",
        size_bytes=1,
        created_at=generated_at,
        metadata={},
    )
    return DataBundleIntakeOutcome(
        archive=SimpleNamespace(archive_uri=f"archive://runs/{REQUEST_ID}"),
        run=run,
        artifact=artifact,
        idempotent=False,
    )


def test_parser_exposes_three_flags_and_main_wires_archive_root_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = cli.build_parser()
    help_text = parser.format_help()
    assert "--request-json-file" in help_text
    assert "--bundle-json-file" in help_text
    assert "--archive-root" in help_text

    request_path, bundle_path, _ = _write_inputs(tmp_path)
    captured: dict[str, Path] = {}

    def fake_run(
        request_file: Path, bundle_file: Path, archive_root: Path, **_kwargs: object
    ) -> int:
        captured["request_file"] = request_file
        captured["bundle_file"] = bundle_file
        captured["archive_root"] = archive_root
        return 0

    monkeypatch.setattr(cli, "run_ingest", fake_run)

    exit_code = cli.main(
        [
            "--request-json-file",
            str(request_path),
            "--bundle-json-file",
            str(bundle_path),
        ]
    )

    assert exit_code == 0
    assert captured["request_file"] == request_path
    assert captured["bundle_file"] == bundle_path
    assert captured["archive_root"] == Settings().workbuddy_bridge_root


def test_valid_inputs_call_ingest_with_exact_bundle_bytes_and_emit_sanitized_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path, bundle_path, bundle_raw = _write_inputs(tmp_path)
    engine = _FakeEngine()
    captured: dict[str, object] = {}
    outcome = _make_outcome()

    def fake_ingestor(
        request: DataRequest, raw_bytes: bytes, archive_root: Path, passed_uow: object
    ) -> DataBundleIntakeOutcome:
        captured["request"] = request
        captured["raw_bytes"] = raw_bytes
        captured["archive_root"] = archive_root
        captured["uow"] = passed_uow
        return outcome

    exit_code = cli.run_ingest(
        request_path,
        bundle_path,
        tmp_path / "archive",
        engine_builder=lambda _url: engine,
        session_factory_builder=lambda _engine: "sessions",
        uow_factory=lambda _sessions: object(),
        ingestor=fake_ingestor,
    )

    captured_out = capsys.readouterr().out
    assert exit_code == 0
    assert captured["raw_bytes"] == bundle_raw
    assert engine.disposed is True
    assert json.loads(captured_out) == {
        "request_id": REQUEST_ID,
        "archive_uri": f"archive://runs/{REQUEST_ID}",
        "run_id": str(RUN_ID),
        "artifact_id": str(ARTIFACT_ID),
        "idempotent": False,
    }
    assert str(tmp_path) not in captured_out
    assert bundle_raw.decode("utf-8") not in captured_out


@pytest.mark.parametrize("kind", ["request", "bundle"])
def test_symlink_input_is_rejected_without_calling_ingestor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    request_path = tmp_path / "request.json"
    bundle_path = tmp_path / "bundle.json"
    outside = tmp_path / "outside"
    outside.mkdir()
    request_path.write_text("placeholder")
    bundle_path.write_text("placeholder")
    target = request_path if kind == "request" else bundle_path
    target.unlink()
    target.symlink_to(outside, target_is_directory=True)

    ingested: list[bool] = []

    def fail_ingestor(*_args: object, **_kwargs: object) -> object:
        ingested.append(True)
        raise AssertionError("ingestor must not be called for symlink input")

    exit_code = cli.run_ingest(
        request_path,
        bundle_path,
        tmp_path / "archive",
        engine_builder=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("engine must not be built for symlink input")
        ),
        ingestor=fail_ingestor,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert ingested == []
    assert json.loads(captured.err) == {"error": "data_bundle_invalid_input", "status": "error"}
    assert str(outside) not in captured.err


def test_malformed_request_json_returns_nonzero_with_sanitized_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("{not-valid-json", encoding="utf-8")
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(_bundle_bytes())

    ingested: list[bool] = []

    def fail_ingestor(*_args: object, **_kwargs: object) -> object:
        ingested.append(True)
        raise AssertionError("ingestor must not be called for malformed request JSON")

    exit_code = cli.run_ingest(
        request_path,
        bundle_path,
        tmp_path / "archive",
        engine_builder=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("engine must not be built for malformed request JSON")
        ),
        ingestor=fail_ingestor,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert ingested == []
    assert json.loads(captured.err) == {"error": "data_bundle_invalid_request", "status": "error"}
    assert "not-valid-json" not in captured.err
    assert captured.out == ""


def test_ingest_data_bundle_error_returns_nonzero_with_stable_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path, bundle_path, _ = _write_inputs(tmp_path)
    engine = _FakeEngine()
    sensitive = "database url=postgres://u:pwd@host/private/secret"

    def failing_ingestor(
        _request: DataRequest, _raw_bytes: bytes, _archive_root: Path, _uow: object
    ) -> DataBundleIntakeOutcome:
        raise DataBundleIntakeError("data_bundle_intake_conflict", f"{sensitive} must not leak")

    exit_code = cli.run_ingest(
        request_path,
        bundle_path,
        tmp_path / "archive",
        engine_builder=lambda _url: engine,
        session_factory_builder=lambda _engine: "sessions",
        uow_factory=lambda _sessions: object(),
        ingestor=failing_ingestor,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert engine.disposed is True
    assert json.loads(captured.err) == {"error": "data_bundle_intake_conflict", "status": "error"}
    assert sensitive not in captured.err
    assert captured.out == ""
