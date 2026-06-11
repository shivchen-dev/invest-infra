"""Pipeline 告警模块 — 去重冷却 + Webhook 推送。

通过 AlertManager 单例提供统一告警入口，用于 pipeline 异常事件的
即时通知（而非仅依赖日志轮转）。

使用方式：
    from src.alert import alerts

    alerts.error("DB write failed", details="connection refused")
    alerts.warn("fetch returned empty for code=000001")
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 冷却周期：同一 (level, message) 对在此时间内只发一次
_COOLDOWN_SECONDS = 3600


@dataclass(frozen=True)
class _AlertKey:
    level: str
    message: str


class AlertManager:
    """Pipeline 告警管理器（单例，通过模块级 alerts 暴露）。"""

    __slots__ = ("_webhook_url", "_cooldowns", "_client")

    def __init__(self, webhook_url: Optional[str] = None):
        self._webhook_url = webhook_url
        # (level, message) → last_send_timestamp
        self._cooldowns: dict[_AlertKey, float] = {}
        self._client = httpx.Client(timeout=10.0) if webhook_url else None

    def send(
        self,
        level: str,
        message: str,
        details: Optional[str] = None,
    ) -> None:
        """发送一条告警。

        Args:
            level:      "error", "warning" 或 "info"（大写写入）
            message:    简短标题，用于冷却键
            details:    可选扩展信息（异常堆栈、代码等）
        """
        level = level.upper()
        key = _AlertKey(level, message)

        now = time.monotonic()
        if key in self._cooldowns and now - self._cooldowns[key] < _COOLDOWN_SECONDS:
            return  # 仍在冷却中，静默跳过

        self._cooldowns[key] = now

        payload = {
            "pipeline": "invest-data-pipeline",
            "level": level,
            "message": message,
            "details": details or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._deliver(payload)

    def error(self, message: str, details: Optional[str] = None) -> None:
        self.send("ERROR", message, details)

    def warn(self, message: str, details: Optional[str] = None) -> None:
        self.send("WARNING", message, details)

    def info(self, message: str, details: Optional[str] = None) -> None:
        self.send("INFO", message, details)

    def _deliver(self, payload: dict) -> None:
        """将告警推送到 webhook。"""
        if not self._webhook_url:
            return

        try:
            resp = self._client.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "alert webhook 返回 HTTP %d: %s", resp.status_code, resp.text[:200]
                )
        except httpx.HTTPError as e:
            logger.error("alert webhook 发送失败: %s", e)

    def configure(self, webhook_url: Optional[str]) -> None:
        """在 pipeline 启动时配置 webhook（避免模块初始化期就建连接）。"""
        if webhook_url and not self._webhook_url:
            self._webhook_url = webhook_url
            self._client = httpx.Client(timeout=10.0)

    def close(self) -> None:
        if self._client:
            self._client.close()


# ── 模块级单例 ──────────────────────────────────────────────────────
alerts: AlertManager = AlertManager()
