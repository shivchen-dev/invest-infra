"""Focused tests for the DC-3B exposure mapping helpers.

The tests exercise the pure mapping layer end-to-end against the
bundled JSON fixture. They confirm that:

* the standardized payload is parsed into the four exposure domain
  objects with the right fields and provenance;
* the factory-generated content_hash is deterministic for identical
  fixtures;
* the mapping layer surfaces dictionary-level failures (missing
  keys, malformed weights, duplicate stock codes) without reaching
  for the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from invest_pipeline.adapters.exposure import (
    AKShareExposureMappingError,
    AKShareExposureStandardizedPayload,
    map_etf_holding_snapshot,
    map_etf_index_mapping,
    map_index_constituent_snapshot,
    map_index_profile,
    map_standardized_payload,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "exposure"
FIXTURE_PATH = FIXTURE_DIR / "akshare_exposure_payload.json"

ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
INDEX_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ALT_ETF_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ALT_INDEX_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
AS_OF_DATE = date(2026, 7, 31)


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixed_id_factory() -> UUID:
    return UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def _fixed_now_factory() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def payload() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture
def fixed_id():
    return _fixed_id_factory()


@pytest.fixture
def fixed_now():
    return _fixed_now_factory()


class TestFixtureLoadingAndShape:
    def test_fixture_path_exists(self) -> None:
        assert FIXTURE_PATH.exists()

    def test_fixture_top_level_keys_present(self, payload: dict[str, Any]) -> None:
        for key in (
            "provider_key",
            "dataset_key",
            "observed_at",
            "index_profile",
            "index_constituents",
            "etf_index_mapping",
            "etf_holdings",
        ):
            assert key in payload

    def test_fixture_observed_at_is_iso8601(self, payload: dict[str, Any]) -> None:
        observed_at = payload["observed_at"]
        assert isinstance(observed_at, str)
        parsed = datetime.fromisoformat(observed_at)
        assert parsed.tzinfo is not None


class TestMapIndexProfile:
    def test_returns_index_profile(self, payload: dict[str, Any]) -> None:
        profile = map_index_profile(payload)
        assert profile.index_code == "000300"
        assert profile.index_name == "CSI 300"
        assert profile.category == "Broad Market"
        assert profile.as_of_date == AS_OF_DATE

    def test_provenance_propagates_from_payload(self, payload: dict[str, Any]) -> None:
        profile = map_index_profile(payload)
        assert profile.provenance.provider_key == "akshare"
        assert profile.provenance.dataset_key == "exposure_bundle"
        assert profile.provenance.observed_at == OBSERVED_AT
        assert profile.provenance.revision == 1
        assert profile.provenance.confidence == Decimal("0.95")

    def test_content_hash_is_64_hex_chars(self, payload: dict[str, Any]) -> None:
        profile = map_index_profile(payload)
        assert len(profile.content_hash) == 64
        int(profile.content_hash, 16)


class TestMapIndexConstituentSnapshot:
    def test_returns_snapshot_with_sorted_constituents(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        codes = [c.stock_code for c in snapshot.constituents]
        assert codes == ["600519", "601318", "000858", "300750"]

    def test_snapshot_uses_injected_factories(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _fixed_id_factory()
        assert snapshot.created_at == _fixed_now_factory()

    def test_snapshot_carries_provenance(self, payload: dict[str, Any]) -> None:
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.provenance.provider_key == "akshare"
        assert snapshot.observed_at == OBSERVED_AT
        assert snapshot.as_of_date == AS_OF_DATE

    def test_snapshot_content_hash_is_deterministic(
        self, payload: dict[str, Any]
    ) -> None:
        first = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        second = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert first.content_hash == second.content_hash


class TestMapEtfIndexMapping:
    def test_returns_mapping(self, payload: dict[str, Any]) -> None:
        mapping = map_etf_index_mapping(payload)
        assert mapping.etf_id == ETF_ID
        assert mapping.index_id == INDEX_ID
        assert mapping.effective_from == date(2024, 1, 1)
        assert mapping.effective_to == date(2026, 12, 31)

    def test_mapping_observed_at_matches_provenance(
        self, payload: dict[str, Any]
    ) -> None:
        mapping = map_etf_index_mapping(payload)
        assert mapping.observed_at == OBSERVED_AT
        assert mapping.provenance.observed_at == OBSERVED_AT

    def test_mapping_content_hash_is_64_hex(self, payload: dict[str, Any]) -> None:
        mapping = map_etf_index_mapping(payload)
        assert len(mapping.content_hash) == 64
        int(mapping.content_hash, 16)


class TestMapEtfHoldingSnapshot:
    def test_returns_snapshot_with_sorted_holdings(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        codes = [h.stock_code for h in snapshot.holdings]
        assert codes == ["600519", "601318", "000858"]

    def test_holdings_carry_industry(self, payload: dict[str, Any]) -> None:
        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        by_code = {h.stock_code: h for h in snapshot.holdings}
        assert by_code["600519"].industry == "白酒"
        assert by_code["601318"].industry == "金融"

    def test_snapshot_uses_injected_factories(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.id == _fixed_id_factory()
        assert snapshot.created_at == _fixed_now_factory()
        assert snapshot.etf_id == ETF_ID


class TestMapStandardizedPayload:
    def test_returns_all_four_objects(self, payload: dict[str, Any]) -> None:
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

    def test_all_objects_share_provenance_summary(
        self, payload: dict[str, Any]
    ) -> None:
        result = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        keys = {obj.provenance.provider_key for obj in result.values()}
        assert keys == {"akshare"}
        datasets = {obj.provenance.dataset_key for obj in result.values()}
        assert datasets == {"exposure_bundle"}

    @pytest.mark.parametrize(
        "missing_section",
        ["index_profile", "index_constituents", "etf_index_mapping", "etf_holdings"],
    )
    def test_missing_bundle_section_raises_contract_error(
        self, payload: dict[str, Any], missing_section: str
    ) -> None:
        payload.pop(missing_section)
        with pytest.raises(AKShareExposureMappingError) as excinfo:
            map_standardized_payload(payload)
        assert excinfo.value.code == "missing_required_top_keys"

    def test_all_four_objects_share_one_provenance_instance(
        self, payload: dict[str, Any]
    ) -> None:
        result = map_standardized_payload(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        shared = result["index_profile"].provenance
        assert result["index_constituents"].provenance is shared
        assert result["etf_index_mapping"].provenance is shared
        assert result["etf_holdings"].provenance is shared


class TestIndependentProvenancePerMap:
    def test_map_index_profile_builds_own_provenance(
        self, payload: dict[str, Any]
    ) -> None:
        profile = map_index_profile(payload)
        assert profile.provenance.provider_key == payload["provider_key"]
        assert profile.provenance.dataset_key == payload["dataset_key"]
        assert profile.provenance.observed_at == OBSERVED_AT

    def test_map_index_constituent_snapshot_builds_own_provenance(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.provenance.provider_key == payload["provider_key"]
        assert snapshot.provenance.dataset_key == payload["dataset_key"]
        assert snapshot.observed_at == OBSERVED_AT

    def test_map_etf_index_mapping_builds_own_provenance(
        self, payload: dict[str, Any]
    ) -> None:
        mapping = map_etf_index_mapping(payload)
        assert mapping.provenance.provider_key == payload["provider_key"]
        assert mapping.provenance.dataset_key == payload["dataset_key"]
        assert mapping.observed_at == OBSERVED_AT

    def test_map_etf_holding_snapshot_builds_own_provenance(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = map_etf_holding_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        assert snapshot.provenance.provider_key == payload["provider_key"]
        assert snapshot.provenance.dataset_key == payload["dataset_key"]
        assert snapshot.observed_at == OBSERVED_AT

    def test_independent_calls_produce_distinct_provenance_instances(
        self, payload: dict[str, Any]
    ) -> None:
        profile = map_index_profile(payload)
        snapshot = map_index_constituent_snapshot(
            payload,
            id_factory=_fixed_id_factory,
            now_factory=_fixed_now_factory,
        )
        # Each map_* call that omits ``provenance`` builds its own
        # ExposureProvenance from the payload envelope; the two
        # instances are equal but distinct.
        assert profile.provenance == snapshot.provenance
        assert profile.provenance is not snapshot.provenance


class TestMappingErrorSurface:
    def test_missing_provenance_key_raises(self) -> None:
        with pytest.raises(AKShareExposureMappingError):
            map_index_profile(
                {
                    "dataset_key": "x",
                    "observed_at": OBSERVED_AT.isoformat(),
                    "index_profile": {"index_code": "X", "index_name": "X"},
                }
            )

    def test_naive_observed_at_is_rejected(self) -> None:
        with pytest.raises(AKShareExposureMappingError):
            map_index_profile(
                {
                    "provider_key": "akshare",
                    "dataset_key": "exposure_bundle",
                    "observed_at": "2026-07-31T12:00:00",
                    "index_profile": {"index_code": "X", "index_name": "X"},
                }
            )

    def test_invalid_weight_is_rejected(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["index_constituents"] = {
            "index_code": "000300",
            "as_of_date": AS_OF_DATE.isoformat(),
            "constituents": [
                {"stock_code": "600519", "weight": "1.5"},
            ],
        }
        with pytest.raises(AKShareExposureMappingError):
            map_index_constituent_snapshot(payload)

    def test_duplicate_stock_codes_surfaced_by_snapshot(
        self, payload: dict[str, Any]
    ) -> None:
        payload = dict(payload)
        payload["index_constituents"] = {
            "index_code": "000300",
            "as_of_date": AS_OF_DATE.isoformat(),
            "constituents": [
                {"stock_code": "600519", "weight": "0.10"},
                {"stock_code": "600519", "weight": "0.05"},
            ],
        }
        with pytest.raises(ValueError):
            map_index_constituent_snapshot(payload)

    def test_invalid_uuid_is_rejected(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload["etf_index_mapping"] = {
            "etf_id": "not-a-uuid",
            "index_id": str(INDEX_ID),
            "effective_from": "2024-01-01",
            "effective_to": None,
        }
        with pytest.raises((AKShareExposureMappingError, ValueError)):
            map_etf_index_mapping(payload)

    def test_missing_index_profile_block_raises(self, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        payload.pop("index_profile")
        with pytest.raises(AKShareExposureMappingError):
            map_index_profile(payload)


class TestPayloadTypeAlias:
    def test_payload_alias_is_a_mapping(self) -> None:
        # The alias is a runtime type alias for ``dict``; the
        # identity form must hold.
        assert AKShareExposureStandardizedPayload is dict
        assert isinstance({}, AKShareExposureStandardizedPayload)


class TestMappingDeterminism:
    def test_two_calls_yield_identical_hashes(self, payload: dict[str, Any]) -> None:
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
        for key in first:
            assert first[key].content_hash == second[key].content_hash
