"""Atomic filesystem worker for one WorkBuddy stage."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

STAGES = ("strategy", "candidate", "research", "observation")
_READY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ready$")
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOCK_NAME = ".workbuddy.lock"
_RENAME_NOREPLACE = 1
_LIBC = ctypes.CDLL(None, use_errno=True)
_RENAMEAT2 = getattr(_LIBC, "renameat2", None)
if _RENAMEAT2 is not None:
    _RENAMEAT2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    _RENAMEAT2.restype = ctypes.c_int


@dataclass(frozen=True, slots=True)
class StagePackageOutcome:
    task_id: str
    status: str
    error: str | None = None


class StagePackageWorker:
    def __init__(self, bridge_root: str | Path, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unsupported stage: {stage}")
        self.stage = stage
        self.bridge_root = Path(bridge_root).resolve()
        self.root = self.bridge_root / "workbuddy" / stage
        self.inbox = self.root / "inbox"
        self.processing = self.root / "processing"
        self.results = self.root / "results"
        self.archive = self.root / "archive"
        self.failed = self.root / "failed"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise ValueError(f"stage root is not a directory: {self.root}")
        for directory in (self.inbox, self.processing, self.results, self.archive, self.failed):
            if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
                raise ValueError(f"stage directory is not a directory: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    def _task_id(self, name: str, ready: bool = True) -> str | None:
        if ready:
            match = _READY_RE.fullmatch(name)
            return name[:-6] if match else None
        return name if _TASK_RE.fullmatch(name) else None

    def discover_ready(self) -> tuple[Path, ...]:
        entries = []
        for entry in os.scandir(self.results):
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if self._task_id(entry.name) is not None:
                entries.append(Path(entry.path))
        return tuple(sorted(entries, key=lambda path: path.name))

    def discover_processing(self) -> tuple[Path, ...]:
        """Return safe processing residues for explicit operator recovery."""
        entries = []
        for entry in os.scandir(self.processing):
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if self._task_id(entry.name, ready=False) is not None:
                entries.append(Path(entry.path))
        return tuple(sorted(entries, key=lambda path: path.name))

    def _validated_child(self, path: str | Path, parent: Path, ready: bool) -> tuple[Path, str]:
        candidate = Path(path)
        if candidate.is_symlink() or candidate.parent != parent:
            raise ValueError("package path must be a direct, non-symlink child")
        if not os.path.lexists(candidate):
            raise FileNotFoundError(candidate)
        task_id = self._task_id(candidate.name, ready=ready)
        if task_id is None or not candidate.is_dir():
            raise ValueError("unsafe package path")
        return candidate, task_id

    @staticmethod
    def _move_noreplace(source: Path, destination: Path) -> None:
        """Atomically move one direct child without ever replacing a target."""
        if _RENAMEAT2 is None:
            raise OSError(errno.ENOSYS, "renameat2(RENAME_NOREPLACE) is unavailable")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        source_parent_fd = os.open(source.parent, flags)
        try:
            destination_parent_fd = os.open(destination.parent, flags)
            try:
                result = _RENAMEAT2(
                    source_parent_fd,
                    os.fsencode(source.name),
                    destination_parent_fd,
                    os.fsencode(destination.name),
                    _RENAME_NOREPLACE,
                )
                if result != 0:
                    error_number = ctypes.get_errno()
                    if error_number == errno.EEXIST:
                        raise FileExistsError(error_number, os.strerror(error_number), destination)
                    raise OSError(error_number, os.strerror(error_number), source)
            finally:
                os.close(destination_parent_fd)
        finally:
            os.close(source_parent_fd)

    @staticmethod
    def _acquire_package_lock(package: Path) -> int:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_fd = os.open(package, directory_flags)
        try:
            try:
                lock_fd = os.open(
                    _LOCK_NAME,
                    os.O_RDWR
                    | os.O_NONBLOCK
                    | os.O_CREAT
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENXIO, errno.ENODEV, errno.EISDIR):
                    raise ValueError("unsafe package lock") from exc
                raise
        finally:
            os.close(directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise ValueError("package lock is not a regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_fd
        except BaseException:
            os.close(lock_fd)
            raise

    def claim(self, path: str | Path) -> Path:
        source, task_id = self._validated_child(path, self.results, ready=True)
        destination = self.processing / task_id
        self._move_noreplace(source, destination)
        return destination

    def finish(self, package: str | Path, success: bool) -> Path:
        source, task_id = self._validated_child(package, self.processing, ready=False)
        destination = (self.archive if success else self.failed) / task_id
        self._move_noreplace(source, destination)
        return destination

    def process_once(
        self, handler: Callable[[str, Path], object]
    ) -> tuple[StagePackageOutcome, ...]:
        outcomes: list[StagePackageOutcome] = []
        for ready_path in self.discover_ready():
            task_id = ready_path.name[:-6]
            lock_fd: int | None = None
            try:
                lock_fd = self._acquire_package_lock(ready_path)
                claimed = self.claim(ready_path)
            except (FileExistsError, FileNotFoundError, BlockingIOError) as exc:
                outcomes.append(StagePackageOutcome(task_id, "claim_conflict", str(exc)))
                if lock_fd is not None:
                    os.close(lock_fd)
                continue
            except ValueError as exc:
                outcomes.append(StagePackageOutcome(task_id, "unsafe_package", str(exc)))
                if lock_fd is not None:
                    os.close(lock_fd)
                continue
            try:
                try:
                    handler(self.stage, claimed)
                except Exception as exc:  # handler failures belong in failed/
                    error = str(exc) or exc.__class__.__name__
                    try:
                        self.finish(claimed, success=False)
                    except (FileExistsError, FileNotFoundError) as finish_exc:
                        error = f"{error}; finish failed: {finish_exc}"
                    outcomes.append(StagePackageOutcome(task_id, "failed", error))
                else:
                    try:
                        self.finish(claimed, success=True)
                    except (FileExistsError, FileNotFoundError) as exc:
                        outcomes.append(StagePackageOutcome(task_id, "finish_conflict", str(exc)))
                        continue
                    outcomes.append(StagePackageOutcome(task_id, "success", None))
            finally:
                os.close(lock_fd)
        return tuple(outcomes)

    def recover_once(
        self, handler: Callable[[str, Path], object]
    ) -> tuple[StagePackageOutcome, ...]:
        """Explicitly resume packages left in ``processing/`` after a crash.

        Recovery is deliberately separate from :meth:`process_once` so a
        normally running worker never steals a package that another worker may
        still be handling. Only valid, direct, non-symlink directories are
        considered; each is completed through the same handler and conflict-
        preserving finish path as a newly claimed package.
        """
        outcomes: list[StagePackageOutcome] = []
        for package in self.discover_processing():
            task_id = package.name
            lock_fd: int | None = None
            try:
                claimed, validated_task_id = self._validated_child(
                    package, self.processing, ready=False
                )
            except FileNotFoundError as exc:
                outcomes.append(
                    StagePackageOutcome(task_id, "recovery_conflict", str(exc))
                )
                continue
            except ValueError as exc:
                outcomes.append(StagePackageOutcome(task_id, "unsafe_residue", str(exc)))
                continue

            try:
                lock_fd = self._acquire_package_lock(claimed)
            except (FileNotFoundError, BlockingIOError) as exc:
                outcomes.append(StagePackageOutcome(task_id, "active", str(exc)))
                continue
            except ValueError as exc:
                outcomes.append(StagePackageOutcome(task_id, "unsafe_residue", str(exc)))
                continue

            try:
                try:
                    handler(self.stage, claimed)
                except Exception as exc:  # handler failures belong in failed/
                    error = str(exc) or exc.__class__.__name__
                    try:
                        self.finish(claimed, success=False)
                    except (FileExistsError, FileNotFoundError) as finish_exc:
                        error = f"{error}; finish failed: {finish_exc}"
                    outcomes.append(
                        StagePackageOutcome(validated_task_id, "failed", error)
                    )
                else:
                    try:
                        self.finish(claimed, success=True)
                    except (FileExistsError, FileNotFoundError) as exc:
                        outcomes.append(
                            StagePackageOutcome(
                                validated_task_id, "finish_conflict", str(exc)
                            )
                        )
                        continue
                    outcomes.append(
                        StagePackageOutcome(validated_task_id, "success", None)
                    )
            finally:
                os.close(lock_fd)
        return tuple(outcomes)
