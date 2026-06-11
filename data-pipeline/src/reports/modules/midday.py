"""
午盘报模块
DB-only 策略：从 daily_market_snapshot 读取,cache miss 时用 FALLBACK_DATA 降级(不触发 MCP)
"""
import logging
import json
from typing import Any, Dict, List, Optional
from datetime import date

from reports.market_data_cache import MarketDataCache

logger = logging.getLogger(__name__)


class MiddayReporter:
    """午盘报生成器"""

    # 报告所需的数据类型列表
    REQUIRED_DATA_TYPES = [
        "market_overview", "concept_ranking", "smart_hotlist",
        "capital_flow_mkt", "broken_limit_up",
    ]

    # DB 未命中时的降级数据（不触发 MCP）
    FALLBACK_DATA = {
        "market_overview": {"content": [{"text": "{}"}]},
        "concept_ranking": {"content": [{"text": "{\"rows\": []}"}]},
        "smart_hotlist": {"content": [{"text": "{\"rows\": []}"}]},
        "capital_flow_mkt": {"content": [{"text": "{}"}]},
        "broken_limit_up": {"content": [{"text": "{\"rows\": []}"}]},
    }

    def __init__(self, cache: Optional[MarketDataCache] = None):
        self.cache = cache

    async def fetch(self, trade_date: str = None) -> Dict[str, Any]:
        """
        获取午盘报数据

        DB-only 策略：
        - cache 命中: 从 DB 读取
        - cache miss: 用 FALLBACK_DATA 降级(不触发 MCP)

        Args:
            trade_date: 交易日期，默认为今日
        """
        if trade_date is None:
            trade_date = date.today().strftime("%Y-%m-%d")

        logger.info(f"午盘报：开始获取数据 (date={trade_date})")

        cache = self.cache or MarketDataCache(trade_date)

        # DB 优先：cache miss 时用降级数据（不触发 MCP）
        results = {}
        for dt in self.REQUIRED_DATA_TYPES:
            data = cache.get(dt)
            if data is not None:
                results[dt] = data
            else:
                results[dt] = self.FALLBACK_DATA.get(dt, {})

        db_hit_count = sum(1 for dt in self.REQUIRED_DATA_TYPES if cache.exists(dt))
        logger.info(f"午盘报：DB 命中 {db_hit_count}/{len(self.REQUIRED_DATA_TYPES)}，降级 {len(self.REQUIRED_DATA_TYPES) - db_hit_count} 项（不触发 MCP）")

        market_data  = results.get("market_overview", {})
        concept_data = results.get("concept_ranking", {})
        hotlist_data = results.get("smart_hotlist", {})
        flow_data    = results.get("capital_flow_mkt", {})
        broken_data  = results.get("broken_limit_up", {})

        # 构建与 IntradayFormatter 对齐的输出结构
        concept = self._extract_concepts(concept_data)
        market_raw = self._extract_market(market_data)

        data = {
            "trade_date": trade_date,
            "market_state": self._build_market_state(market_raw, hotlist_data),
            "main_lines": self._build_main_lines(concept),
            "limit_events": {},
            "strategy_realtime": self._extract_strategy_realtime(),
            "etf_intraday": self._extract_etf_intraday(),
            "risk_signals": self._build_risk_signals(broken_data),
        }

        logger.info(f"午盘报：数据获取完成")
        return data

    def _extract_market(self, market_data: Dict) -> Dict[str, Any]:
        try:
            content = market_data.get("content", [])
            if content:
                text = content[0].get("text", "{}")
                data = json.loads(text) if isinstance(text, str) else text
                up_count = data.get("upCount", data.get("up_count", 0))
                down_count = data.get("downCount", data.get("down_count", 0))
                return {"up_count": up_count, "down_count": down_count, "temperature": data.get("temperature", "未知")}
        except Exception as e:
            logger.warning(f"市场概况提取失败: {e}")
        return {"up_count": 0, "down_count": 0, "temperature": "未知"}

    def _extract_concepts(self, concept_data: Dict) -> Dict[str, Any]:
        try:
            content = concept_data.get("content", [])
            if content:
                text = content[0].get("text", "[]")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                concepts = []
                for row in (rows[:10] or []):
                    concepts.append({
                        "name": row.get("name", row.get("tsCode", "")),
                        "limit_up_count": row.get("limitUpNum", 0),
                        "change": row.get("change", 0),
                    })
                return {"top": concepts}
        except Exception as e:
            logger.warning(f"概念提取失败: {e}")
        return {"top": []}

    def _extract_hot_stocks(self, hotlist_data: Dict) -> Dict[str, Any]:
        try:
            content = hotlist_data.get("content", [])
            if content:
                text = content[0].get("text", "[]")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                stocks = []
                for row in (rows[:10] or []):
                    stocks.append({
                        "code": row.get("code", ""),
                        "name": row.get("name", ""),
                        "change": row.get("change", 0),
                    })
                return {"stocks": stocks}
        except Exception as e:
            logger.warning(f"热门股提取失败: {e}")
        return {"stocks": []}

    def _extract_capital_flow(self, flow_data: Dict) -> Dict[str, Any]:
        try:
            content = flow_data.get("content", [])
            if content:
                text = content[0].get("text", "{}")
                data = json.loads(text) if isinstance(text, str) else text
                return {
                    "main_flow": data.get("mainInflow", data.get("main_flow", "未知")),
                    "north_flow": data.get("hsgtInflow", data.get("north_flow", "未知")),
                }
        except Exception as e:
            logger.warning(f"资金流向提取失败: {e}")
        return {"main_flow": "未知", "north_flow": "未知"}

    def _build_market_state(self, market_raw: Dict, hotlist_data: Dict) -> Dict[str, Any]:
        """构建 IntradayFormatter 期望的 market_state 结构"""
        counts = {}
        hotlist_content = hotlist_data.get("content", [])
        if hotlist_content and isinstance(hotlist_content[0], dict):
            try:
                raw_text = hotlist_content[0].get("text", "[]")
                hd = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
                rows = hd.get("rows", []) or []
                up_count = sum(1 for r in rows if r.get("change", 0) > 0)
                down_count = sum(1 for r in rows if r.get("change", 0) < 0)
                counts["up"] = up_count
                counts["down"] = down_count
                counts["flat"] = len(rows) - up_count - down_count
            except Exception:
                counts["up"] = market_raw.get("up_count", "-")
                counts["down"] = market_raw.get("down_count", "-")
        return {
            "indices": {"HS300": market_raw.get("hs300_point", "-")},
            "counts": counts,
            "sentiment": market_raw.get("temperature", "未知"),
        }

    def _build_main_lines(self, concept: Dict) -> List[Dict]:
        """构建 IntradayFormatter 期望的 main_lines 结构"""
        top = concept.get("top", []) or []
        lines = []
        for item in top[:2]:
            name = item.get("name", "-")
            change = item.get("change", 0)
            sign = "+" if isinstance(change, (int, float)) and change > 0 else ""
            leader_change = f"{sign}{change}%" if isinstance(change, (int, float)) else "-"
            lines.append({
                "sector": name,
                "signal_strength": "强" if (isinstance(change, (int, float)) and change > 0) else "观察",
                "leader": {"name": name, "code": "", "change": leader_change},
                "spread_to": "",
            })
        return lines

    def _build_risk_signals(self, broken_data: Dict) -> Dict[str, Any]:
        """构建 IntradayFormatter 期望的 risk_signals 结构"""
        limit_down_count = 0
        try:
            content = broken_data.get("content", [])
            if content:
                text = content[0].get("text", "{}")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                limit_down_count = len(rows)
        except Exception:
            pass
        return {
            "limit_down_count": limit_down_count,
            "high_board_broken": [],
            "break_rate": None,
        }

    def _extract_risks(self, broken_data: Dict) -> Dict[str, Any]:
        broken_list = []
        try:
            content = broken_data.get("content", [])
            if content:
                text = content[0].get("text", "{}")
                data = json.loads(text) if isinstance(text, str) else text
                rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
                for row in (rows[:10] or []):
                    broken_list.append({"name": row.get("name", ""), "code": row.get("code", "")})
        except Exception as e:
            logger.warning(f"风险提取失败: {e}")
        return {"broken_limit_up": broken_list} if broken_list else {"broken_limit_up": []}

    def _extract_etf_intraday(self) -> Dict[str, Any]:
        logger.info("午盘报：ETF盘中溢价率暂未接入")
        return {"alerts": []}

    def _extract_strategy_realtime(self) -> Dict[str, Any]:
        logger.info("午盘报：策略方向实时信号暂未接入")
        return {"phys_ai": {}, "optical": {}, "pcb": {}, "cpo": {}, "etf_broad": {}}
