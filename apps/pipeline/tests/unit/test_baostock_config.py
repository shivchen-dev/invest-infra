"""BaoStock settings tests (Slice-1 of PR-08)."""

from __future__ import annotations

import pytest
from invest_pipeline.adapters.baostock import BaostockSettings
from pydantic import ValidationError


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
