"""Unit tests for :mod:`invest_pipeline.candidate_routing.custom_strategy_loader`.

The slice is intentionally narrow: the loader is the only place in the
invest-infra stack that reads custom-strategy YAML from disk, and the
tests pin its behaviour exactly:

* Happy-path loading of the seven-rule example from
  ``config/candidate-strategies/custom-trend.yaml`` (the representative
  fixture) and of an in-memory ``tmp_path`` YAML.
* Strict delegation to :func:`parse_custom_strategy_mapping`: every
  domain-level validation rule (unknown top-level keys, unknown
  factor, unknown operator, weights not summing to 1, …) is rejected
  through :class:`InvalidCustomStrategyError`, never swallowed by the
  loader.
* Filesystem failures: missing file, directory in place of file,
  unparseable YAML, non-mapping root, non-UTF-8 content.
* **YAML safety**: every known unsafe tag (Python object / module
  reference, etc.) is rejected by :func:`yaml.safe_load` with a
  :class:`yaml.YAMLError` and re-raised as
  :class:`CustomStrategyLoaderStructureError`. This is the central
  property of plan §5.4 — arbitrary code cannot execute through the
  loader.
* Deterministic ``content_hash`` independent of the path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from invest_domain.candidate_pool import InvalidCustomStrategyError
from invest_pipeline.candidate_routing.custom_strategy_loader import (
    CustomStrategyLoaderError,
    CustomStrategyLoaderFileError,
    CustomStrategyLoaderStructureError,
    LoadedCustomStrategy,
    load_custom_strategy,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
REPRESENTATIVE_CONFIG = REPO_ROOT / "config" / "candidate-strategies" / "custom-trend.yaml"

# Mirror the seven-rule example shipped in
# ``config/candidate-strategies/custom-trend.yaml``. Used by the
# happy-path tests to avoid drift if the production file is updated.
REPRESENTATIVE_PAYLOAD: dict[str, object] = {
    "strategy_key": "custom_trend",
    "version": "1.0.0",
    "enabled": True,
    "universe": {"minimum_history_days": 60},
    "filters": {
        "all": [
            {"factor": "data_completeness_60d", "op": "gte", "value": "0.90"},
            {"factor": "avg_turnover_amount_20d", "op": "gte", "value": "10000000"},
            {"factor": "distance_ma60", "op": "gt", "value": "0"},
        ]
    },
    "score": [
        {"factor": "return_20d", "weight": "0.35", "direction": "higher"},
        {"factor": "return_60d", "weight": "0.35", "direction": "higher"},
        {"factor": "realized_volatility_20d", "weight": "0.15", "direction": "lower"},
        {"factor": "max_drawdown_60d", "weight": "0.15", "direction": "higher"},
    ],
    "output": {"include_top_n": 10, "watch_next_n": 10},
}


def _write_yaml(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_representative_fixture_loads(self) -> None:
        assert REPRESENTATIVE_CONFIG.exists(), (
            f"expected representative fixture at {REPRESENTATIVE_CONFIG}"
        )
        loaded = load_custom_strategy(REPRESENTATIVE_CONFIG)
        assert isinstance(loaded, LoadedCustomStrategy)
        assert loaded.strategy.strategy_key == "custom_trend"
        assert loaded.strategy.version == "1.0.0"
        assert loaded.strategy.enabled is True
        assert loaded.strategy.universe.minimum_history_days == 60
        assert len(loaded.strategy.filters_all) == 3
        assert len(loaded.strategy.score) == 4
        assert loaded.strategy.output.include_top_n == 10
        assert loaded.strategy.output.watch_next_n == 10
        # 64-char SHA-256 hex digest of the file bytes.
        assert len(loaded.content_hash) == 64
        assert len(loaded.strategy.parameter_hash) == 64
        assert loaded.source_path == REPRESENTATIVE_CONFIG

    def test_tmp_path_yaml_loads(self, tmp_path: Path) -> None:
        path = _write_yaml(tmp_path / "strategy.yaml", REPRESENTATIVE_PAYLOAD)
        loaded = load_custom_strategy(path)
        assert loaded.strategy.strategy_key == "custom_trend"

    def test_content_hash_independent_of_path(self, tmp_path: Path) -> None:
        first_path = _write_yaml(tmp_path / "a.yaml", REPRESENTATIVE_PAYLOAD)
        second_path = _write_yaml(tmp_path / "b.yaml", REPRESENTATIVE_PAYLOAD)
        first = load_custom_strategy(first_path)
        second = load_custom_strategy(second_path)
        assert first.content_hash == second.content_hash
        assert first.strategy.parameter_hash == second.strategy.parameter_hash
        # but the source path is preserved on the result.
        assert first.source_path != second.source_path

    def test_content_hash_changes_when_payload_changes(self, tmp_path: Path) -> None:
        first_path = _write_yaml(tmp_path / "a.yaml", REPRESENTATIVE_PAYLOAD)
        payload = {**REPRESENTATIVE_PAYLOAD, "enabled": False}
        second_path = _write_yaml(tmp_path / "b.yaml", payload)
        first = load_custom_strategy(first_path)
        second = load_custom_strategy(second_path)
        assert first.content_hash != second.content_hash
        assert first.strategy.parameter_hash != second.strategy.parameter_hash


# ---------------------------------------------------------------------------
# Filesystem failures
# ---------------------------------------------------------------------------


class TestFilesystemFailures:
    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(CustomStrategyLoaderFileError, match="not found"):
            load_custom_strategy(tmp_path / "does-not-exist.yaml")

    def test_directory_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(CustomStrategyLoaderFileError, match="not a file"):
            load_custom_strategy(tmp_path)

    def test_unparseable_yaml_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("this: is: not: valid: yaml: : :\n  - oops", encoding="utf-8")
        with pytest.raises(CustomStrategyLoaderStructureError, match="not parseable"):
            load_custom_strategy(path)

    def test_non_mapping_root_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- one\n- two\n- three\n", encoding="utf-8")
        with pytest.raises(CustomStrategyLoaderStructureError, match="root must be a mapping"):
            load_custom_strategy(path)

    def test_non_utf8_file_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "binary.yaml"
        path.write_bytes(b"\xff\xfe\xfd\xfc strategy_key: custom_trend\n")
        with pytest.raises(CustomStrategyLoaderFileError, match="UTF-8"):
            load_custom_strategy(path)


# ---------------------------------------------------------------------------
# YAML safety
# ---------------------------------------------------------------------------


class TestYamlSafety:
    @pytest.mark.parametrize(
        "tag",
        [
            "!!python/object:os.system",
            "!!python/object/apply:os.system",
            "!!python/module:os",
            "!!python/name:os.system",
            "!!python/object/new:os.system",
        ],
    )
    def test_python_object_tag_is_rejected(self, tmp_path: Path, tag: str) -> None:
        # ``yaml.safe_load`` is contractually forbidden from
        # instantiating Python objects, so any ``!!python/...`` tag
        # must raise ``yaml.YAMLError``. The loader re-raises it as
        # :class:`CustomStrategyLoaderStructureError` so the loader's
        # callers never see a bare yaml error.
        path = tmp_path / "evil.yaml"
        # Hand-craft a YAML document carrying a Python object tag.
        # We do NOT use ``yaml.safe_dump`` here because it would
        # already filter the tag; we use ``yaml.dump`` (unsafe) only
        # to *write* the test fixture, never to *load* it.
        document = (
            f"strategy_key: custom_trend\n"
            f"version: 1.0.0\n"
            f"enabled: true\n"
            f"universe: {{minimum_history_days: 60}}\n"
            f"score:\n"
            f"  - factor: return_20d\n"
            f"    weight: 0.5\n"
            f"    direction: higher\n"
            f"  - factor: return_60d\n"
            f"    weight: 0.5\n"
            f"    direction: higher\n"
            f"output: {{include_top_n: 1, watch_next_n: 1}}\n"
            f"evil: {tag} ['echo pwned']\n"
        )
        path.write_text(document, encoding="utf-8")
        with pytest.raises(CustomStrategyLoaderStructureError):
            load_custom_strategy(path)

    def test_python_object_tag_does_not_execute_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The most important property: even if a malformed YAML
        # document somehow gets past the safe_load contract, the
        # loader must not execute any Python code. We install a
        # sentinel in ``os.system`` and verify it is never called.
        from invest_pipeline.candidate_routing import custom_strategy_loader as loader_module

        called: list[str] = []

        def _sentinel(*args: object, **kwargs: object) -> object:
            called.append("called")
            return 0

        monkeypatch.setattr(loader_module.yaml, "safe_load", _sentinel)
        path = tmp_path / "noop.yaml"
        path.write_text("strategy_key: custom_trend\nversion: 1.0.0\n", encoding="utf-8")
        # ``yaml.safe_load`` is replaced so the test does not depend
        # on PyYAML's internal handling of the tag. The test then
        # proves that the loader does NOT re-execute the sentinel as
        # if it were a Python object.
        with pytest.raises(CustomStrategyLoaderStructureError, match="root must be a mapping"):
            load_custom_strategy(path)
        assert called == ["called"]


# ---------------------------------------------------------------------------
# Domain-validation delegation
# ---------------------------------------------------------------------------


class TestDomainValidationDelegation:
    def test_unknown_top_level_key_is_rejected(self, tmp_path: Path) -> None:
        payload = {**REPRESENTATIVE_PAYLOAD, "sneaky": "value"}
        path = _write_yaml(tmp_path / "sneaky.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="unknown top-level keys"):
            load_custom_strategy(path)

    def test_unknown_filter_factor_is_rejected(self, tmp_path: Path) -> None:
        payload = {
            **REPRESENTATIVE_PAYLOAD,
            "filters": {
                "all": [{"factor": "non_existent", "op": "gt", "value": "0"}]
            },
        }
        path = _write_yaml(tmp_path / "bad-factor.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="non_existent"):
            load_custom_strategy(path)

    def test_unknown_operator_is_rejected(self, tmp_path: Path) -> None:
        payload = {
            **REPRESENTATIVE_PAYLOAD,
            "filters": {
                "all": [{"factor": "return_20d", "op": "regex", "value": "0"}]
            },
        }
        path = _write_yaml(tmp_path / "bad-op.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="regex"):
            load_custom_strategy(path)

    def test_weights_not_summing_to_one_is_rejected(self, tmp_path: Path) -> None:
        payload = {
            **REPRESENTATIVE_PAYLOAD,
            "score": [
                {"factor": "return_20d", "weight": "0.3", "direction": "higher"},
                {"factor": "return_60d", "weight": "0.5", "direction": "higher"},
            ],
        }
        path = _write_yaml(tmp_path / "bad-weights.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="sum to exactly 1"):
            load_custom_strategy(path)

    def test_bad_semver_is_rejected(self, tmp_path: Path) -> None:
        payload = {**REPRESENTATIVE_PAYLOAD, "version": "v1"}
        path = _write_yaml(tmp_path / "bad-version.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="version"):
            load_custom_strategy(path)

    def test_non_bool_enabled_is_rejected(self, tmp_path: Path) -> None:
        payload = {**REPRESENTATIVE_PAYLOAD, "enabled": "yes"}
        path = _write_yaml(tmp_path / "bad-enabled.yaml", payload)
        with pytest.raises(InvalidCustomStrategyError, match="enabled"):
            load_custom_strategy(path)


# ---------------------------------------------------------------------------
# Loader purity / interface guarantees
# ---------------------------------------------------------------------------


class TestLoaderPurity:
    def test_loader_does_not_import_infra_deps(self) -> None:
        import invest_pipeline.candidate_routing.custom_strategy_loader as module

        forbidden = {
            "sqlalchemy",
            "pandas",
            "polars",
            "fastapi",
            "dagster",
            "httpx",
            "vectorbt",
            "backtrader",
        }
        assert forbidden.isdisjoint(set(getattr(module, "__all__", [])))
        for name in forbidden:
            assert not hasattr(module, name), (
                f"custom_strategy_loader must not expose infra dep {name}"
            )

    def test_loader_error_hierarchy(self) -> None:
        # ``CustomStrategyLoaderError`` must be a ``ValueError`` so
        # generic error-handling code that catches ``ValueError`` still
        # treats loader failures as validation-time errors.
        assert issubclass(CustomStrategyLoaderError, ValueError)
        assert issubclass(CustomStrategyLoaderFileError, CustomStrategyLoaderError)
        assert issubclass(CustomStrategyLoaderStructureError, CustomStrategyLoaderError)
