"""
盘中异动监控模块

注意：盘中异动是实时数据，不走 DB 缓存，
daily_market_snapshot 中的盘中异动数据仅作历史参考。
"""
import logging
import json
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class IntradayAlertReporter:
    """
    盘中异动监控生成器

    始终走 MCP 实时获取，不走 DB 缓存。
    cache 参数存在但不使用（仅作接口兼容）。
    """

    def __init__(self, mcp_client, cache: Optional[Any] = None):
        self.mcp = mcp_client
        # cache 参数不使用，盘中异动始终实时

    async def fetch(self, trade_date: str = None) -> Dict[str, Any]:
        """
        获取盘中异动数据（实时，不走缓存）

        Args:
            trade_date: 可选，指定日期（默认今日）
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        trade_time = datetime.now().strftime("%H:%M")

        logger.info(f"盘中异动：开始获取实时数据 (date={trade_date})")

        results = await self.mcp.call_batch([
            {"name": "limit_events", "params": {"type": "limit_up", "limit": 20, "order": "desc", "detailLevel": "standard", "format": "json"}},
            {"name": "limit_down", "params": {"date": trade_date, "limit": 10, "detailLevel": "standard", "format": "json"}},
            {"name": "anomaly_detection", "params": {"date": trade_date, "detailLevel": "standard", "format": "json"}},
        ])

        limit_events = results.get("limit_events", {})
        limit_down = results.get("limit_down", {})
        anomaly = results.get("anomaly_detection", {})

        data = {
            "alert_time": trade_time,
            "trade_date": trade_date,
            "limit_up": self._extract_limit_up(limit_events),
            "limit_down": self._extract_limit_down(limit_down),
            "anomaly": self._extract_anomaly(anomaly),
            "raw_data": {
                "limit_events": limit_events,
                "limit_down": limit_down,
                "anomaly_detection": anomaly,
            }
        }

        logger.info(f"盘中异动：数据获取完成")
        return data

    def _extract_limit_up(self, events: Dict) -> Dict[str, Any]:
        try:
            content = events.get("content", [])
            if content:
                text = content[0].get("text", "[]")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                alerts = []
                for row in (rows[:10] or []):
                    alerts.append({
                        "code": row.get("code", ""),
                        "name": row.get("name", ""),
                        "time": row.get("time", ""),
                        "type": row.get("type", ""),
                    })
                return {"events": alerts, "count": len(alerts)}
        except Exception as e:
            logger.warning(f"涨停事件提取失败: {e}")
        return {"events": [], "count": 0}

    def _extract_limit_down(self, limit_down: Dict) -> Dict[str, Any]:
        try:
            content = limit_down.get("content", [])
            if content:
                text = content[0].get("text", "[]")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                stocks = []
                for row in (rows[:10] or []):
                    stocks.append({
                        "code": row.get("code", ""),
                        "name": row.get("name", ""),
                    })
                return {"stocks": stocks, "count": len(stocks)}
        except Exception as e:
            logger.warning(f"跌停池提取失败: {e}")
        return {"stocks": [], "count": 0}

    def _extract_anomaly(self, anomaly: Dict) -> Dict[str, Any]:
        try:
            content = anomaly.get("content", [])
            if content:
                text = content[0].get("text", "{}")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                anomalies = []
                for row in (rows[:5] or []):
                    anomalies.append({
                        "code": row.get("code", ""),
                        "name": row.get("name", ""),
                        "deviation": row.get("deviation", ""),
                    })
                return {"events": anomalies, "count": len(anomalies)}
        except Exception as e:
            logger.warning(f"异动检测提取失败: {e}")
        return {"events": [], "count": 0}
