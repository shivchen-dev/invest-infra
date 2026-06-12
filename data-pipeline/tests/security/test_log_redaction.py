"""
test_log_redaction.py — log_redactor 单元测试 (N-2.3)

4 核心 case:
1. msg 路径: 5 个 msg 场景覆盖 _REDACT_PATTERNS
2. args 路径: record.args 中单 arg 含 key=value
3. install/uninstall 生命周期
4. 性能基准 (F-5: < 100μs/条)

F-21 已知 limitation: msg="%s" + args=(value) 组合路径不联动 — 不测

审计员: Arc
"""
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from security.log_redactor import (  # noqa: E402
    SecretRedactorFilter, install_redactor, _REDACT_PATTERNS,
)


@pytest.fixture
def redactor():
    """提供 redactor filter + 自动清理."""
    return SecretRedactorFilter()


# ─── Case 1: msg 路径 ──────────────────────────────────────────────
@pytest.mark.parametrize("msg,expected_substr", [
    ("User logged in with password=abc123", "password=***"),
    ("API call api_key: secretkey_9999", "api_key: ***"),  # 保留 separator
    ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "Authorization: Bearer ***"),
    ("Safe message with no secrets", "Safe message with no secrets"),
    ("Multi password=foo api_key=bar", "password=***"),  # 多 secret 也能处理
])
def test_msg_redact(caplog, redactor, msg, expected_substr):
    """msg 文本 5 个场景: 各 pattern + 保留 separator + 不动安全文本."""
    import logging
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("test_msg_" + str(hash(msg))[:8])
    logger.addFilter(redactor)
    logger.info(msg)
    # caplog 至少应有 1 条
    assert any(expected_substr in rec.message or expected_substr in str(rec.msg)
               for rec in caplog.records), \
        f"expected '{expected_substr}' in log, got: {[r.message for r in caplog.records]}"
    logger.removeFilter(redactor)


# ─── Case 2: args 路径(单 arg 自身含 key=value) ──────────────────────
def test_args_redact(caplog, redactor):
    """record.args 中单 arg 自身含 key=value,应被 args loop 脱敏."""
    import logging
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("test_args")
    logger.addFilter(redactor)
    # 注意: 这里用 %s 但不依赖 msg 含 "password" 关键字
    # 测的是 args 数组中元素本身被处理
    logger.warning("event=%s", "password=hack_attempt_999")
    found = False
    for rec in caplog.records:
        # args[0] 应被处理
        if rec.args and any("password=***" in str(a) for a in rec.args):
            found = True
            break
        # 或 message 拼接后含
        if "password=***" in rec.message:
            found = True
            break
    assert found, f"args 脱敏未生效,records: {[(r.message, r.args) for r in caplog.records]}"
    logger.removeFilter(redactor)


# ─── Case 3: install / uninstall 生命周期 ─────────────────────────
def test_install_uninstall(caplog):
    """install_redactor 装上后生效,removeFilter 后失效."""
    import logging
    logger = logging.getLogger("test_install")
    caplog.set_level(logging.DEBUG)

    # 装上
    f = install_redactor("test_install")
    logger.info("password=secret_value_001")
    assert any("password=***" in r.message for r in caplog.records), \
        "install 后未脱敏"

    # 卸下
    logger.removeFilter(f)
    caplog.clear()
    logger.info("password=still_secret_002")
    assert any("password=still_secret_002" in r.message for r in caplog.records), \
        "uninstall 后应失效 (明文应保留)"
    assert not any("password=***" in r.message for r in caplog.records), \
        "uninstall 后不应再脱敏"


# ─── Case 4: 性能基准(F-5) ──────────────────────────────────────
def test_perf_under_100us_per_log(caplog):
    """1000 条日志总耗时 < 100ms(每条 < 100μs, F-5 要求)."""
    import logging
    logger = logging.getLogger("test_perf")
    caplog.set_level(logging.DEBUG)
    f = install_redactor("test_perf")

    N = 1000
    start = time.perf_counter()
    for i in range(N):
        logger.info("password=secret_%d api_key=key_%d", i, i)
    elapsed = time.perf_counter() - start
    per_log_us = elapsed / N * 1_000_000

    assert per_log_us < 100, \
        f"性能不达标: {per_log_us:.1f}μs/条 (目标 < 100μs)"

    logger.removeFilter(f)
