"""
盘后报模块
DB Only 策略：所有数据从 daily_market_snapshot 读取，MCP 仅用于采集入库，报告不触发 MCP
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import date

from reports.market_data_cache import MarketDataCache
from loader.pg import get_conn

logger = logging.getLogger(__name__)


# 所需数据源（与 market_data_collector.py 采集清单对应）
REQUIRED_DATA_TYPES = [
    "limit_stats",
    "hot_sectors",
    "market_overview",
    "limit_up_ladder",
    "board_break",
    "capital_flow_mkt",
]


# DB 未命中时的降级数据（不触发 MCP）
# 必须包含足够的嵌套结构，确保 PostMarketFormatter 访问任意字段时不崩溃
FALLBACK_DATA = {
    "limit_stats": {
        "sealedLimitUp": 0,
        "sealedLimitDown": 0,
        "sealRate": "N/A",
        "breakRate": "N/A",
    },
    "hot_sectors": {
        "rows": [{"name": "暂无数据", "change": "N/A", "reason": "数据采集中"}],
        "summary": {"totalSectors": 0, "topSector": "暂无"},
    },
    "market_leaders": {
        "hasMainLine": False,
        "mainLines": [],
        "observations": ["主线数据采集中"],
    },
    "limit_up_ladder": {
        "rows": [],
        "summary": {"totalLimitUp": 0, "totalStreak2": 0, "totalStreak3": 0},
    },
    "board_break": {
        "focus": "all",
        "statusBreakdown": {
            "total": 0,
            "sealedAgain": 0,
            "broken": 0,
            "firstBoardBroken": 0,
            "highBoardBroken": 0,
        },
        "breakRate": "N/A",
    },
    "capital_flow_mkt": {
        "items": [{"name": "暂无数据", "netBuy": 0, "pct": "N/A"}],
        "summary": {"totalNetBuy": 0, "mainSector": "暂无"},
    },
}


class PostMarketReporter:
    """盘后报生成器"""

    def __init__(self, cache: Optional[MarketDataCache] = None):
        self.cache = cache

    async def fetch(self, trade_date: str = None) -> Dict[str, Any]:
        """
        获取盘后报数据（纯 DB 读取，DB 未命中则用降级数据，不触发 MCP）

        Args:
            trade_date: 交易日期，默认为今日
        """
        if trade_date is None:
            trade_date = date.today().strftime("%Y-%m-%d")

        logger.info(f"盘后报：开始获取数据 (date={trade_date})，DB Only 模式")

        cache = self.cache or MarketDataCache(trade_date)

        # 只从 DB 读取，DB 未命中用降级数据（不触发 MCP）
        results = {}
        cache_misses = []

        for dt in REQUIRED_DATA_TYPES:
            data = cache.get(dt)
            if data is not None:
                results[dt] = data
            else:
                cache_misses.append(dt)
                results[dt] = FALLBACK_DATA.get(dt, {})

        db_hit_count = len(REQUIRED_DATA_TYPES) - len(cache_misses)
        logger.info(f"盘后报：DB 命中 {db_hit_count}/{len(REQUIRED_DATA_TYPES)}，降级 {len(cache_misses)} 项（{'无' if not cache_misses else ', '.join(cache_misses)}）")

        limit_stats = results.get("limit_stats", {})
        hot_sectors = results.get("hot_sectors", {})
        leaders = results.get("market_overview", {})  # market_overview 含温度/涨跌家数
        # 注入 ladder 的 boardSummary/emotionMetrics 到 limit_stats（供子方法使用）
        ladder_data = results.get("limit_up_ladder", {})
        if isinstance(ladder_data, dict):
            limit_stats["_board_summary"] = ladder_data.get("boardSummary", [])
            limit_stats["_emotion_metrics"] = ladder_data.get("emotionMetrics", {})
        ladder = results.get("limit_up_ladder", {})
        board_break = results.get("board_break", {})
        flow_data = results.get("capital_flow_mkt", {})

        data = {
            "trade_date": trade_date,
            "summary": self._build_summary(leaders),
            "limit_stats": self._extract_limit_stats(limit_stats),
            "main_review": self._build_main_review(hot_sectors, limit_stats),
            "ladder": self._build_ladder(ladder),
            "board_break": self._format_board_break_data(results),
            "capital_flow": self._extract_capital_flow(flow_data),
            "strategy_review": self._extract_strategy_review(results),
            "etf_arbitrage": self._extract_etf_arbitrage(trade_date),
            "risk_review": self._build_risk_review(limit_stats, board_break),
            "day_summary": self._build_day_summary(limit_stats),
        }

        logger.info(f"盘后报：数据获取完成")
        return data

    def _build_summary(self, leaders: Dict) -> Dict[str, Any]:
        """构建 PostMarketFormatter._format_summary 期望的结构"""
        rise = leaders.get("riseCount", 0) if isinstance(leaders, dict) else 0
        fall = leaders.get("fallCount", 0) if isinstance(leaders, dict) else 0
        temp = leaders.get("marketTemperature", 50) if isinstance(leaders, dict) else 50
        if temp < 30:
            sentiment, tomorrow = "冷", "等待修复"
        elif temp < 45:
            sentiment, tomorrow = "弱", "观察"
        elif temp < 60:
            sentiment, tomorrow = "中性", "观察"
        else:
            sentiment, tomorrow = "热", "注意轮动"
        return {
            "indices": {},
            "counts": {"rise": rise, "fall": fall},
            "amount": "-",
            "sentiment": sentiment,
            "tomorrow_expect": tomorrow,
        }

    def _extract_limit_stats(self, limit_stats: Dict) -> Dict[str, Any]:
        """构建 PostMarketFormatter._format_limit_stats 期望的结构"""
        current_up = limit_stats.get("sealedLimitUp", limit_stats.get("limitUp", 0))
        current_down = limit_stats.get("sealedLimitDown", limit_stats.get("limitDown", 0))
        touched_up = limit_stats.get("touchedLimitUp", 0)
        broken_up = limit_stats.get("brokenLimitUp", 0)
        break_rate_pct = f"{round(broken_up / touched_up * 100, 1)}%" if touched_up else "-"
        board_summary = limit_stats.get("_board_summary", [])
        first_board = second_board = third_plus = "-"
        for entry in board_summary:
            lvl = entry.get("level", 0)
            cnt = entry.get("count", 0)
            if lvl == 1:
                first_board = cnt
            elif lvl == 2:
                second_board = cnt
            elif lvl >= 3:
                third_plus = cnt
        return {
            "limit_up": current_up,
            "limit_up_yesterday": "-",
            "seal_rate": f"{round(limit_stats.get("limitUpSealRate", 0) * 100, 1)}%" if limit_stats.get("limitUpSealRate") else "-",
            "break_rate": break_rate_pct,
            "limit_down": current_down,
            "limit_down_yesterday": "-",
            "broken": broken_up,
            "continued": "-",
            "first_board": first_board,
            "second_board": second_board,
            "third_plus": third_plus,
        }

    def _build_main_review(self, hot_sectors: Dict, limit_stats: Dict) -> List[Dict]:
        """构建 PostMarketFormatter._format_main_review 期望的结构"""
        rows = []
        if isinstance(hot_sectors, dict):
            rows = hot_sectors.get("rows", []) or []
        emotion = limit_stats.get("_emotion_metrics", {})
        promo = emotion.get("promotionRates", {})
        br_val = promo.get("2to3", 0)
        sealed = limit_stats.get("sealedLimitUp", 0)
        strength = "强" if br_val >= 30 and sealed > 30 else "观察"
        main_review = []
        for row in rows[:3]:
            core_stocks = row.get("coreStocks", [])
            leaders = [{"name": s.get("name", ""), "code": s.get("code", "")} for s in core_stocks[:3]]
            main_review.append({
                "sector": row.get("name", "-"),
                "performance": row.get("highBoard", "-"),
                "leaders": leaders,
                "signal_strength": strength,
                "tomorrow": "观察",
            })
        return main_review

    def _build_ladder(self, ladder: Dict) -> List[Dict]:
        """构建 PostMarketFormatter._format_ladder 期望的结构（列表，每项含 streak）"""
        rows = []
        if isinstance(ladder, dict):
            rows = ladder.get("rows", []) or []
        return [
            {
                "streak": row.get("level", 1) or 1,
                "name": row.get("name", ""),
                "code": row.get("code", ""),
                "reason": row.get("reasonType", ""),
                "url": f"https://stock.quicktiny.cn/quote/{row.get('code', '')}",
            }
            for row in (rows[:20] or [])
        ]

    def _format_board_break_data(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """构建 PostMarketFormatter._format_board_break 期望的结构"""
        try:
            bb = results.get("board_break", {})
            rows = bb.get("rows", []) or []
            broken_list = [
                {
                    "name": r.get("name", ""),
                    "code": r.get("code", ""),
                    "status": r.get("status", ""),
                    "open_pct": r.get("open_pct", "-"),
                }
                for r in rows
            ]
            status_bd = bb.get("statusBreakdown", {})
            high_board_broken = [
                {
                    "name": "",
                    "code": "",
                    "streak": "-",
                }
            ] if status_bd.get("highBoardBroken", 0) > 0 else []
            return {
                "broken": broken_list if broken_list else [],
                "high_board_broken": high_board_broken,
            }
        except Exception as e:
            logger.warning(f"断板数据格式化失败: {e}")
            return {"broken": [], "high_board_broken": []}

    def _extract_capital_flow(self, flow_data: Dict) -> Dict[str, Any]:
        """提取资金流向"""
        return flow_data  # 原始数据透传

    def _extract_strategy_review(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """从 limit_stats + hot_sectors 提取策略方向复盘"""
        try:
            limit_stats = results.get("limit_stats", {})
            hot_sectors = results.get("hot_sectors", {})
            rows = hot_sectors.get("rows", [])[:5]  # 取前5热板块
            return {
                "phys_ai": {
                    "limit_up_count": limit_stats.get("sealedLimitUp", 0),
                    "seal_rate": limit_stats.get("sealRate", "N/A"),
                    "break_rate": limit_stats.get("breakRate", "N/A"),
                },
                "optical": {"top_sectors": [r.get("name") for r in rows if r.get("name")]},
                "pcb": {"hot_rows": rows},
                "cpo": {"summary": hot_sectors.get("summary", {})},
                "etf_broad": {"total_sectors": hot_sectors.get("summary", {}).get("totalSectors", 0)},
            }
        except Exception as e:
            logger.warning(f"策略方向复盘提取失败: {e}")
            return {"phys_ai": {}, "optical": {}, "pcb": {}, "cpo": {}, "etf_broad": {}}

    def _extract_etf_arbitrage(self, trade_date: str) -> Dict[str, Any]:
        """从 etf_alpha_signals 表查询 ETF 套利信号"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT etf_code, signal_type, strength, created_at
                        FROM etf_alpha_signals
                        WHERE trade_date = %s
                        ORDER BY strength DESC
                        LIMIT 10
                        """,
                        (trade_date,)
                    )
                    rows = cur.fetchall()
                    if not rows:
                        return {"signals": [], "count": 0}
                    return {
                        "signals": [
                            {
                                "etf_code": r[0],
                                "signal_type": r[1],
                                "strength": float(r[2]) if r[2] is not None else 0.0,
                                "created_at": str(r[3]) if r[3] else None,
                            }
                            for r in rows
                        ],
                        "count": len(rows),
                    }
        except Exception as e:
            logger.warning(f"ETF 套利信号查询失败: {e}")
            return {"signals": [], "count": 0}

    def _build_risk_review(self, limit_stats: Dict, board_break: Dict) -> Dict[str, Any]:
        """构建 PostMarketFormatter._format_risk_review 期望的结构"""
        break_rate_raw = limit_stats.get("breakRate", limit_stats.get("break_rate", None))
        break_rate_val = None
        try:
            if break_rate_raw is not None and str(break_rate_raw).replace(".", "").isdigit():
                break_rate_val = float(str(break_rate_raw))
        except (ValueError, TypeError):
            pass
        limit_down_count = limit_stats.get("sealedLimitDown", limit_stats.get("limitDown", 0))
        high_board_broken_status = board_break.get("statusBreakdown", {}).get("highBoardBroken", 0) if isinstance(board_break, dict) else 0
        return {
            "limit_down": {"count": limit_down_count, "change": "", "desc": ""},
            "high_board_broken": {"name": "-", "code": "-", "streak": "-"} if high_board_broken_status > 0 else None,
            "break_rate": break_rate_val,
            "st": {"has": False, "desc": ""},
        }

    def _build_day_summary(self, limit_stats: Dict) -> str:
        """构建 PostMarketFormatter._format_day_summary 期望的字符串"""
        try:
            limit_up = limit_stats.get("sealedLimitUp", 0)
            break_rate_raw = limit_stats.get("breakRate", limit_stats.get("break_rate", ""))
            if isinstance(break_rate_raw, str):
                break_rate_val = float(break_rate_raw) if break_rate_raw and break_rate_raw.replace(".", "").isdigit() else None
            elif isinstance(break_rate_raw, (int, float)):
                break_rate_val = break_rate_raw
            else:
                break_rate_val = None
            if limit_up > 30 and break_rate_val is not None and break_rate_val < 20:
                return "市场情绪偏暖，关注主线延续"
            elif break_rate_val is not None and break_rate_val > 30:
                return "炸板率偏高，注意情绪退潮风险"
            else:
                return "今日市场情绪中性，等待方向选择"
        except (ValueError, TypeError):
            return "数据不完整，暂无法形成小结"
