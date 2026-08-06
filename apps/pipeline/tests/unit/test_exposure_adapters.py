"""Focused tests for the DC-3B exposure adapter slice.

The slice is intentionally minimal:

* the adapter defaults to ``enabled=False`` and never reaches the
  network at construction or fetch when disabled;
* mapping helpers are pure and accept the standardized payload
  directly; tests inject a fake client or load a fixture.

Coverage map:

* :class:`TestAKShareExposureConfig` — config defaults and validation.
* :class:`TestFixtureMapping` — fixture-driven mapping to the four
  domain objects.
* :class:`TestMappingValidation` — payload validation surfaces.
* :class:`TestAKShareExposureAdapterDisabled` — disabled is offline.
* :class:`TestAKShareExposureAdapterEnabled` — enabled calls client.
* :class:`TestFixturePathResolution` — fixture loader paths.
* :class:`TestClientProtocol` — runtime-checkable protocol.
* :class:`TestEndToEndAdapterAndMapping` — adapter + mapping wire-up.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.exposure import (
    AKShareExposureAdapter,
    AkShareExposureClientProtocol,
    AKShareExposureConfig,
    AKShareExposurePayload,
    map_etf_holding_snapshot,
    map_etf_index_mapping,
    map_index_constituent_snapshot,
    map_index_profile,
    map_standardized_payload,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "exposure"
    / "akshare_exposure_payload.json"
)


def _load_fixture() -> dict[str, Any]:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"exposure fixture not found: {FIXTURE_PATH}")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def payload() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture
def fixed_id() -> UUID:
    return UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


@pytest.fixture
def fixed_now() -> str:
    return "2026-08-01T00:00:00+00:00"


class FakeClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        self.calls = 0

    def fetch_exposure_payload(self) -> Mapping[str, Any]:
        self.calls += 1
        return self._payload


class MissingMethodClient:
    pass


class TestFixtureMapping:
    def test_fixture_file_exists(self) -> None:
        assert FIXTURE_PATH.exists()

    def test_index_profile_maps_to_domain_object(self, payload: dict[str, Any]) -> None:
        profile = map_index_profile(payload)
        assert profile.index_code == "000300"
        assert profile.index_name == "CSI 300"
        assert profile.category == "Broad Market"
        assert profile.provenance.provider_key == "akshare"
        assert profile.provenance.dataset_key == "exposure_bundle"
        assert profile.provenance.confidence == Decimal("0.95")

    def test_index_constituents_snapshot_uses_injected_factories(
        self,
        payload: dict[str, Any],
        fixed_id: UUID,
        fixed_now: str,
    ) -> None:
        from datetime import datetime

        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=lambda: fixed_id,
            now_factory=lambda: datetime.fromisoformat(fixed_now),
        )
        assert snapshot.id == fixed_id
        assert snapshot.index_code == "000300"
        codes = [c.stock_code for c in snapshot.constituents]
        assert codes == sorted(codes, key=lambda c: (not c.startswith("6"), c))

    def test_etf_index_mapping_round_trip(self, payload: dict[str, Any]) -> None:
        mapping = map_etf_index_mapping(payload)
        assert mapping.etf_id == UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        assert mapping.index_id == UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        assert mapping.effective_from.isoformat() == "2024-01-01"
        assert mapping.effective_to is not None
        assert mapping.effective_to.isoformat() == "2026-12-31"

    def test_etf_holding_snapshot_returns_sorted_holdings(
        self,
        payload: dict[str, Any],
        fixed_id: UUID,
        fixed_now: str,
    ) -> None:
        from datetime import datetime

        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=lambda: fixed_id,
            now_factory=lambda: datetime.fromisoformat(fixed_now),
        )
        codes = [h.stock_code for h in snapshot.holdings]
        assert codes == sorted(codes, key=lambda c: (not c.startswith("6"), c))
        assert snapshot.id == fixed_id

    def test_map_standardized_payload_returns_all_four(
        self,
        payload: dict[str, Any],
        fixed_id: UUID,
        fixed_now: str,
    ) -> None:
        from datetime import datetime

        result = map_standardized_payload(
            payload,
            id_factory=lambda: fixed_id,
            now_factory=lambda: datetime.fromisoformat(fixed_now),
        )
        assert set(result.keys()) == {
            "index_profile",
            "index_constituents",
            "etf_index_mapping",
            "etf_holdings",
        }

    def test_map_standardized_payload_shares_one_provenance_instance(
        self,
        payload: dict[str, Any],
    ) -> None:
        result = map_standardized_payload(payload)
        shared = result["index_profile"].provenance
        assert result["index_constituents"].provenance is shared
        assert result["etf_index_mapping"].provenance is shared
        assert result["etf_holdings"].provenance is shared

    def test_each_map_builds_own_provenance_independently(
        self,
        payload: dict[str, Any],
    ) -> None:
        profile = map_index_profile(payload)
        snapshot = map_index_constituent_snapshot(payload)
        mapping = map_etf_index_mapping(payload)
        holdings = map_etf_holding_snapshot(payload)
        provenances = [
            profile.provenance,
            snapshot.provenance,
            mapping.provenance,
            holdings.provenance,
        ]
        assert all(prov == profile.provenance for prov in provenances)
        assert len({id(prov) for prov in provenances}) == 4

    def test_duplicate_constituents_rejected(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["index_constituents"] = {
            "index_code": "000300",
            "as_of_date": "2026-07-31",
            "constituents": [
                {"stock_code": "600519", "weight": "0.10"},
                {"stock_code": "600519", "weight": "0.05"},
            ],
        }
        with pytest.raises(ValueError):
            map_index_constituent_snapshot(payload)

    def test_malformed_weight_rejected(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["index_constituents"]["constituents"][0]["weight"] = "1.5"
        with pytest.raises(ValueError):
            map_index_constituent_snapshot(payload)


class TestAKShareExposureConfig:
    def test_default_enabled_is_false(self) -> None:
        assert AKShareExposureConfig().enabled is False

    def test_default_provider_key_is_akshare(self) -> None:
        assert AKShareExposureConfig().provider_key == "akshare"

    def test_default_dataset_key_is_exposure_bundle(self) -> None:
        assert AKShareExposureConfig().dataset_key == "exposure_bundle"

    def test_enabled_can_be_overridden(self) -> None:
        assert AKShareExposureConfig(enabled=True).enabled is True


class TestAKShareExposureAdapterDisabled:
    def test_default_construction_is_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        assert adapter.enabled is False
        assert adapter.is_disabled is True

    def test_construction_does_not_invoke_client(self) -> None:
        client = FakeClient(_load_fixture())
        AKShareExposureAdapter(client=client)
        assert client.calls == 0

    def test_fetch_raises_when_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()

    def test_fetch_raises_when_disabled_even_with_client(self) -> None:
        client = FakeClient(_load_fixture())
        adapter = AKShareExposureAdapter(client=client)
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()
        assert client.calls == 0

    def test_fetch_loads_fixture_when_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(
            fixture_path=FIXTURE_PATH
        )
        assert isinstance(payload, AKShareExposurePayload)
        assert payload["provider_key"] == "akshare"
        assert payload["dataset_key"] == "exposure_bundle"

    def test_fetch_relative_fixture_path(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(
            fixture_path="akshare_exposure_payload.json"
        )
        assert payload["provider_key"] == "akshare"

    def test_fetch_missing_fixture_raises(self, tmp_path: Path) -> None:
        adapter = AKShareExposureAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.fetch_standardized_payload(
                fixture_path=tmp_path / "missing.json"
            )


class TestAKShareExposureAdapterEnabled:
    def test_enabled_calls_injected_client(self) -> None:
        client = FakeClient(_load_fixture())
        adapter = AKShareExposureAdapter(
            client=client,
            config=AKShareExposureConfig(enabled=True),
        )
        adapter.fetch_standardized_payload()
        assert client.calls == 1

    def test_enabled_without_client_raises(self) -> None:
        adapter = AKShareExposureAdapter(
            config=AKShareExposureConfig(enabled=True)
        )
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()

    def test_enabled_returns_client_payload(self) -> None:
        expected = _load_fixture()
        client = FakeClient(expected)
        adapter = AKShareExposureAdapter(
            client=client,
            config=AKShareExposureConfig(enabled=True),
        )
        payload = adapter.fetch_standardized_payload()
        assert payload["provider_key"] == expected["provider_key"]


class TestAkShareExposureClientProtocol:
    def test_fake_client_satisfies_protocol(self) -> None:
        client = FakeClient(_load_fixture())
        assert isinstance(client, AkShareExposureClientProtocol)

    def test_missing_method_client_is_not_protocol(self) -> None:
        assert not isinstance(MissingMethodClient(), AkShareExposureClientProtocol)


class TestEndToEndAdapterAndMapping:
    def test_disabled_adapter_maps_fixture_to_domain_objects(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(
            fixture_path=FIXTURE_PATH
        )
        result = map_standardized_payload(payload)
        assert set(result.keys()) == {
            "index_profile",
            "index_constituents",
            "etf_index_mapping",
            "etf_holdings",
        }
        assert result["index_profile"].index_code == "000300"
        assert result["etf_index_mapping"].etf_id == UUID(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )

    def test_enabled_adapter_maps_client_payload_to_domain_objects(self) -> None:
        client = FakeClient(_load_fixture())
        adapter = AKShareExposureAdapter(
            client=client,
            config=AKShareExposureConfig(enabled=True),
        )
        payload = adapter.fetch_standardized_payload()
        result = map_standardized_payload(payload)
        assert result["index_profile"].index_code == "000300"
        assert client.calls == 1
