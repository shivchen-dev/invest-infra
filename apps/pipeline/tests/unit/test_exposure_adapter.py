"""DC-3B exposure adapter integration tests.

These tests drive the standardized payload from the bundled JSON
fixture through the pure mapping layer and the AKShare adapter
boundary. The slice is intentionally minimal:

* the fixture is a static JSON file under ``tests/unit/fixtures/exposure/``;
* the AKShare adapter defaults to ``enabled=False`` and refuses to
  touch the network at construction or fetch when disabled;
* mapping helpers are pure and accept the standardized payload
  directly so tests can inject a fake client or a loaded fixture
  without any I/O.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from invest_domain.exposure import (
    EtfHoldingSnapshot,
    EtfIndexMapping,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.exposure import (
    AKShareExposureAdapter,
    AKShareExposureConfig,
    AKShareExposurePayload,
    AKShareExposureStandardizedPayload,
    map_etf_holding_snapshot,
    map_etf_index_mapping,
    map_index_constituent_snapshot,
    map_index_profile,
    map_standardized_payload,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "exposure" / "akshare_exposure_payload.json"

_ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_INDEX_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
_AS_OF_DATE = date(2026, 7, 31)
_FIXED_SNAPSHOT_ID = UUID("11111111-2222-3333-4444-555555555555")
_FIXED_CREATED_AT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def _fixed_id_factory() -> UUID:
    return _FIXED_SNAPSHOT_ID


def _fixed_now_factory() -> datetime:
    return _FIXED_CREATED_AT


def _load_fixture_payload() -> dict[str, Any]:
    """Load the fixture file used by the tests."""

    if not _FIXTURE_PATH.exists():
        pytest.skip(f"fixture not present: {_FIXTURE_PATH}")
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


class FakeClient:
    """Fake AKShare client used for the fetch payload integration test."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        self.calls = 0

    def fetch_exposure_payload(self) -> Mapping[str, Any]:
        self.calls += 1
        return self._payload


class TestFixtureMapping:
    def test_fixture_file_is_well_formed(self) -> None:
        payload = _load_fixture_payload()
        assert payload["provider_key"] == "akshare"
        assert payload["dataset_key"] == "exposure_bundle"
        assert payload["observed_at"] == "2026-07-31T12:00:00+00:00"
        assert payload["revision"] == 1
        for key in (
            "index_profile",
            "index_constituents",
            "etf_index_mapping",
            "etf_holdings",
        ):
            assert key in payload

    def test_index_profile_is_mapped_from_fixture(self) -> None:
        payload = _load_fixture_payload()
        profile = map_index_profile(payload)
        assert isinstance(profile, IndexProfile)
        assert profile.index_code == "000300"
        assert profile.index_name == "CSI 300"
        assert profile.category == "Broad Market"
        assert profile.as_of_date == _AS_OF_DATE
        assert profile.provenance.provider_key == "akshare"
        assert profile.provenance.dataset_key == "exposure_bundle"
        assert profile.provenance.observed_at == _OBSERVED_AT
        assert profile.provenance.revision == 1
        assert profile.provenance.confidence == Decimal("0.95")

    def test_index_constituents_snapshot_is_mapped_from_fixture(self) -> None:
        payload = _load_fixture_payload()
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert isinstance(snapshot, IndexConstituentSnapshot)
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.index_code == "000300"
        assert snapshot.as_of_date == _AS_OF_DATE
        assert snapshot.observed_at == _OBSERVED_AT
        assert snapshot.created_at == _FIXED_CREATED_AT
        assert [c.stock_code for c in snapshot.constituents] == [
            "600519",
            "601318",
            "000858",
            "300750",
        ]
        assert snapshot.constituents[0].weight == Decimal("0.10")
        assert snapshot.constituents[2].weight == Decimal("0.03")
        assert snapshot.constituents[2].industry == "白酒"

    def test_etf_index_mapping_is_mapped_from_fixture(self) -> None:
        payload = _load_fixture_payload()
        mapping = map_etf_index_mapping(payload)
        assert isinstance(mapping, EtfIndexMapping)
        assert mapping.etf_id == _ETF_ID
        assert mapping.index_id == _INDEX_ID
        assert mapping.effective_from == date(2024, 1, 1)
        assert mapping.effective_to == date(2026, 12, 31)
        assert mapping.observed_at == _OBSERVED_AT
        assert mapping.provenance.provider_key == "akshare"

    def test_etf_holding_snapshot_is_mapped_from_fixture(self) -> None:
        payload = _load_fixture_payload()
        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert isinstance(snapshot, EtfHoldingSnapshot)
        assert snapshot.id == _FIXED_SNAPSHOT_ID
        assert snapshot.etf_id == _ETF_ID
        assert snapshot.as_of_date == _AS_OF_DATE
        assert [h.stock_code for h in snapshot.holdings] == [
            "600519",
            "601318",
            "000858",
        ]
        assert snapshot.holdings[0].weight == Decimal("0.10")
        assert snapshot.holdings[0].industry == "白酒"
        assert snapshot.holdings[2].weight == Decimal("0.03")

    def test_map_standardized_payload_returns_all_four_objects(self) -> None:
        payload = _load_fixture_payload()
        result = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert set(result.keys()) == {
            "index_profile",
            "index_constituents",
            "etf_index_mapping",
            "etf_holdings",
        }
        assert isinstance(result["index_profile"], IndexProfile)
        assert isinstance(result["index_constituents"], IndexConstituentSnapshot)
        assert isinstance(result["etf_index_mapping"], EtfIndexMapping)
        assert isinstance(result["etf_holdings"], EtfHoldingSnapshot)
        assert (
            result["index_constituents"].provenance.observed_at
            == result["etf_holdings"].provenance.observed_at
        )


class TestFixtureDeterminism:
    def test_deterministic_hashes_for_repeated_mapping(self) -> None:
        payload = _load_fixture_payload()
        first = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first["index_profile"].content_hash == second["index_profile"].content_hash
        assert (
            first["index_constituents"].content_hash
            == second["index_constituents"].content_hash
        )
        assert (
            first["etf_index_mapping"].content_hash
            == second["etf_index_mapping"].content_hash
        )
        assert (
            first["etf_holdings"].content_hash
            == second["etf_holdings"].content_hash
        )

    def test_default_factories_still_produce_valid_objects(self) -> None:
        payload = _load_fixture_payload()
        result = map_standardized_payload(payload)
        assert isinstance(result["index_profile"].content_hash, str)
        assert len(result["index_constituents"].content_hash) == 64
        assert isinstance(result["etf_holdings"].id, UUID)


class TestProvenanceSharing:
    def test_map_standardized_payload_shares_one_provenance_instance(self) -> None:
        payload = _load_fixture_payload()
        result = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        shared = result["index_profile"].provenance
        assert result["index_constituents"].provenance is shared
        assert result["etf_index_mapping"].provenance is shared
        assert result["etf_holdings"].provenance is shared

    def test_each_map_builds_its_own_provenance_when_called_independently(self) -> None:
        payload = _load_fixture_payload()
        profile = map_index_profile(payload)
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        mapping = map_etf_index_mapping(payload)
        holding = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        # Each map_* call built its own provenance from the payload
        # envelope — all four are equal in field values but distinct
        # Python objects.
        provenances = [
            profile.provenance,
            snapshot.provenance,
            mapping.provenance,
            holding.provenance,
        ]
        assert all(prov == profile.provenance for prov in provenances)
        identities = {id(prov) for prov in provenances}
        assert len(identities) == 4


class TestAKShareExposureMappingValidation:
    def test_missing_top_level_key_raises(self) -> None:
        payload = _load_fixture_payload()
        payload.pop("etf_holdings")
        with pytest.raises(ValueError):
            map_standardized_payload(payload)

    def test_malformed_weight_is_rejected(self) -> None:
        payload = _load_fixture_payload()
        payload["index_constituents"]["constituents"][0]["weight"] = "1.5"
        with pytest.raises(ValueError):
            map_index_constituent_snapshot(payload)

    def test_malformed_observed_at_is_rejected(self) -> None:
        payload = _load_fixture_payload()
        payload["observed_at"] = "not-a-date"
        with pytest.raises(ValueError):
            map_index_profile(payload)

    def test_negative_confidence_is_rejected(self) -> None:
        payload = _load_fixture_payload()
        payload["confidence"] = "-0.1"
        with pytest.raises(ValueError):
            map_index_profile(payload)

    def test_duplicate_constituent_is_rejected_by_factory(self) -> None:
        payload = _load_fixture_payload()
        constituents = payload["index_constituents"]["constituents"]
        constituents.append(dict(constituents[0]))
        with pytest.raises(ValueError):
            map_index_constituent_snapshot(payload)

    def test_rev_below_one_is_rejected(self) -> None:
        payload = _load_fixture_payload()
        payload["revision"] = 0
        with pytest.raises(ValueError):
            map_index_profile(payload)


class TestAKShareExposureAdapter:
    def test_default_is_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        assert adapter.enabled is False
        assert adapter.is_disabled is True

    def test_default_construction_does_not_call_client(self) -> None:
        client = FakeClient(_load_fixture_payload())
        adapter = AKShareExposureAdapter(client=client)
        assert adapter.enabled is False
        assert client.calls == 0

    def test_fetch_raises_when_disabled_and_no_fixture_path(self) -> None:
        client = FakeClient(_load_fixture_payload())
        adapter = AKShareExposureAdapter(client=client)
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()
        assert client.calls == 0

    def test_fetch_loads_fixture_when_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(
            fixture_path="akshare_exposure_payload.json"
        )
        assert isinstance(payload, AKShareExposurePayload)
        assert payload["provider_key"] == "akshare"

    def test_fetch_calls_client_when_enabled(self) -> None:
        fixture = _load_fixture_payload()
        client = FakeClient(fixture)
        adapter = AKShareExposureAdapter(
            client=client,
            config=AKShareExposureConfig(enabled=True),
        )
        payload = adapter.fetch_standardized_payload()
        assert payload["provider_key"] == "akshare"
        assert client.calls == 1

    def test_fetch_skips_client_even_when_present_if_disabled(self) -> None:
        client = FakeClient(_load_fixture_payload())
        adapter = AKShareExposureAdapter(
            client=client,
            config=AKShareExposureConfig(enabled=False),
        )
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()
        assert client.calls == 0

    def test_fixture_path_resolution_uses_absolute_when_provided(self, tmp_path: Path) -> None:
        fixture = _load_fixture_payload()
        fixture_file = tmp_path / "custom.json"
        fixture_file.write_text(json.dumps(fixture), encoding="utf-8")
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(fixture_path=fixture_file)
        assert payload["provider_key"] == "akshare"

    def test_fetch_raises_on_missing_fixture(self, tmp_path: Path) -> None:
        adapter = AKShareExposureAdapter()
        missing = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            adapter.fetch_standardized_payload(fixture_path=missing)


class TestAKShareExposureConfig:
    def test_default_is_disabled(self) -> None:
        assert AKShareExposureConfig().enabled is False

    def test_invalid_enabled_type_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            AKShareExposureConfig(enabled="yes")  # type: ignore[arg-type]

    def test_invalid_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(provider_key="")

    def test_invalid_dataset_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(dataset_key="   ")


class TestStandardizedPayloadType:
    def test_alias_is_a_mapping(self) -> None:
        payload = _load_fixture_payload()
        assert isinstance(payload, AKShareExposureStandardizedPayload)
