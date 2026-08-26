"""Tests for :mod:`invest_api.strategy_artifacts` and the
``strategy_artifact_root`` setting on :class:`invest_api.config.Settings`.

The reader must return exact file bytes, reject every unsafe
``artifact_ref`` category, scrub the bounded exception to a fixed
public message, and let operators scope the artifact root through
``STRATEGY_ARTIFACT_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from invest_api import dependencies
from invest_api.config import Settings
from invest_api.dependencies import get_strategy_draft_query_service
from invest_api.strategy_artifacts import (
    READ_ERROR,
    LocalStrategyArtifactReader,
    StrategyArtifactReadError,
)
from invest_storage.repositories import (
    SqlAlchemyStrategyAuditRepository,
    SqlAlchemyStrategyDraftRepository,
)
from pydantic_settings import SettingsConfigDict
from sqlalchemy.orm import Session

PAYLOAD = b"\x00\x01schema binary \xff\xfe end"


def _write(root: Path, rel: str, payload: bytes = PAYLOAD) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _isolated_settings() -> Settings:
    class _Isolated(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    return _Isolated()


class TestSuccessfulRead:
    def test_returns_exact_bytes(self, tmp_path: Path) -> None:
        root = tmp_path / "artifacts"
        _write(root, "sector-strength/strategy.json")
        reader = LocalStrategyArtifactReader(root)

        assert reader.read_bytes("sector-strength/strategy.json") == PAYLOAD


class TestSetting:
    def test_default_is_repository_relative_path(self, monkeypatch) -> None:
        monkeypatch.delenv("STRATEGY_ARTIFACT_ROOT", raising=False)

        settings = _isolated_settings()

        assert settings.strategy_artifact_root == Path("var/strategy-artifacts")

    def test_env_override_sets_root(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("STRATEGY_ARTIFACT_ROOT", str(tmp_path))

        settings = _isolated_settings()

        assert settings.strategy_artifact_root == tmp_path


class TestDependency:
    def test_relative_root_is_resolved_from_repository_not_cwd(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        relative_root = Path("var/test-strategy-artifacts")
        monkeypatch.setattr(
            dependencies,
            "get_settings",
            lambda: Settings(strategy_artifact_root=relative_root),
        )
        monkeypatch.chdir(tmp_path)

        service = get_strategy_draft_query_service(Session())

        repository_root = Path(dependencies.__file__).resolve().parents[4]
        assert service._artifact_reader._root == (  # noqa: SLF001
            repository_root / relative_root
        ).resolve()

    def test_absolute_root_is_preserved(self, monkeypatch, tmp_path: Path) -> None:
        artifact_root = tmp_path / "strategy-artifacts"
        monkeypatch.setattr(
            dependencies,
            "get_settings",
            lambda: Settings(strategy_artifact_root=artifact_root),
        )

        service = get_strategy_draft_query_service(Session())

        assert service._artifact_reader._root == artifact_root.resolve()  # noqa: SLF001

    def test_composes_concrete_repository_and_reader(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            dependencies,
            "get_settings",
            lambda: Settings(strategy_artifact_root=tmp_path),
        )
        session = Session()

        service = get_strategy_draft_query_service(session)

        assert isinstance(  # noqa: SLF001
            service._repository, SqlAlchemyStrategyDraftRepository
        )
        assert service._repository._session is session  # noqa: SLF001
        assert isinstance(  # noqa: SLF001
            service._audit_repository, SqlAlchemyStrategyAuditRepository
        )
        assert service._audit_repository._session is session  # noqa: SLF001
        assert isinstance(service._artifact_reader, LocalStrategyArtifactReader)  # noqa: SLF001


class TestRejection:
    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        r = tmp_path / "artifacts"
        r.mkdir()
        _write(r, "sub/file.bin")
        return r

    @pytest.fixture
    def reader(self, root: Path) -> LocalStrategyArtifactReader:
        return LocalStrategyArtifactReader(root)

    @pytest.mark.parametrize(
        "ref",
        [
            pytest.param("", id="empty"),
            pytest.param("   ", id="whitespace"),
            pytest.param("/abs/path", id="absolute"),
            pytest.param("sub/../../escape", id="traversal"),
            pytest.param("out/../escape", id="relative-traversal"),
        ],
    )
    def test_unsafe_refs_rejected(self, reader, ref: str) -> None:
        with pytest.raises(StrategyArtifactReadError):
            reader.read_bytes(ref)

    def test_symlink_outside_root_rejected(self, reader, root: Path) -> None:
        outside = root.parent / "secret.bin"
        outside.write_bytes(b"secret")
        os.symlink(outside, root / "alias.bin")

        with pytest.raises(StrategyArtifactReadError):
            reader.read_bytes("alias.bin")

    def test_directory_rejected(self, reader, root: Path) -> None:
        (root / "subdir").mkdir()

        with pytest.raises(StrategyArtifactReadError):
            reader.read_bytes("subdir")

    def test_missing_file_rejected(self, reader) -> None:
        with pytest.raises(StrategyArtifactReadError):
            reader.read_bytes("does-not-exist.bin")


class TestExceptionSanitisation:
    def test_str_exc_is_fixed_safe_message(self, tmp_path: Path) -> None:
        root = tmp_path / "artifacts"
        root.mkdir()
        outside = tmp_path / "leak.txt"
        outside.write_text("hunter2 in payload")
        os.symlink(outside, root / "leak-link")
        reader = LocalStrategyArtifactReader(root)

        with pytest.raises(StrategyArtifactReadError) as exc_info:
            reader.read_bytes("leak-link")

        message = str(exc_info.value)
        assert message == READ_ERROR
        for forbidden in ("leak-link", str(outside), "hunter2"):
            assert forbidden not in message


__all__ = [
    "TestExceptionSanitisation",
    "TestDependency",
    "TestRejection",
    "TestSetting",
    "TestSuccessfulRead",
]
