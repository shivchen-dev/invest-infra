from __future__ import annotations

from pathlib import Path

import pytest
from invest_pipeline.credentials import CredentialStore


def test_explicit_value_takes_precedence_over_central_file(tmp_path: Path) -> None:
    (tmp_path / "tushare.token").write_text("file-secret\n", encoding="utf-8")
    assert CredentialStore(tmp_path).resolve("tushare", "env-secret") == "env-secret"


def test_provider_value_is_trimmed_from_central_file(tmp_path: Path) -> None:
    (tmp_path / "cifangquant.api_key").write_text("file-secret\n", encoding="utf-8")
    assert CredentialStore(tmp_path).resolve("cifangquant") == "file-secret"


def test_missing_central_file_is_empty(tmp_path: Path) -> None:
    assert CredentialStore(tmp_path).resolve("rsscast") == ""


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported credential provider"):
        CredentialStore(tmp_path).resolve("unknown")
