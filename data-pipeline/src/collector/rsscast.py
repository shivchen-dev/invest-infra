"""RssCast MCP 数据采集器 — 通过 MCP JSON-RPC 调用获取股票/指数数据"""

import json
import logging
import urllib.request
import urllib.error
from datetime import date
from typing import Optional

from src.collector.retry import with_retry

logger = logging.getLogger(__name__)


class RssCastError(Exception):
    """RssCast 请求级别的错误（网络超时、认证失败、JSON-RPC error 等）"""
    pass


class RssCastNoData(Exception):
    """RssCast 返回空数据（代码错误或该日期无数据）"""
    pass


class RssCastClient:
    """RssCast MCP 客户端 — 实例化方式，非全局状态"""

    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token
        self._id_counter = 1

    def _next_id(self):
        n = self._id_counter
        self._id_counter += 1
        return n

    def _call(self, tool_name: str, arguments: dict) -> dict:
        """发送 JSON-RPC 2.0 请求到 RssCast MCP，返回 parsed result。

        抛出:
            RssCastError: 网络超时、HTTP 错误、认证失败、JSON-RPC error 等请求级错误
            RssCastNoData: result 为空（内容不存在），调用方应视为"无数据"而非"失败"
        """
        if not self.endpoint or not self.token:
            raise RuntimeError("RssCast not configured — provide endpoint and token")

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": self._next_id(),
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error(f"RssCast HTTP {e.code}: {body[:200]}")
            raise RssCastError(f"HTTP {e.code}") from e
        except TimeoutError:
            logger.error("RssCast request timeout")
            raise RssCastError("timeout") from e
        except Exception as e:
            logger.error(f"RssCast request failed: {e}")
            raise RssCastError(str(e)) from e

        if "error" in data:
            err = data["error"]
            logger.error(f"RssCast JSON-RPC error: {err}")
            raise RssCastError(str(err))

        result = data.get("result", {})
        if not result:
            raise RssCastNoData(f"no result for {tool_name}")

        return result

    # ─── 工具封装 ─────────────────────────────────────────────────────────────

    def fetch_stock_quotes(self, codes: list[str]) -> list[dict]:
        """查询股票实时价格。返回原始 RssCast 格式。"""
        if not codes:
            return []
        result = self._call("StockPriceQuery", {"codes": codes})
        raw = result.get("content", [])
        if not raw:
            raise RssCastNoData(f"empty content for StockPriceQuery: {codes}")
        try:
            return json.loads(raw[0].get("text", "[]"))
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"fetch_stock_quotes parse error: {e}")
            raise RssCastNoData(f"parse error: {e}") from e

    def fetch_stock_kline(
        self,
        codes: list[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """查询股票历史日线。返回原始 RssCast 格式。"""
        if not codes:
            return []
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date

        result = self._call(
            "StockKLineQuery",
            {
                "codes": codes,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            },
        )
        raw = result.get("content", [])
        if not raw:
            raise RssCastNoData(f"empty content for StockKLineQuery: {codes}")
        try:
            text = raw[0].get("text", "[]")
            start_idx = text.find("[{")
            end_idx = text.rfind("]")
            if start_idx < 0:
                return []
            return json.loads(text[start_idx:end_idx + 1])
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"fetch_stock_kline parse error: {e}")
            raise RssCastNoData(f"parse error: {e}") from e

    def fetch_index_quotes(self, codes: list[str]) -> list[dict]:
        """查询股票指数实时价格。返回原始 RssCast 格式。"""
        if not codes:
            return []
        result = self._call("StockIndexPriceQuery", {"codes": codes})
        raw = result.get("content", [])
        if not raw:
            raise RssCastNoData(f"empty content for StockIndexPriceQuery: {codes}")
        try:
            return json.loads(raw[0].get("text", "[]"))
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"fetch_index_quotes parse error: {e}")
            raise RssCastNoData(f"parse error: {e}") from e

    def fetch_index_kline(
        self,
        codes: list[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """查询股票指数历史日线。返回原始 RssCast 格式。"""
        if not codes:
            return []
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date

        result = self._call(
            "StockIndexKLineQuery",
            {
                "codes": codes,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            },
        )
        raw = result.get("content", [])
        if not raw:
            raise RssCastNoData(f"empty content for StockIndexKLineQuery: {codes}")
        try:
            text = raw[0].get("text", "[]")
            start_idx = text.find("[{")
            end_idx = text.rfind("]")
            if start_idx < 0:
                return []
            return json.loads(text[start_idx:end_idx + 1])
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"fetch_index_kline parse error: {e}")
            raise RssCastNoData(f"parse error: {e}") from e

    # ─── 字段映射：RssCast → Silver 层标准字段 ───────────────────────────────

    @staticmethod
    def map_stock_record(r: dict) -> dict:
        """将 RssCast 股票记录映射为 Silver 层标准字段。"""
        return {
            "stock_code": r.get("code", ""),
            "trade_date": r.get("timeString", "")[:10],
            "open_price": r.get("open"),
            "high_price": r.get("high"),
            "low_price": r.get("low"),
            "close_price": r.get("close"),
            "pre_close": r.get("prev_close"),
            "volume": r.get("volume"),
            "amount": r.get("amount"),
            "turnover_rate": r.get("turnover_rate"),
            "amplitude": r.get("amplitude"),
            "change_pct": r.get("change_pct"),
            "source": "rsscast",
        }

    @staticmethod
    def map_index_record(r: dict) -> dict:
        """将 RssCast 指数记录映射为 index_quotes 表标准字段。"""
        return {
            "index_code": r.get("code", ""),
            "trade_date": r.get("timeString", "")[:10],
            "open_point": r.get("open"),
            "high_point": r.get("high"),
            "low_point": r.get("low"),
            "close_point": r.get("close"),
            "pre_close": r.get("prev_close"),
            "volume": r.get("volume"),
            "amount": r.get("amount"),
            "change_pct": r.get("change_pct"),
            "amplitude": r.get("amplitude"),
            "source": "rsscast",
        }

    # ─── 对外接口：标准化输出 ────────────────────────────────────────────────

    def fetch_stock_quotes_normalized(self, codes: list[str]) -> list[dict]:
        return [self.map_stock_record(r) for r in self.fetch_stock_quotes(codes)]

    def fetch_stock_kline_normalized(
        self,
        codes: list[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        return [self.map_stock_record(r) for r in self.fetch_stock_kline(codes, start_date, end_date)]

    def fetch_index_quotes_normalized(self, codes: list[str]) -> list[dict]:
        return [self.map_index_record(r) for r in self.fetch_index_quotes(codes)]

    def fetch_index_kline_normalized(
        self,
        codes: list[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        return [self.map_index_record(r) for r in self.fetch_index_kline(codes, start_date, end_date)]


# ─── 便捷函数（保持向后兼容，内部创建 client）─────────────────────────────

# 全局默认 client（延迟创建，每次调用 configure 时重建）
_default_client: Optional[RssCastClient] = None


def configure(endpoint: str, token: str) -> None:
    """重建全局默认 client（向后兼容）"""
    global _default_client
    _default_client = RssCastClient(endpoint, token)


def _client() -> RssCastClient:
    global _default_client
    if _default_client is None:
        raise RuntimeError("RssCast not configured — call configure(endpoint, token) first")
    return _default_client


# 透传函数


@with_retry()
def fetch_stock_quotes(codes: list[str]) -> list[dict]:
    return _client().fetch_stock_quotes(codes)


@with_retry()
def fetch_stock_kline(codes: list[str], start_date=None, end_date=None) -> list[dict]:
    return _client().fetch_stock_kline(codes, start_date, end_date)


@with_retry()
def fetch_index_quotes(codes: list[str]) -> list[dict]:
    return _client().fetch_index_quotes(codes)


@with_retry()
def fetch_index_kline(codes: list[str], start_date=None, end_date=None) -> list[dict]:
    return _client().fetch_index_kline(codes, start_date, end_date)


@with_retry()
def fetch_stock_quotes_normalized(codes: list[str]) -> list[dict]:
    return _client().fetch_stock_quotes_normalized(codes)


@with_retry()
def fetch_stock_kline_normalized(codes: list[str], start_date=None, end_date=None) -> list[dict]:
    return _client().fetch_stock_kline_normalized(codes, start_date, end_date)


@with_retry()
def fetch_index_quotes_normalized(codes: list[str]) -> list[dict]:
    return _client().fetch_index_quotes_normalized(codes)


@with_retry()
def fetch_index_kline_normalized(codes: list[str], start_date=None, end_date=None) -> list[dict]:
    return _client().fetch_index_kline_normalized(codes, start_date, end_date)