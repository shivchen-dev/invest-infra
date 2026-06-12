"""
error_codes.py — 网格优先项目错误码体系 + 自定义异常 (v1.0)

错误码命名 (F-5 决策):
  {PREFIX}-{LEVEL}{NUMBER}
  PREFIX: GRID / MOM / RSK / MAC / ROT / WOA / PG / REDIS / MC / QQ
  LEVEL:  E (FATAL/ERROR) / W (WARN) / R (REPORT)
  NUMBER: 3 位

错误分层 (规范 §③ 3.1):
  L1 FATAL:  进程退出, 紧急告警
  L2 ERROR:  报告降级, 阻塞告警
  L3 WARN:   标 ⚠️, 容忍
  L4 INFO:   log.info, 留痕

审计员: Arc
"""
from __future__ import annotations

import logging
import sys
from typing import Optional


# ─── 错误码常量(常用集合) ───────────────────────────────────────────
class ErrorCode:
    """错误码字符串常量. 命名: {PREFIX}-{LEVEL}{NUMBER}.

    完整集合见 docs/specs/2026-06-12_网格优先_5维度技术规范_v1.0.md §③ 3.2
    """
    # GRID - 网格分析师
    GRID_E001 = "GRID-E001"  # 数据不足(<252d)
    GRID_E002 = "GRID-E002"  # 异常值
    GRID_W101 = "GRID-W101"  # 极端偏离(>±30%)
    GRID_W102 = "GRID-W102"  # 极端 CV (>50%)
    GRID_R201 = "GRID-R201"  # 报告格式化失败

    # MOM - 动量分析师
    MOM_E010 = "MOM-E010"
    MOM_W110 = "MOM-W110"

    # WOA - 聚合层
    WOA_E110 = "WOA-E110"   # 5 子 Agent 全失败
    WOA_W111 = "WOA-W111"   # 1-2 子 Agent 失败

    # PG - 数据库
    PG_E010 = "PG-E010"     # PG 连接失败
    PG_E011 = "PG-E011"     # PG 查询超时

    # REDIS
    REDIS_E020 = "REDIS-E020"

    # MC - MCP 客户端
    MC_W103 = "MC-W103"     # MCP 额度不足
    MC_E030 = "MC-E030"

    # QQ - 推送
    QQ_R201 = "QQ-R201"     # QQ 推送超长截断
    QQ_E040 = "QQ-E040"     # QQ 推送失败


# ─── 4 层错误分级 ─────────────────────────────────────────────────
class ErrorLevel:
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


# ─── 自定义异常 ────────────────────────────────────────────────────
class GridError(Exception):
    """网格优先项目顶级异常,默认 L2 ERROR.

    所有自定义异常继承此类,便于顶层 except GridError 兜底。
    Attributes:
        code: 错误码 (例: 'GRID-E001')
        level: 错误层 (FATAL/ERROR/WARN/INFO)
        message: 人类可读信息
    """

    def __init__(self, code: str, message: str, level: str = ErrorLevel.ERROR):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.level = level
        self.message = message


class GridFatalError(GridError):
    """L1 FATAL: 致命错误,进程退出."""

    def __init__(self, code: str, message: str):
        super().__init__(code, message, level=ErrorLevel.FATAL)


class GridWarning(GridError):
    """L3 WARN: 警告,标 ⚠️ 继续执行."""

    def __init__(self, code: str, message: str):
        super().__init__(code, message, level=ErrorLevel.WARN)


class GridReport(GridError):
    """L4 INFO/REPORT: 报告层信息,写日志不阻塞."""

    def __init__(self, code: str, message: str):
        super().__init__(code, message, level=ErrorLevel.INFO)


# ─── 错误处理工具 (N-4.2) ─────────────────────────────────────────
_logger = logging.getLogger(__name__)


def classify_error(e: Exception, default_code: str = "GRID-E001") -> GridError:
    """把任意 Exception 包装为 GridError(用于 except 块).

    如果 e 已是 GridError, 直接返回;否则用 default_code 包装。
    """
    if isinstance(e, GridError):
        return e
    return GridError(default_code, f"{type(e).__name__}: {e}")


def handle_error(
    e: GridError,
    logger: Optional[logging.Logger] = None,
    reraise: bool = True,
) -> None:
    """根据 e.level 处理 GridError.

    行为 (按 level):
        FATAL: logger.critical + sys.exit(1) (reraise 被忽略)
        ERROR: logger.error + 重新抛出(若 reraise=True)
        WARN : logger.warning + 不抛出
        INFO : logger.info + 不抛出

    Args:
        e: GridError 实例
        logger: 可选 logger,默认模块 logger
        reraise: ERROR 时是否重新抛出
    """
    log = logger or _logger
    msg = f"[{e.code}] {e.message}"

    if e.level == ErrorLevel.FATAL:
        log.critical(msg, exc_info=True)
        sys.exit(1)
    elif e.level == ErrorLevel.ERROR:
        log.error(msg, exc_info=True)
        if reraise:
            raise e
    elif e.level == ErrorLevel.WARN:
        log.warning(msg)
    elif e.level == ErrorLevel.INFO:
        log.info(msg)
    else:
        log.error(f"未知 level '{e.level}': {msg}", exc_info=True)
