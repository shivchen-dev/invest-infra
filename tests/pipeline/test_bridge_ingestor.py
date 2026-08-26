"""Focused tests for the safe WorkBuddy archive bridge."""

from types import SimpleNamespace
from uuid import UUID

from invest_pipeline.integrations.bridge_ingestor import import_archived_candidate_run
from invest_pipeline.workbuddy_candidates.archive import archive_candidates


class _Repo:
    def __init__(self):
        self.items = {}
        self.save_resolution_calls: list[tuple] = []
        self.save_admission_calls: list[tuple] = []

    def add(self, item):
        key = next(
            getattr(item, name)
            for name in ("observation_id", "artifact_id", "run_id")
            if hasattr(item, name)
        )
        self.items[key] = item
        return item

    def get_by_id(self, key):
        return self.items.get(key)

    def list_by_run(self, run_id, *, limit=100, offset=0):
        items = [item for item in self.items.values() if item.run_id == run_id]
        return items[offset : offset + limit]

    def save_resolution(self, observation):
        self.save_resolution_calls.append(
            (
                observation.observation_id,
                observation.instrument_id,
                dict(observation.metadata),
            )
        )
        existing = self.items.get(observation.observation_id)
        if existing is None:
            raise LookupError(observation.observation_id)
        # Mirror what the SQL implementation will do: rewrite only
        # instrument_id and metadata; everything else stays untouched.
        replaced = SimpleNamespace(
            observation_id=existing.observation_id,
            run_id=existing.run_id,
            artifact_id=existing.artifact_id,
            observed_at=existing.observed_at,
            as_of=existing.as_of,
            source_uri=existing.source_uri,
            producer=existing.producer,
            payload=existing.payload,
            symbol=existing.symbol,
            instrument_id=observation.instrument_id,
            admission_status=existing.admission_status,
            metadata=dict(observation.metadata),
        )
        self.items[observation.observation_id] = replaced
        return replaced


class _Instruments:
    def __init__(self):
        self.by_key: dict[tuple[str, str], object] = {}

    def get_by_business_key(self, *, exchange: str, symbol: str):
        return self.by_key.get((exchange, symbol))


class _Uow:
    def __init__(self):
        self.external_workflow_runs = _Repo()
        self.external_artifacts = _Repo()
        self.external_observations = _Repo()
        self.instruments = _Instruments()


def _payload():
    return {
        "workflow_run_id": "wb-run-001",
        "trade_date": "2026-08-14",
        "strategy_id": "etf-screen-v1",
        "status": "succeeded",
        "candidates": [
            {"symbol": " 510300 ", "reason": "liquid"},
            {"symbol": "", "reason": "bad item"},
            {"symbol": "159915", "reason": "growth"},
        ],
    }


def test_bridge_imports_valid_candidates_and_is_idempotent(tmp_path):
    archive_candidates(_payload(), str(tmp_path))
    uow = _Uow()

    first = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-14",
        workflow_run_id="wb-run-001",
        uow=uow,
        resolver=lambda symbol: "510300" if symbol.strip() == "510300" else None,
    )
    second = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-14",
        workflow_run_id="wb-run-001",
        uow=uow,
    )

    assert first.run.intake_status.value == "partial"
    assert first.run.producer_status.value == "partial"
    assert len(first.observations) == 2
    assert {item.metadata["candidate_status"] for item in first.observations} == {
        "pending_validation",
        "needs_symbol_resolution",
    }
    assert second.idempotent
    assert second.observations == first.observations
    assert len(uow.external_observations.items) == 2


def test_bridge_rejects_manifest_tampering(tmp_path):
    archive_candidates(_payload(), str(tmp_path))
    candidates = tmp_path / "runs" / "2026-08-14" / "wb-run-001" / "candidates.json"
    candidates.write_text(candidates.read_text() + "\n", encoding="utf-8")

    try:
        import_archived_candidate_run(
            tmp_path,
            trade_date="2026-08-14",
            workflow_run_id="wb-run-001",
            uow=_Uow(),
        )
    except ValueError as exc:
        assert "hash or size" in str(exc)
    else:
        raise AssertionError("tampered archive must be rejected")


def _payload_with_unresolved_510300():
    return {
        "workflow_run_id": "wb-run-002",
        "trade_date": "2026-08-20",
        "strategy_id": "etf-screen-v1",
        "status": "succeeded",
        "candidates": [
            {"symbol": "510300.SH", "reason": "liquid"},
            {"symbol": "510500.SH", "reason": "broad"},
            {"symbol": "159915.SZ", "reason": "growth"},
        ],
    }


def test_idempotent_reimport_resolves_previously_unresolved_observation(tmp_path):
    """When re-importing an archived candidate run, observations whose
    instrument_id is still None are re-resolved with the injected symbol
    resolver. A successful resolution persists instrument_id and flips
    candidate_status to pending_validation without rewriting payload,
    source_uri, run/artifact identity, or admission_status."""
    archive_candidates(_payload_with_unresolved_510300(), str(tmp_path))
    uow = _Uow()

    # First import: nothing resolved yet → all three stay unresolved
    # (no SSE instrument rows for 510300/510500 in this fake).
    first = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-20",
        workflow_run_id="wb-run-002",
        uow=uow,
        resolver=lambda symbol: None,
    )
    assert first.idempotent is False
    assert {obs.metadata["candidate_status"] for obs in first.observations} == {
        "needs_symbol_resolution",
    }
    assert all(obs.instrument_id is None for obs in first.observations)

    # Second import: SSE rows for 510300 and 510500 now exist.
    id_300 = UUID("11111111-1111-1111-1111-111111111111")
    id_500 = UUID("22222222-2222-2222-2222-222222222222")
    uow.instruments.by_key[("SSE", "510300")] = SimpleNamespace(instrument_id=id_300)
    uow.instruments.by_key[("SSE", "510500")] = SimpleNamespace(instrument_id=id_500)

    second = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-20",
        workflow_run_id="wb-run-002",
        uow=uow,
        resolver=lambda symbol: symbol.split(".")[0] if "." in symbol else (symbol or None),
    )

    assert second.idempotent is True
    # Index by the qualified symbol that was originally stored so the
    # assertions don't depend on any new metadata fields. Only SSE rows
    # (510300.SH, 510500.SH) flip; 159915.SZ stays unresolved.
    by_symbol = {obs.symbol: obs for obs in second.observations}
    assert by_symbol["510300.SH"].metadata["candidate_status"] == "pending_validation"
    assert by_symbol["510500.SH"].metadata["candidate_status"] == "pending_validation"
    assert by_symbol["159915.SZ"].metadata["candidate_status"] == "needs_symbol_resolution"

    # save_resolution was called once per resolved observation; the
    # 159915.SZ observation must NOT have triggered a save_resolution call.
    assert len(uow.external_observations.save_resolution_calls) == 2
    saved_ids = {
        call[1]
        for call in uow.external_observations.save_resolution_calls
    }
    assert saved_ids == {id_300, id_500}

    # Bounded metadata rewrite: only candidate_status flipped; no payload,
    # source_uri, run/artifact identity, or admission_status touched.
    expected_ids = {"510300.SH": id_300, "510500.SH": id_500}
    for symbol, instrument_id in expected_ids.items():
        obs = by_symbol[symbol]
        assert obs.instrument_id == instrument_id
        assert obs.metadata["candidate_status"] == "pending_validation"
        assert obs.source_uri == second.artifact.logical_uri
        assert obs.run_id == second.run.run_id
        assert obs.artifact_id == second.artifact.artifact_id
        assert obs.payload  # payload still present
        assert obs.admission_status.value == "pending"

    # Unresolved 159915.SZ is unchanged: no instrument_id, original status,
    # no save_resolution call against it.
    obs_unresolved = by_symbol["159915.SZ"]
    assert obs_unresolved.instrument_id is None
    assert obs_unresolved.metadata["candidate_status"] == "needs_symbol_resolution"


def test_idempotent_reimport_leaves_still_unresolved_observation_unchanged(tmp_path):
    """When the resolver still cannot resolve a previously unresolved
    symbol, the observation stays exactly as it was: no instrument_id,
    candidate_status still needs_symbol_resolution, no save_resolution
    call."""
    archive_candidates(_payload_with_unresolved_510300(), str(tmp_path))
    uow = _Uow()

    import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-20",
        workflow_run_id="wb-run-002",
        uow=uow,
        resolver=lambda symbol: None,
    )

    second = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-20",
        workflow_run_id="wb-run-002",
        uow=uow,
        resolver=lambda symbol: None,
    )

    assert second.idempotent is True
    assert uow.external_observations.save_resolution_calls == []
    for obs in second.observations:
        assert obs.instrument_id is None
        assert obs.metadata["candidate_status"] == "needs_symbol_resolution"
        assert obs.admission_status.value == "pending"
