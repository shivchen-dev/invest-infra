"""
盘中异动监控模块（DB 优先 · 2026-06-12）

盘中每30分钟预采集 → intraday_snapshot（PG）→ 本模块从 PG 读。
不再在报告层直接调用 MCP。
"""
import logging
import json
from typing import Any, Dict, Optional
from datetime import datetime, date

logger = logging.getLogger(__name__)



class IntradaySnapshotCache:
    """盘中快照缓存读取器（从 intraday_snapshot 表）"""

    def __init__(self, trade_date: str):
        self.trade_date = trade_date
        self._cache: Dict[str, dict] = {}

    def get(self, data_type: str) -> Optional[dict]:
        """读取指定类型的盘中快照数据"""
        if data_type in self._cache:
            return self._cache[data_type]

        from loader.pg import get_conn
        with get_conn() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT raw_data FROM intraday_snapshot
                    WHERE trade_date = %s AND data_type = %s
                    """,
                    (self.trade_date, data_type),
                )
                row = cur.fetchone()
                if row:
                    raw = row[0]
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    # 兼容 structuredContent.data 嵌套格式
                    if isinstance(data, dict) and "structuredContent" in data:
                        sc = data.get("structuredContent", {})
                        inner = sc.get("data", {}) if isinstance(sc, dict) else {}
                        if isinstance(inner, dict):
                            data = inner
                    self._cache[data_type] = data
                    logger.info(f"[DB CACHE HIT] intraday_{data_type} @ {self.trade_date}")
                    return data
                else:
                    logger.warning(f"[DB CACHE MISS] intraday_{data_type} @ {self.trade_date}")
                    return None
            finally:
                conn.close()


class IntradayAlertReporter:
    """
    盘中异动监控生成器（DB 优先）

    数据来源：intraday_snapshot（盘中每30分钟预采集）
    MCP 仅在 DB 无数据时降级使用（保留安全性）。
    """

    def __init__(self, mcp_client, cache: Optional[Any] = None):
        self.mcp = mcp_client
        self._snapshot_cache: Optional[IntradaySnapshotCache] = None

    async def fetch(self, trade_date: str = None) -> Dict[str, Any]:
        """
        获取盘中异动数据（从 PG 预采集缓存）

        Args:
            trade_date: 可选，指定日期（默认今日）
        """
        if trade_date is None:
            trade_date = date.today().strftime("%Y-%m-%d")
        trade_time = datetime.now().strftime("%H:%M")

        logger.info(f"盘中异动：开始获取数据 (date={trade_date})")

        # 初始化 PG 缓存读取器
        self._snapshot_cache = IntradaySnapshotCache(trade_date)

        # 从 PG 读取三项数据
        limit_events_data = self._snapshot_cache.get("limit_events")
        limit_down_data = self._snapshot_cache.get("limit_down")
        anomaly_data = self._snapshot_cache.get("anomaly_detection")

        # 如果 PG 全部 miss，降级走 MCP（盘中实时补采）
        if not all([limit_events_data, limit_down_data, anomaly_data]):
            logger.warning("盘中异动：PG 缓存未命中，降级走 MCP 实时采集")
            limit_events_data, limit_down_data, anomaly_data = await self._fetch_via_mcp(trade_date)

        data = {
            "alert_time": trade_time,
            "trade_date": trade_date,
            "limit_up": self._extract_limit_up(limit_events_data or {}),
            "limit_down": self._extract_limit_down(limit_down_data or {}),
            "anomaly": self._extract_anomaly(anomaly_data or {}),
            "raw_data": {
                "limit_events": limit_events_data or {},
                "limit_down": limit_down_data or {},
                "anomaly_detection": anomaly_data or {},
            }
        }

        logger.info(f"盘中异动：数据获取完成")
        return data

    async def _fetch_via_mcp(self, trade_date: str) -> tuple:
        """MCP 降级采集（仅在 PG miss 时使用）"""
        results = await self.mcp.call_batch([
            {"name": "limit_events", "params": {"type": "limit_up", "limit": 20, "order": "desc", "detailLevel": "standard", "format": "json"}},
            {"name": "limit_down", "params": {"detailLevel": "standard", "format": "json"}},
            {"name": "anomaly_detection", "params": {"date": trade_date, "detailLevel": "standard", "format": "json"}},
        ])
        return (
            results.get("limit_events"),
            results.get("limit_down"),
            results.get("anomaly_detection"),
        )

    def _extract_limit_up(self, events: Dict) -> Dict[str, Any]:
        try:
            # 兼容两种格式：直接格式（来自 PG）或嵌套格式（来自 MCP）
            if "rows" in events:
                rows = events.get("rows", []) or []
            else:
                content = events.get("content", [])
                if content:
                    text = content[0].get("text", "[]")
                    data = json.loads(text) if isinstance(text, str) else text
                    rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                else:
                    rows = []
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
            if "rows" in limit_down:
                rows = limit_down.get("rows", []) or []
            else:
                content = limit_down.get("content", [])
                if content:
                    text = content[0].get("text", "[]")
                    data = json.loads(text) if isinstance(text, str) else text
                    rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                else:
                    rows = []
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
            if "rows" in anomaly:
                rows = anomaly.get("rows", []) or []
            else:
                content = anomaly.get("content", [])
                if content:
                    text = content[0].get("text", "{}")
                    data = json.loads(text) if isinstance(text, str) else text
                    rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                else:
                    rows = []
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