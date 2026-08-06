"""Focused tests for the DC-3B AKShare exposure adapter slice.

Coverage map:

* :class:`TestAKShareExposureAdapterConfig` — the configuration
  dataclass defaults to ``enabled=False`` and rejects bad types.
* :class:`TestAKShareExposureAdapterDisabled` — constructing the
  adapter is side-effect-free and the adapter refuses to call the
  client when disabled; the fixture path is consulted without
  touching the injected client.
* :class:`TestAKShareExposureAdapterEnabled` — when enabled the
  adapter forwards the call to the injected client.
* :class:`TestAKShareExposureAdapterFixturePath` — the bundled
  fixture is loaded verbatim and contains every required key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.exposure import (
    AKShareExposureAdapter,
    AkShareExposureClientProtocol,
    AKShareExposureConfig,
    AKShareExposurePayload,
    fetch_akshare_exposure_payload,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "exposure"
    / "akshare_exposure_payload.json"
)


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0

    def fetch_exposure_payload(self) -> dict[str, Any]:
        self.calls += 1
        return self._payload


class ExplodingClient:
    def fetch_exposure_payload(self) -> dict[str, Any]:
        raise AssertionError("client must not be invoked when disabled")


class MissingMethodClient:
    pass


class TestAKShareExposureAdapterConfig:
    def test_default_enabled_is_false(self) -> None:
        config = AKShareExposureConfig()
        assert config.enabled is False

    def test_default_provider_key(self) -> None:
        config = AKShareExposureConfig()
        assert config.provider_key == "akshare"

    def test_default_dataset_key(self) -> None:
        config = AKShareExposureConfig()
        assert config.dataset_key == "exposure_bundle"

    def test_rejects_non_bool_enabled(self) -> None:
        with pytest.raises(TypeError):
            AKShareExposureConfig(enabled=1)  # type: ignore[arg-type]

    def test_rejects_empty_provider_key(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(provider_key="")

    def test_rejects_empty_dataset_key(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(dataset_key="")

    def test_rejects_whitespace_provider_key(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(provider_key="   ")

    def test_rejects_whitespace_dataset_key(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(dataset_key="   ")

    def test_rejects_non_string_provider_key(self) -> None:
        with pytest.raises(TypeError):
            AKShareExposureConfig(provider_key=123)  # type: ignore[arg-type]

    def test_rejects_non_string_dataset_key(self) -> None:
        with pytest.raises(TypeError):
            AKShareExposureConfig(dataset_key=123)  # type: ignore[arg-type]

    def test_rejects_empty_fixture_path(self) -> None:
        with pytest.raises(ValueError):
            AKShareExposureConfig(fixture_path="")

    def test_rejects_naive_observed_at(self) -> None:
        from datetime import datetime
        with pytest.raises(ValueError):
            AKShareExposureConfig(
                observed_at=datetime(2026, 7, 31, 12, 0, 0)
            )


class TestAKShareExposureAdapterDisabled:
    def test_default_construction_is_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        assert adapter.enabled is False
        assert adapter.is_disabled is True
        assert adapter.client is None

    def test_constructor_is_pure_no_network(self) -> None:
        client = FakeClient({"stub": True})
        adapter = AKShareExposureAdapter(client=client)
        assert adapter.client is client
        assert client.calls == 0

    def test_fetch_raises_when_disabled_and_no_fixture(self) -> None:
        adapter = AKShareExposureAdapter()
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()

    def test_fetch_raises_when_disabled_with_client_only(self) -> None:
        client = FakeClient({"stub": True})
        adapter = AKShareExposureAdapter(client=client)
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()
        assert client.calls == 0

    def test_disabled_with_exploding_client_never_invokes(self) -> None:
        adapter = AKShareExposureAdapter(client=ExplodingClient())
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()

    def test_fetch_loads_fixture_when_disabled(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(fixture_path=FIXTURE_PATH)
        assert isinstance(payload, dict)
        assert "index_profile" in payload
        assert "index_constituents" in payload
        assert "etf_index_mapping" in payload
        assert "etf_holdings" in payload

    def test_convenience_wrapper_forwards_to_adapter(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = fetch_akshare_exposure_payload(adapter, fixture_path=FIXTURE_PATH)
        assert payload["provider_key"] == "akshare"

    def test_missing_fixture_path_raises(self) -> None:
        adapter = AKShareExposureAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.fetch_standardized_payload(fixture_path="__missing__.json")


class TestAKShareExposureAdapterEnabled:
    def test_enabled_adapter_calls_client(self) -> None:
        client = FakeClient({"ok": True})
        adapter = AKShareExposureAdapter(
            client=client, config=AKShareExposureConfig(enabled=True)
        )
        assert adapter.enabled is True
        result = adapter.fetch_standardized_payload()
        assert result is client._payload
        assert client.calls == 1

    def test_enabled_adapter_without_client_raises(self) -> None:
        adapter = AKShareExposureAdapter(
            config=AKShareExposureConfig(enabled=True)
        )
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_standardized_payload()

    def test_enabled_with_fixture_path_still_uses_client(self) -> None:
        client = FakeClient({"ok": True})
        adapter = AKShareExposureAdapter(
            client=client, config=AKShareExposureConfig(enabled=True)
        )
        # Fixture path is ignored when enabled — the client is consulted.
        result = adapter.fetch_standardized_payload(fixture_path=FIXTURE_PATH)
        assert result is client._payload
        assert client.calls == 1


class TestAKShareExposureAdapterFixturePath:
    def test_relative_fixture_path_resolves(self) -> None:
        adapter = AKShareExposureAdapter()
        payload = adapter.fetch_standardized_payload(
            fixture_path="akshare_exposure_payload.json"
        )
        assert "index_profile" in payload

    def test_fixture_must_be_json_object(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        adapter = AKShareExposureAdapter()
        with pytest.raises(ValueError, match="JSON object"):
            adapter.fetch_standardized_payload(fixture_path=bad)


class TestAkShareExposureClientProtocol:
    def test_fake_client_satisfies_protocol(self) -> None:
        client = FakeClient({"x": 1})
        assert isinstance(client, AkShareExposureClientProtocol)

    def test_missing_method_client_is_not_protocol(self) -> None:
        assert not isinstance(MissingMethodClient(), AkShareExposureClientProtocol)


class TestAKShareExposurePayloadAlias:
    def test_payload_is_mapping(self) -> None:
        payload: AKShareExposurePayload = {"k": "v"}
        assert isinstance(payload, dict)
