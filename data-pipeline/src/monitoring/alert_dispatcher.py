"""
alert_dispatcher.py — 4 层告警 + SLA 阈值 (v1.0)

阈值 (规范 §③ 3.5):
    FATAL: 5min 内 ≥3 次 → 紧急告警
    ERROR: 1h 内 ≥5 次 → 阻塞告警
    WARN : 1h 内 ≥10 次 → 摘要告警
    INFO : 不告警(仅记录)

设计:
- AlertDispatcher 维护每个 level 的最近事件时间戳 (deque)
- should_alert(level) 滑窗统计
- dispatch(level, summary) Phase 1 用 logging.warning 模拟
  Phase 2 接入邮件/QQ/钉钉 (本任务不实现)

与 handle_error (N-4.2) 关系: 分工
- handle_error 写 log (errors.error_codes 模块 logger)
- alert_dispatcher 由调用方显式 record(职责分离, 不依赖)

审计员: Arc
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Dict

# 4 层告警 SLA (规范 §③ 3.5)
SLA_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "FATAL": {"window_sec": 300, "threshold": 3},     # 5min 内 3 次
    "ERROR": {"window_sec": 3600, "threshold": 5},    # 1h 内 5 次
    "WARN":  {"window_sec": 3600, "threshold": 10},   # 1h 内 10 次
    "INFO":  {"window_sec": 0, "threshold": 0},       # 不告警
}

_logger = logging.getLogger(__name__)


class AlertDispatcher:
    """4 层告警分发器(单例可用)."""

    def __init__(self, thresholds: Dict[str, Dict[str, int]] = None):
        self.thresholds = thresholds or SLA_THRESHOLDS
        self._events: Dict[str, Deque[float]] = {
            level: deque() for level in self.thresholds
        }

    def _count_in_window(self, level: str, window_sec: int) -> int:
        """统计 level 在 window_sec 窗口内的事件数."""
        if window_sec == 0:
            return 0
        now = time.time()
        cutoff = now - window_sec
        dq = self._events[level]
        # 清理过期事件
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq)

    def record(self, level: str, code: str, message: str) -> None:
        """记录一次事件(供上层调用).

        Args:
            level: FATAL/ERROR/WARN/INFO
            code: 错误码(例: 'GRID-E001')
            message: 事件描述
        """
        if level not in self.thresholds:
            _logger.warning(f"未知 level '{level}': [{code}] {message}")
            return
        self._events[level].append(time.time())
        if self.should_alert(level):
            self.dispatch(level, f"近 {self.thresholds[level]['window_sec']}s 内 {self._count_in_window(level, self.thresholds[level]['window_sec'])} 次 {level} (阈值 {self.thresholds[level]['threshold']}): [{code}] {message}")

    def should_alert(self, level: str) -> bool:
        """检查 level 是否达到告警阈值."""
        sla = self.thresholds.get(level)
        if not sla or sla["threshold"] == 0:
            return False
        return self._count_in_window(level, sla["window_sec"]) >= sla["threshold"]

    def dispatch(self, level: str, summary: str) -> None:
        """实际发送告警(Phase 1 用 logging.warning 模拟).

        Phase 2 升级: 邮件/QQ/钉钉
        """
        # 紧急程度排序: FATAL > ERROR > WARN
        priority = {"FATAL": "🚨 CRITICAL", "ERROR": "❌ ERROR", "WARN": "⚠️  WARN"}.get(level, level)
        _logger.warning(f"[ALERT {priority}] {summary}")

    def reset(self) -> None:
        """清空所有事件队列(测试用)."""
        for dq in self._events.values():
            dq.clear()

    def stats(self) -> Dict[str, int]:
        """返回各 level 当前窗口内事件数(调试/监控用)."""
        return {
            level: self._count_in_window(level, sla["window_sec"])
            for level, sla in self.thresholds.items()
        }
