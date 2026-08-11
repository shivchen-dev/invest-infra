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


# Synthetic, obviously fictional sentinel used to populate the
# ``hithink.api_key`` fixture for the reserved-provider slice. The
# value carries ``ci-test-`` / ``-not-a-real-secret`` markers so it
# cannot accidentally match a real upstream HiThink credential in a
# future regression; the tests also assert the literal never appears
# in any error message that could leak to a log line.
_HITHINK_TEST_API_KEY = "ci-test-hithink-key-not-a-real-secret"


def test_hithink_resolves_trimmed_value_from_central_file(tmp_path: Path) -> None:
    # Reserved-provider slice: ``hithink`` is registered in the
    # centralized ``_CREDENTIAL_FILES`` mapping under the
    # ``hithink.api_key`` filename. The lookup contract mirrors the
    # runtime-backed providers: trim the file contents and return the
    # value when ``explicit_value`` is empty.
    (tmp_path / "hithink.api_key").write_text(
        f"{_HITHINK_TEST_API_KEY}\n", encoding="utf-8"
    )
    assert CredentialStore(tmp_path).resolve("hithink") == _HITHINK_TEST_API_KEY


def test_hithink_explicit_value_overrides_central_file(tmp_path: Path) -> None:
    # The explicit override path must win over the centralized file for
    # ``hithink`` exactly the way it does for every other provider;
    # the reserved provider must not silently bypass the override.
    (tmp_path / "hithink.api_key").write_text(
        f"{_HITHINK_TEST_API_KEY}\n", encoding="utf-8"
    )
    explicit = "ci-env-override-hithink-not-a-real-secret"
    assert CredentialStore(tmp_path).resolve("hithink", explicit) == explicit


def test_hithink_missing_central_file_is_empty(tmp_path: Path) -> None:
    # No centralized file -> empty string, same as ``rsscast``. The
    # reserved provider has no real adapter wired in this slice, so a
    # missing file must not raise; future adapters can opt in by
    # populating the file or supplying an explicit override.
    assert CredentialStore(tmp_path).resolve("hithink") == ""


def test_hithink_path_uses_reserved_filename(tmp_path: Path) -> None:
    # ``path_for`` is the public seam the helper exposes for
    # operators / docs; the HiThink mapping must pin the reserved
    # ``hithink.api_key`` filename under the secrets root so a future
    # adapter can locate the centralized credential without hard-coding
    # the filename in two places.
    assert (
        CredentialStore(tmp_path).path_for("hithink")
        == tmp_path / "hithink.api_key"
    )


def test_hithink_resolved_value_is_redacted_in_lookup_errors(tmp_path: Path) -> None:
    # Redaction guardrail: ``CredentialStore.resolve`` returns the
    # secret value to the caller but must never echo it back in an
    # error path. Populate the file with a synthetic sentinel and
    # trigger a failure by requesting an *unsupported* provider key so
    # the helper raises ``ValueError``; the secret value must not
    # appear anywhere in the raised exception's string.
    (tmp_path / "hithink.api_key").write_text(
        f"{_HITHINK_TEST_API_KEY}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError) as exc_info:
        CredentialStore(tmp_path).resolve("hithink-not-a-registered-provider")
    message = str(exc_info.value)
    assert "unsupported credential provider" in message
    assert _HITHINK_TEST_API_KEY not in message
    assert "hithink-not-a-registered-provider" in message
