"""
MCP 客户端封装
提供限流、重试、指数退避功能
"""
import asyncio
import time
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from functools import wraps

logger = logging.getLogger(__name__)

import os
from typing import Optional

# MCP 服务配置
MCP_BASE_URL = os.getenv("MCP_BASE_URL", "https://stock.quicktiny.cn/api/mcp-stream")

# Lazy MCP token（首次调用时求值，避免 cron 环境变量加载晚于 import）
_mcp_token: Optional[str] = None


def get_mcp_token() -> str:
    global _mcp_token
    if _mcp_token is None:
        _mcp_token = os.environ.get("MCP_TOKEN", "")
    return _mcp_token

# MCP 工具映射 (short_name -> mcp_tool_name)
MCP_TOOLS = {
    # 盘前报
    "sector_analysis": "sector_analysis",
    "smart_hotlist": "smart_hotlist",
    "limit_stats": "limit_stats",
    "auction_market_scan": "auction_market_scan",
    "official_announcements": "official_announcements",
    # 午盘报
    "market_overview": "market_overview",
    "concept_ranking": "concept_ranking",
    "capital_flow": "capital_flow",
    "broken_limit_up": "broken_limit_up",
    "watchlist_list": "watchlist_list",
    # 盘后报
    "hot_sectors": "hot_sectors",
    "market_leaders_pick": "market_leaders_pick",
    "limit_up_ladder": "limit_up_ladder",
    "board_break_analysis": "board_break_analysis",
    # 盘中轮询
    "limit_events": "limit_events",
    "limit_down": "limit_down",
    "anomaly_detection": "anomaly_detection",
    # market_data_collector 额外需要
    "market_replay_workflow": "market_replay_workflow",
    "auction_weak_to_strong": "auction_weak_to_strong",
    "auction_limitup_feedback": "auction_limitup_feedback",
    "stock_rank": "stock_rank",
    "cls_news": "cls_news",
}


class MCPClient:
    """MCP 客户端封装"""

    def __init__(self, rate_limit_ms: int = 100, max_retries: int = 3):
        self.rate_limit_ms = rate_limit_ms
        self.max_retries = max_retries
        self.last_call_time = 0
        self._call_count = 0
        self._total_calls = 0
        self._failed_calls = 0

    def _rate_limit(self):
        """限流:确保调用间隔不小于 rate_limit_ms"""
        now = time.time() * 1000
        elapsed = now - self.last_call_time
        if elapsed < self.rate_limit_ms:
            sleep_ms = (self.rate_limit_ms - elapsed) / 1000
            time.sleep(sleep_ms)
        self.last_call_time = time.time() * 1000

    def _exponential_backoff(self, attempt: int) -> float:
        """指数退避:1s, 2s, 4s"""
        return min(2 ** attempt, 8)  # 最多 8 秒

    async def call_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称(如 sector_analysis)
            **kwargs: 工具参数

        Returns:
            工具返回结果
        """
        full_tool_name = MCP_TOOLS.get(tool_name, tool_name)

        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                self._call_count += 1

                # 调用 wudao_aStock工具
                result = await self._execute_tool(full_tool_name, **kwargs)

                return result

            except Exception as e:
                self._failed_calls += 1
                error_str = str(e)
                is_quota = "DAILY_LIMIT_EXCEEDED" in error_str or "-32029" in error_str
                is_client_error = isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500

                # 配额耗尽或客户端错误：不重试，立即降级
                if is_quota or is_client_error:
                    logger.warning(f"MCP 调用失败 [{tool_name}] (不重试): {e}")
                    return self._fallback_result(tool_name)

                logger.warning(f"MCP 调用失败 [{tool_name}] attempt={attempt+1}: {e}")

                if attempt < self.max_retries - 1:
                    backoff = self._exponential_backoff(attempt)
                    logger.info(f"等待 {backoff}s 后重试...")
                    time.sleep(backoff)
                else:
                    logger.error(f"MCP 调用最终失败 [{tool_name}]: {e}")
                    return self._fallback_result(tool_name)

        return self._fallback_result(tool_name)

    async def _execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """实际执行 MCP 工具调用(异步,避免阻塞事件循环)"""
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": kwargs
            }
        }

        _token = get_mcp_token()
        if not _token:
            raise RuntimeError("MCP_TOKEN environment variable is not set. Cannot call MCP API.")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_token}"
        }

        req = urllib.request.Request(
            MCP_BASE_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method="POST"
        )

        try:
            # Use to_thread to avoid blocking the event loop
            def _sync_http():
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode('utf-8'))

            result = await asyncio.to_thread(_sync_http)

            if "error" in result:
                raise Exception(f"MCP error: {result['error']}")

            return result.get("result", {})

        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP error: {e.code} {e.reason}")
        except Exception as e:
            raise Exception(f"MCP call failed: {e}")

    def _fallback_result(self, tool_name: str) -> Dict[str, Any]:
        """降级结果"""
        logger.warning(f"返回降级结果 [{tool_name}]")
        return {
            "error": True,
            "tool": tool_name,
            "message": "数据暂不可用",
            "data": None
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计"""
        success_rate = 0 if self._call_count == 0 else (self._call_count - self._failed_calls) / self._call_count * 100
        return {
            "total_calls": self._call_count,
            "failed_calls": self._failed_calls,
            "success_rate": f"{success_rate:.1f}%"
        }


class BatchMCPClient:
    """批量 MCP 客户端"""

    def __init__(self, client: MCPClient):
        self.client = client
        self.results: Dict[str, Any] = {}

    async def call_batch(self, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        批量调用工具

        Args:
            tools: [{"name": "tool_name", "params": {...}}, ...]
        """
        results = {}

        for tool_spec in tools:
            name = tool_spec["name"]
            params = tool_spec.get("params", {})

            try:
                result = await self.client.call_tool(name, **params)
                results[name] = result
            except Exception as e:
                logger.error(f"批量调用失败 [{name}]: {e}")
                results[name] = {"error": True, "message": str(e)}

        self.results = results
        return results

    def get_result(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取单个工具结果"""
        return self.results.get(tool_name)


# 全局客户端实例
_mcp_client: Optional[MCPClient] = None
_batch_client: Optional[BatchMCPClient] = None


def get_mcp_client() -> MCPClient:
    """获取全局 MCP 客户端"""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient(rate_limit_ms=100, max_retries=3)
    return _mcp_client


def get_batch_mcp_client() -> BatchMCPClient:
    """获取全局批量 MCP 客户端(支持 call_batch)"""
    global _batch_client
    if _batch_client is None:
        _batch_client = BatchMCPClient(get_mcp_client())
    return _batch_client