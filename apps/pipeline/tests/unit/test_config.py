"""Unit tests for the pipeline ``Settings`` module.

Pins the contract for the fail-closed StrategyVersion approver
allowlist setting:

- ``strategy_approver_agent_ids`` is a tuple of non-empty,
  outer-whitespace-trimmed agent IDs.
- The default is the empty tuple so authorization fails closed.
- Blank entries raise ``ValidationError`` instead of being dropped.
- The :envvar:`INVEST_PIPELINE_STRATEGY_APPROVER_AGENT_IDS` alias is
  honored via the standard JSON-encoded list convention.

Environment variables and the ``get_settings`` cache are isolated so
no test order can leak.
"""

from __future__ import annotations

import json

import pytest
from invest_pipeline.config import Settings, get_settings
from pydantic import ValidationError

_ENV_ALIAS = "INVEST_PIPELINE_STRATEGY_APPROVER_AGENT_IDS"


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.delenv(_ENV_ALIAS, raising=False)
    yield monkeypatch
    get_settings.cache_clear()


def test_default_is_empty_tuple(isolated_env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.strategy_approver_agent_ids == ()
    assert isinstance(settings.strategy_approver_agent_ids, tuple)


def test_accepts_single_id(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv(_ENV_ALIAS, json.dumps(["agent-1"]))

    settings = Settings()

    assert settings.strategy_approver_agent_ids == ("agent-1",)


def test_accepts_multiple_ids(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv(_ENV_ALIAS, json.dumps(["agent-a", "agent-b", "agent-c"]))

    settings = Settings()

    assert settings.strategy_approver_agent_ids == ("agent-a", "agent-b", "agent-c")


def test_strips_outer_whitespace(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv(_ENV_ALIAS, json.dumps(["  agent-1  ", "\tagent-2\n"]))

    settings = Settings()

    assert settings.strategy_approver_agent_ids == ("agent-1", "agent-2")


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_rejects_blank_entry(blank: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(strategy_approver_agent_ids=(blank,))

    assert "strategy_approver_agent_ids" in str(exc_info.value)


def test_env_alias_is_honored(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv(_ENV_ALIAS, json.dumps(["alpha", "beta"]))

    settings = Settings()

    assert settings.strategy_approver_agent_ids == ("alpha", "beta")


def test_get_settings_reads_env_alias(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv(_ENV_ALIAS, json.dumps(["ops-approver"]))

    settings = get_settings()

    assert settings.strategy_approver_agent_ids == ("ops-approver",)
