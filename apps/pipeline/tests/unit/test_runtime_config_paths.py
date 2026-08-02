from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest
from invest_pipeline import assets
from invest_pipeline.config import Settings, get_settings


class _LoaderStop(Exception):
    pass


def test_settings_default_paths_point_to_repository_config() -> None:
    repository_root = Path(__file__).resolve().parents[4]

    settings = Settings()

    assert settings.personal_universe_path == (
        repository_root / "config" / "personal-universe.yaml"
    )
    assert settings.candidate_pool_policy_path == (
        repository_root / "config" / "candidate-pool-personal.yaml"
    )


def test_get_settings_reads_environment_path_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    personal_path = tmp_path / "universe.yaml"
    policy_path = tmp_path / "policy.yaml"
    monkeypatch.setenv("INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH", str(personal_path))
    monkeypatch.setenv(
        "INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH", str(policy_path)
    )
    get_settings.cache_clear()

    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.personal_universe_path == personal_path
    assert settings.candidate_pool_policy_path == policy_path


@pytest.mark.parametrize(
    ("asset_name", "loader_name"),
    [
        ("etf_daily_bars_raw", "load_personal_universe"),
        ("etf_daily_bars", "load_personal_universe"),
        ("etf_input_snapshot", "load_personal_universe"),
        ("personal_candidate_pool", "load_candidate_pool_policy"),
    ],
)
def test_personal_assets_pass_configured_paths_to_loaders_without_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    asset_name: str,
    loader_name: str,
) -> None:
    personal_path = tmp_path / "configured-universe.yaml"
    policy_path = tmp_path / "configured-policy.yaml"
    settings = Settings(
        personal_universe_path=personal_path,
        candidate_pool_policy_path=policy_path,
    )
    captured: dict[str, Path] = {}

    def _capture_path(path: Path) -> None:
        captured["path"] = path
        raise _LoaderStop

    monkeypatch.setattr(assets, "get_settings", lambda: settings)
    monkeypatch.setattr(assets, loader_name, _capture_path)
    if asset_name in {"etf_daily_bars_raw", "etf_daily_bars"}:
        monkeypatch.setattr(
            assets,
            "build_provider",
            lambda _settings: SimpleNamespace(provider_key="fixture_dev"),
        )

    asset_fn = getattr(assets, asset_name).op.compute_fn.decorated_fn
    with pytest.raises(_LoaderStop):
        asset_fn(dg.build_asset_context(partition_key="2026-07-31"))

    expected_path = personal_path if loader_name == "load_personal_universe" else policy_path
    assert captured["path"] == expected_path
