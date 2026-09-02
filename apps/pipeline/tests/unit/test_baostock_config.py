"""BaoStock settings tests (Slice-1 of PR-08)."""

from __future__ import annotations

import pytest
from invest_pipeline.adapters.baostock import BaostockSettings
from pydantic import ValidationError

_MAX_HISTORY_DAYS_ENV = "INVEST_PIPELINE_BAOSTOCK_MAX_HISTORY_DAYS"


class TestBaostockSettings:
    def test_enabled_defaults_to_false(self) -> None:
        assert BaostockSettings().enabled is False

    def test_adjustflag_defaults_to_three(self) -> None:
        assert BaostockSettings().adjustflag == "3"

    @pytest.mark.parametrize("bad", ["1", "", "abc"])
    def test_non_three_adjustflag_is_rejected(self, bad: str) -> None:
        with pytest.raises((ValidationError, ValueError)):
            BaostockSettings(adjustflag=bad)

    def test_three_adjustflag_is_accepted(self) -> None:
        assert BaostockSettings(adjustflag="3").adjustflag == "3"


class TestMaxHistoryDays:
    """``max_history_days`` defaults to 120 and rejects non-positive values."""

    def test_default_is_120(self) -> None:
        assert BaostockSettings().max_history_days == 120

    def test_positive_integer_is_accepted(self) -> None:
        assert BaostockSettings(max_history_days=60).max_history_days == 60
        assert BaostockSettings(max_history_days=1).max_history_days == 1

    @pytest.mark.parametrize("bad", [0, -1, -120])
    def test_non_positive_integer_is_rejected(self, bad: int) -> None:
        with pytest.raises((ValidationError, ValueError)):
            BaostockSettings(max_history_days=bad)

    @pytest.mark.parametrize("bad", [True, False])
    def test_bool_is_rejected(self, bad: bool) -> None:
        # ``True`` / ``False`` are ``int`` subclasses but must still be
        # rejected so a misconfigured ``enabled=True`` boolean cannot
        # silently bind to ``max_history_days``.
        with pytest.raises((ValidationError, ValueError, TypeError)):
            BaostockSettings(max_history_days=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [1.5, 1.0, 60.0])
    def test_float_is_rejected_without_silent_truncation(
        self, bad: float
    ) -> None:
        # ``int`` coercion in lax mode truncates ``1.0`` / ``60.0`` to
        # ``1`` / ``60`` silently; the ``before`` validator must reject
        # the float first so a fractional window cannot accidentally
        # collapse into a smaller window.
        with pytest.raises((ValidationError, ValueError, TypeError)):
            BaostockSettings(max_history_days=bad)  # type: ignore[arg-type]

    def test_fractional_string_is_rejected(self) -> None:
        # A string carrying a fractional component (``"1.5"`` or
        # ``"60.0"``) would also silently truncate under lax ``int``
        # parsing, so it must be rejected at the type boundary.
        with pytest.raises((ValidationError, ValueError, TypeError)):
            BaostockSettings(max_history_days="1.5")  # type: ignore[arg-type]

    def test_direct_constructor_string_integer_is_accepted(self) -> None:
        # The same lax ``int`` coercion that powers environment loading
        # is also reachable from a direct constructor string; the
        # production path is environment, but this guarantees the
        # parser is shared so a regression that breaks env loading
        # surfaces here too.
        assert (
            BaostockSettings(max_history_days="60").max_history_days == 60
        )


class TestMaxHistoryDaysEnvLoading:
    """Environment loading through the ``INVEST_PIPELINE_BAOSTOCK_`` prefix."""

    def test_env_string_60_is_parsed_as_integer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: ``StrictInt`` used to reject the env string
        # ``"60"`` because BaseSettings hands the env value to Pydantic
        # as a string. The fix must parse ``"60"`` to ``60`` so
        # ``INVEST_PIPELINE_BAOSTOCK_MAX_HISTORY_DAYS=60`` works.
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, "60")
        assert BaostockSettings().max_history_days == 60

    def test_env_string_120_is_parsed_as_integer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, "120")
        assert BaostockSettings().max_history_days == 120

    def test_env_string_1_is_parsed_as_integer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, "1")
        assert BaostockSettings().max_history_days == 1

    def test_env_string_zero_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The ``<= 0`` guard still fires after the env value is parsed
        # into an ``int``; ``WINDOW_OUT_OF_RANGE`` semantics require a
        # positive window.
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, "0")
        with pytest.raises((ValidationError, ValueError)):
            BaostockSettings()

    def test_env_string_negative_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, "-1")
        with pytest.raises((ValidationError, ValueError)):
            BaostockSettings()

    @pytest.mark.parametrize("bad", ["1.0", "1.5", "60.0", "1e2"])
    def test_env_fractional_string_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        # Lax ``int`` parsing would silently truncate ``"1.0"`` /
        # ``"60.0"`` / ``"1e2"`` into an integer, collapsing the
        # window. The ``before`` validator must surface that as a
        # rejection at the type boundary, the same way it rejects a
        # direct ``float`` argument.
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, bad)
        with pytest.raises((ValidationError, ValueError, TypeError)):
            BaostockSettings()

    @pytest.mark.parametrize("bad", ["true", "True", "false", "False"])
    def test_env_boolean_string_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        # Booleans reach Pydantic through BaseSettings as strings, and
        # pydantic's lax ``int`` coercion rejects them as unparseable.
        # This locks in the contract that a truthy-looking env value
        # cannot silently bind to ``max_history_days``.
        monkeypatch.setenv(_MAX_HISTORY_DAYS_ENV, bad)
        with pytest.raises((ValidationError, ValueError, TypeError)):
            BaostockSettings()