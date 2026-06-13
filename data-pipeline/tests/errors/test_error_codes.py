"""
test_error_codes.py — errors.error_codes 单元测试 (N-10)

覆盖 ErrorCode 常量 + 4 异常类 + handle_error 4 层 + classify_error
审计员: Arc
"""
import logging
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from errors.error_codes import (  # noqa: E402
    ErrorCode, ErrorLevel, GridError, GridFatalError, GridWarning, GridReport,
    handle_error, classify_error,
)


# ─── 常量 ────────────────────────────────────────────────────────
def test_error_code_constants():
    """ErrorCode 关键常量值."""
    assert ErrorCode.GRID_E001 == "GRID-E001"
    assert ErrorCode.PG_E010 == "PG-E010"
    assert ErrorCode.QQ_R201 == "QQ-R201"


def test_error_level_constants():
    """ErrorLevel 4 层."""
    for level in ["FATAL", "ERROR", "WARN", "INFO"]:
        assert getattr(ErrorLevel, level) == level


# ─── 4 异常类 + 继承 ──────────────────────────────────────────────
def test_4_exception_classes_and_inheritance():
    """4 异常 + 字段 + 继承关系."""
    e = GridError("X-E001", "test msg")
    assert e.code == "X-E001" and e.level == "ERROR"
    assert "X-E001" in str(e)

    assert GridFatalError("X-F001", "fatal").level == "FATAL"
    assert GridWarning("X-W101", "warn").level == "WARN"
    assert GridReport("X-R201", "info").level == "INFO"

    for cls in [GridFatalError, GridWarning, GridReport]:
        assert issubclass(cls, GridError)


# ─── handle_error 4 层 ──────────────────────────────────────────
def test_handle_error_4_levels(caplog):
    """handle_error 4 层 + reraise 行为."""
    log = logging.getLogger("test_handle")
    log.setLevel(logging.DEBUG)

    # INFO: 不抛
    caplog.clear()
    handle_error(GridReport(ErrorCode.QQ_R201, "info msg"), logger=log, reraise=False)
    assert any("QQ-R201" in r.message for r in caplog.records)

    # WARN: 不抛
    caplog.clear()
    handle_error(GridWarning(ErrorCode.GRID_W101, "warn msg"), logger=log, reraise=False)
    assert any("GRID-W101" in r.message for r in caplog.records)

    # ERROR: 抛 (reraise=True)
    caplog.clear()
    with pytest.raises(GridError):
        handle_error(GridError(ErrorCode.GRID_E001, "err"), logger=log, reraise=True)
    assert any("GRID-E001" in r.message for r in caplog.records)

    # ERROR: 不抛 (reraise=False)
    caplog.clear()
    handle_error(GridError(ErrorCode.GRID_E001, "err swallow"), logger=log, reraise=False)
    assert any("GRID-E001" in r.message for r in caplog.records)

    # FATAL: subprocess 验证 sys.exit(1)
    src_str = str(_SRC).replace("\\", "\\\\")
    result = subprocess.run(
        [sys.executable, "-c", (
            f"import sys; sys.path.insert(0, '{src_str}'); "
            "import logging; logging.disable(logging.CRITICAL); "
            "from errors.error_codes import GridFatalError, ErrorCode, handle_error; "
            "handle_error(GridFatalError(ErrorCode.PG_E010, 'fatal'))"
        )],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"期望 exit 1, 实际 {result.returncode}"


# ─── classify_error ──────────────────────────────────────────────
def test_classify_error_wrap_and_passthrough():
    """classify_error 包裸 Exception + 透传 GridError."""
    try:
        raise ValueError("裸 ValueError")
    except ValueError as e:
        ge = classify_error(e, default_code=ErrorCode.PG_E010)
        assert isinstance(ge, GridError) and ge.code == "PG-E010"

    try:
        raise GridWarning(ErrorCode.GRID_W101, "原 GridWarning")
    except GridWarning as e:
        assert classify_error(e) is e  # 透传
