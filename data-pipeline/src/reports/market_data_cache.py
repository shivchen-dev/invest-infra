#!/usr/bin/env python3
"""
市场数据缓存读取层
从 daily_market_snapshot 表读取采集好的数据

用途:
    - 盘前/午盘/盘后报告从 DB 读，不走 MCP
    - MCP 无数据时降级读取
"""

import json
import logging
from typing import Any, Optional

from loader.pg import get_conn

logger = logging.getLogger(__name__)


class MarketDataCache:
    """市场数据缓存读取器"""

    # data_type → MCP 工具名 映射
    DATA_TYPE_MAP = {
        # 大盘/复盘
        "market_overview": "market_overview",
        "limit_stats": "limit_stats",
        "market_replay": "market_replay_workflow",
        # 涨停/板块
        "hot_sectors": "hot_sectors",
        "limit_up_ladder": "limit_up_ladder",
        "board_break": "board_break_analysis",
        "broken_limit_up": "broken_limit_up",
        # 资金流
        "capital_flow_mkt": "capital_flow",
        # 竞价
        "auction_scan": "auction_market_scan",
        "auction_wts": "auction_weak_to_strong",
        "auction_feedback": "auction_limitup_feedback",
        # 排行
        "stock_rank_volume": "stock_rank",
        "stock_rank_turnover": "stock_rank",
        # 消息
        "cls_news": "cls_news",
        # 板块
        "concept_ranking": "concept_ranking",
        "sector_analysis": "sector_analysis",
    }

    def __init__(self, trade_date: str):
        self.trade_date = trade_date
        self._cache = {}

    def get(self, data_type: str) -> Optional[Any]:
        """
        读取指定类型的数据

        Args:
            data_type: 数据类型（如 limit_stats, auction_scan 等）

        Returns:
            数据字典，无数据返回 None
        """
        if data_type in self._cache:
            return self._cache[data_type]

        with get_conn() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT raw_data, collected_at FROM daily_market_snapshot
                    WHERE trade_date = %s AND data_type = %s
                    """,
                    (self.trade_date, data_type),
                )
                row = cur.fetchone()
                if row:
                    raw = row[0]
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    self._cache[data_type] = data
                    logger.info(f"[DB CACHE HIT] {data_type} @ {self.trade_date}")
                    return data
                else:
                    logger.warning(f"[DB CACHE MISS] {data_type} @ {self.trade_date}")
                    return None
            finally:
                conn.close()

    def get_or_mcp(self, data_type: str, mcp_tool: str, mcp_params: dict) -> Optional[Any]:
        """
        DB 有则返回 DB，DB 无则降级走 MCP

        Args:
            data_type: 数据类型
            mcp_tool: MCP 工具名
            mcp_params: MCP 参数字典（不含 date）
        """
        data = self.get(data_type)
        if data is not None:
            return data

        # DB 无数据，降级走 MCP
        logger.info(f"[MCP FALLBACK] {mcp_tool} (无DB缓存)")
        return None  # 由调用方决定是否走 MCP

    def exists(self, data_type: str) -> bool:
        """检查指定类型数据是否已采集"""
        with get_conn() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM daily_market_snapshot WHERE trade_date = %s AND data_type = %s",
                    (self.trade_date, data_type),
                )
                return cur.fetchone() is not None
            finally:
                conn.close()

    def save(self, data_type: str, tool_name: str, data: Any) -> bool:
        """
        将数据写入 DB 快照

        Args:
            data_type: 数据类型
            tool_name: 对应的 MCP 工具名
            data: 原始数据字典

        Returns:
            True 成功，False 失败
        """
        with get_conn() as conn:
            try:
                import json
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO daily_market_snapshot (trade_date, data_type, tool_name, raw_data, collected_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (trade_date, data_type)
                    DO UPDATE SET
                        tool_name = EXCLUDED.tool_name,
                        raw_data = EXCLUDED.raw_data,
                        collected_at = NOW()
                    """,
                    (self.trade_date, data_type, tool_name, json.dumps(data, ensure_ascii=False, default=str)),
                )
                conn.commit()
                self._cache[data_type] = data
                logger.info(f"[DB WRITE] {data_type} @ {self.trade_date}")
                return True
            except Exception as e:
                logger.error(f"[DB WRITE FAIL] {data_type}: {e}")
                conn.rollback()
                return False
            finally:
                conn.close()

    def has_all(self, data_types: list) -> bool:
        """检查是否所有类型数据都已采集"""
        return all(self.exists(dt) for dt in data_types)
