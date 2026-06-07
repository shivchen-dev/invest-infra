"""
盘前报模块
DB 优先策略：优先从 daily_market_snapshot 读取，cache miss 时走 MCP 并写入 DB
补充：旧版 WOA 数据直接接入（index_quotes / etf_alpha_signals / etf_quotes）
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import date, timedelta

from reports.market_data_cache import MarketDataCache

logger = logging.getLogger(__name__)

# 指数 ID → 名称映射
INDEX_NAMES = {
    1: '上证指数',
    2: '深证成指',
    3: '创业板指',
    4: '沪深300',
    5: '科创50',
    6: '中证500',
    7: '中证1000',
    8: '上证50',
}


class PreMarketReporter:
    """盘前报生成器"""

    # 工具定义（用于 MCP 调用和 DB 写入的映射）
    TOOL_MAP = [
        {"name": "sector_analysis",    "data_type": "sector_analysis",    "params": {"source": "dongcai_concept", "period": 60,  "detailLevel": "standard", "format": "json"}},
        {"name": "smart_hotlist",      "data_type": "smart_hotlist",      "params": {"source": "combined",           "limit": 10,  "detailLevel": "standard", "format": "json"}},
        {"name": "limit_stats",        "data_type": "limit_stats",        "params": {"date": "__DATE__",             "detailLevel": "standard", "format": "json"}},
        {"name": "auction_market_scan", "data_type": "auction_scan",      "params": {"tradeDate": "__DATE__",        "sortBy": "bidStrength", "limit": 15, "detailLevel": "standard", "format": "json"}},
    ]

    def __init__(self, mcp_client, cache: Optional[MarketDataCache] = None):
        self.mcp = mcp_client
        self.cache = cache

    async def fetch(self, trade_date: str = None) -> Dict[str, Any]:
        """
        获取盘前报数据

        DB 优先策略（针对 MCP 工具）：
        - cache 存在时：优先从 DB 读取，MCP 结果同时写入 DB（自举）
        - cache 不存在时：直接走 MCP（MCP 结果写入 DB）

        旧版 WOA 数据直接走 DB 查询，不经过 cache：
        - index_quotes → 今日预判
        - etf_alpha_signals → 策略方向信号
        - etf_quotes → ETF盘前溢价率

        Args:
            trade_date: 交易日期，默认为上一交易日
        """
        # 默认为上一交易日（盘前报在当日开盘前生成）
        if trade_date is None:
            from reports.trading_day import get_last_trading_day
            trade_date = get_last_trading_day()

        trade_date_str = trade_date if isinstance(trade_date, str) else trade_date.strftime("%Y-%m-%d")
        logger.info(f"盘前报：开始获取数据 (date={trade_date_str})")

        cache = self.cache or MarketDataCache(trade_date_str)

        # ── Step 1: 直接从 DB 读取旧版 WOA 数据 ─────────────────────────
        db_data = self._get_db_data(trade_date_str)

        # ── Step 2: MCP 工具，cache miss 时走 MCP ─────────────────────────
        results = {}
        cache_misses = []

        for tool in self.TOOL_MAP:
            dt = tool["data_type"]
            data = cache.get(dt)
            if data is not None:
                results[dt] = data
            else:
                cache_misses.append(tool)

        if cache_misses:
            mcp_batch = []
            for tool in cache_misses:
                params = {}
                for k, v in tool["params"].items():
                    if "__DATE__" in str(v):
                        params[k] = trade_date_str
                    else:
                        params[k] = v
                mcp_batch.append({"name": tool["name"], "params": params})

            mcp_results = await self.mcp.call_batch(mcp_batch)

            for tool in cache_misses:
                dt = tool["data_type"]
                data = mcp_results.get(dt, {})
                if data:
                    results[dt] = data
                    cache.save(dt, tool["name"], data)

        # ── Step 3: 提取各板块数据 ─────────────────────────────────────────
        sector_data      = results.get("sector_analysis", {})
        hotlist_data     = results.get("smart_hotlist", {})
        limit_stats_data = results.get("limit_stats", {})
        auction_data     = results.get("auction_scan", {})

        sentiment   = self._extract_sentiment(limit_stats_data)
        sectors     = self._extract_sectors(sector_data)
        candidates  = self._extract_auction_candidates(auction_data)

        # 组装完整数据
        data = {
            "trade_date": trade_date_str,
            # 1. 今日预判（来自 index_quotes）
            "prediction": self._extract_prediction(db_data),
            # 2. 今日主线预判（来自 sector_analysis）
            "main_lines": self._extract_main_lines(sectors, db_data),
            # 3. 盘前异动（来自 auction_market_scan）
            "auction": {
                "strongest": candidates,
                "weak_to_strong": self._extract_weak_to_strong(auction_data),
                "observe": [],
            },
            # 4. 宏观/事件面（cls_news）
            "macro_events": await self._extract_macro_events(trade_date_str),
            # 5. 策略方向跟踪（来自 etf_alpha_signals 五因子）
            "strategy_signals": self._extract_strategy_signals(db_data),
            # 6. ETF盘前信号（来自 etf_quotes）
            "etf_premarket": self._extract_etf_premarket(db_data),
            # 7. 今日操作参考（stub）
            "operation_ref": {},
            # 8. 明日关注点（stub）
            "tomorrow_focus": [],
            # 辅助字段（供 formatter 或后续模块使用）
            "macro": {
                "limit_up_count": limit_stats_data.get("sealedLimitUp", limit_stats_data.get("limitUp", 0)),
                "limit_down_count": limit_stats_data.get("sealedLimitDown", limit_stats_data.get("limitDown", 0)),
            },
            "sectors": sectors,
            "sentiment": sentiment,
            "candidates": candidates,
            "risks": self._extract_risks(limit_stats_data),
            "raw_data": {**db_data, **results},
        }

        logger.info(f"盘前报：数据获取完成，候选股 {len(candidates)} 只")
        return data

    # ── 旧版 WOA 数据直接查询 ────────────────────────────────────────────────

    def _get_db_data(self, trade_date: str) -> Dict[str, Any]:
        """直接查询旧版 WOA 数据表（index_quotes / etf_alpha_signals / etf_quotes）"""
        try:
            from loader.pg import get_conn
        except Exception as e:
            logger.warning(f"无法导入 loader.pg: {e}")
            return {}

        data = {}
        try:
            with get_conn() as conn:
                cur = conn.cursor()

                # 1. index_quotes — 大盘指数
                cur.execute("""
                    WITH latest AS (
                        SELECT index_id, close_point, trade_date,
                               LAG(close_point) OVER (PARTITION BY index_id ORDER BY trade_date) as prev_close
                        FROM index_quotes
                        WHERE trade_date <= %s
                    )
                    SELECT l.index_id, l.close_point, l.prev_close,
                           ROUND((l.close_point - l.prev_close) / NULLIF(l.prev_close, 0) * 100, 2) as change_pct,
                           iq.amplitude, iq.amount
                    FROM latest l
                    JOIN index_quotes iq ON iq.index_id = l.index_id AND iq.trade_date = l.trade_date
                    WHERE l.trade_date = (SELECT MAX(trade_date) FROM index_quotes WHERE trade_date <= %s)
                    ORDER BY l.index_id
                """, (trade_date, trade_date))
                index_rows = cur.fetchall()
                data["index_quotes"] = [
                    {
                        "index_id": r[0],
                        "name": INDEX_NAMES.get(r[0], f"指数{r[0]}"),
                        "close": float(r[1]) if r[1] else None,
                        "prev_close": float(r[2]) if r[2] else None,
                        "change_pct": float(r[3]) if r[3] else 0.0,
                        "amplitude": float(r[4]) if r[4] else 0.0,
                        "amount": float(r[5]) if r[5] else 0.0,
                    }
                    for r in index_rows
                ]

                # 2. etf_alpha_signals — 最新五因子评分（取 TOP 50 综合评分）
                cur.execute("""
                    SELECT e.code, e.name, e.跟踪指数,
                           a.composite_score, a.signal, a.signal_reason,
                           a.norm_momentum, a.norm_value, a.norm_liquidity,
                           a.norm_volatility, a.norm_money_flow,
                           a.fundamental_score, a.risk_score, a.info_score,
                           a.liquidity_score, a.score_rank
                    FROM etf_alpha_signals a
                    JOIN etfs e ON e.id = a.etf_id
                    WHERE a.calc_date = (SELECT MAX(calc_date) FROM etf_alpha_signals)
                    AND e.is_active = true
                    ORDER BY a.score_rank ASC
                    LIMIT 50
                """, )
                etf_rows = cur.fetchall()
                data["etf_alpha_signals"] = [
                    {
                        "code": r[0], "name": r[1], "track_index": r[2],
                        "composite_score": float(r[3]) if r[3] else 0,
                        "signal": r[4], "signal_reason": r[5],
                        "norm_momentum": float(r[6]) if r[6] else None,
                        "norm_value": float(r[7]) if r[7] else None,
                        "norm_liquidity": float(r[8]) if r[8] else None,
                        "norm_volatility": float(r[9]) if r[9] else None,
                        "norm_money_flow": float(r[10]) if r[10] else None,
                        "fundamental_score": float(r[11]) if r[11] else None,
                        "risk_score": float(r[12]) if r[12] else None,
                        "info_score": float(r[13]) if r[13] else None,
                        "liquidity_score": float(r[14]) if r[14] else None,
                        "score_rank": r[15],
                    }
                    for r in etf_rows
                ]

                # 3. etf_quotes — ETF 溢价率（取有溢价率数据的）
                cur.execute("""
                    SELECT e.code, e.name, e.category, e.跟踪指数,
                           q.close_price, q.premium_rate, q.iopv, q.turnover_rate
                    FROM etf_quotes q
                    JOIN etfs e ON e.id = q.etf_id
                    WHERE q.trade_date = (SELECT MAX(trade_date) FROM etf_quotes)
                    AND e.is_active = true
                    AND q.premium_rate IS NOT NULL
                    ORDER BY ABS(q.premium_rate) DESC
                    LIMIT 20
                """)
                etf_quote_rows = cur.fetchall()
                data["etf_quotes"] = [
                    {
                        "code": r[0], "name": r[1], "category": r[2], "track_index": r[3],
                        "close": float(r[4]) if r[4] else None,
                        "premium_rate": float(r[5]) if r[5] else 0.0,
                        "iopv": float(r[6]) if r[6] else None,
                        "turnover_rate": float(r[7]) if r[7] else 0.0,
                    }
                    for r in etf_quote_rows
                ]

                logger.info(f"盘前报：DB数据 index_quotes={len(data.get('index_quotes',[]))} "
                           f"etf_alpha={len(data.get('etf_alpha_signals',[]))} "
                           f"etf_quotes={len(data.get('etf_quotes',[]))}")

        except Exception as e:
            logger.warning(f"盘前报：DB数据查询失败: {e}")

        return data

    # ── 数据提取方法 ─────────────────────────────────────────────────────────

    def _extract_prediction(self, db_data: Dict[str, Any]) -> Dict[str, Any]:
        """从 index_quotes 提取今日预判（大盘点位 + 情绪）"""
        indices = db_data.get("index_quotes", [])
        if not indices:
            return {}

        # 计算市场整体涨跌幅（用沪深300代表性指数）
        main_indices = [i for i in indices if i["index_id"] in (4, 1, 3, 5)]
        if not main_indices:
            main_indices = indices[:3]

        avg_change = sum(i["change_pct"] for i in main_indices) / len(main_indices)

        # 大盘描述
        if avg_change > 1:
            大盘 = "高开"
        elif avg_change > 0.2:
            大盘 = "小幅高开"
        elif avg_change > -0.5:
            大盘 = "平开/小幅低开"
        elif avg_change > -2:
            大盘 = "低开"
        else:
            大盘 = "大幅低开"

        # 情绪判断
        if avg_change > 1:
            情绪 = "乐观"
        elif avg_change > 0:
            情绪 = "偏暖"
        elif avg_change > -1:
            情绪 = "中性偏谨慎"
        elif avg_change > -2:
            情绪 = "谨慎"
        else:
            情绪 = "悲观"

        # 构建指数列表字符串
        idx_strs = []
        for i in indices[:5]:
            chg = i["change_pct"]
            chg_str = f"{chg:+.2f}%" if chg else "N/A"
            idx_strs.append(f"{i['name']} {i['close']:.2f}({chg_str})")

        逻辑 = f"昨日 {'/'.join(idx_strs)} 【来源：index_quotes.close_point / change_pct】"

        return {
            "大盘": 大盘,
            "情绪": 情绪,
            "逻辑": 逻辑,
            "情绪依据": f"主要指数平均涨跌 {avg_change:+.2f}%，市场整体{'偏弱' if avg_change < 0 else '偏强'} 【来源：index_quotes.change_pct】",
            "indices": indices,
            "来源": "index_quotes",
        }

    def _extract_main_lines(self, sectors: Dict[str, Any], db_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 sector_analysis + etf_alpha_signals 提取今日主线预判（≤2条）"""
        main_lines = []

        # 尝试从 sector_analysis 找强势板块
        strong = sectors.get("strong", [])
        starting = sectors.get("starting_strong", [])
        if strong:
            top = strong[0] if isinstance(strong[0], dict) else {}
            if top:
                main_lines.append({
                    "板块": top.get("name", top.get("sector", "主线")),
                    "逻辑": top.get("reason", top.get("desc", "板块动量强")),
                })
        if starting and len(main_lines) < 2:
            top2 = starting[0] if isinstance(starting[0], dict) else {}
            if top2:
                main_lines.append({
                    "板块": top2.get("name", top2.get("sector", "主线")),
                    "逻辑": top2.get("reason", top2.get("desc", "板块启动")),
                })

        # 如果没有 sector_analysis 数据，用 etf_alpha_signals 综合评分 TOP
        if not main_lines:
            etf_list = db_data.get("etf_alpha_signals", [])
            if etf_list:
                # 取跟踪不同指数的 TOP 1
                seen_tracks = set()
                for etf in etf_list:
                    track = etf.get("track_index", "")
                    if track and track not in seen_tracks and len(main_lines) < 2:
                        seen_tracks.add(track)
                        main_lines.append({
                            "板块": track,
                            "逻辑": f"综合评分 rank #{etf.get('score_rank', '?')}，{etf.get('signal_reason', '')} 【来源：etf_alpha_signals.composite_score】",
                        })

        return main_lines

    def _extract_sentiment(self, limit_stats: Dict) -> Dict[str, Any]:
        try:
            limit_up = limit_stats.get("sealedLimitUp", limit_stats.get("limitUp", 0))
            limit_down = limit_stats.get("sealedLimitDown", limit_stats.get("limitDown", 0))
            if limit_up > limit_down * 3:
                signal = "多头"
            elif limit_down > limit_up * 3:
                signal = "空头"
            else:
                signal = "中性"
            return {"signal": signal, "limit_up_count": limit_up, "limit_down_count": limit_down}
        except Exception as e:
            logger.warning(f"情绪提取失败: {e}")
            return {"signal": "未知", "limit_up_count": 0, "limit_down_count": 0}

    def _extract_sectors(self, sector_data: Dict) -> Dict[str, Any]:
        try:
            top_lists = sector_data.get("data", {}).get("topLists", {})
            continuing = top_lists.get("continuingStrong", [])
            starting = top_lists.get("startingStrong", [])
            return {
                "strong": (continuing[:5] if continuing else []),
                "starting_strong": (starting[:5] if starting else []),
            }
        except Exception as e:
            logger.warning(f"板块提取失败: {e}")
            return {"strong": [], "starting_strong": []}

    def _extract_auction_candidates(self, auction_data: Dict) -> list:
        try:
            rows = auction_data.get("content", [{}])[0].get("text", "")
            if isinstance(rows, str):
                import json
                parsed = json.loads(rows)
                rows = parsed.get("rows", []) if isinstance(parsed, dict) else []
            candidates = []
            for row in rows[:10]:
                code = row.get("code", "")
                name = row.get("name", "")
                change_rate = row.get("changeRate", row.get("change_rate", 0))
                if code and name:
                    candidates.append({"code": code, "name": name, "change": change_rate})
            return candidates
        except Exception as e:
            logger.warning(f"竞价候选提取失败: {e}")
            return []

    def _extract_weak_to_strong(self, auction_data: Dict) -> list:
        """从 auction_data 中尝试提取弱转强候选（暂用竞价候选前3作为备选）"""
        # auction_market_scan 的 preset=weak_to_strong 会单独采集，这里用主数据的前3
        candidates = self._extract_auction_candidates(auction_data)
        return candidates[:3]

    def _extract_risks(self, limit_stats: Dict) -> Dict[str, Any]:
        announcements = []
        try:
            limit_down = limit_stats.get("sealedLimitDown", limit_stats.get("limitDown", 0))
            if limit_down > 20:
                announcements.append({"title": f"跌停数量偏多 ({limit_down} 只)"})
            broken_rate = limit_stats.get("brokenRate", 0)
            if broken_rate and float(broken_rate) > 30:
                announcements.append({"title": f"炸板率偏高 ({broken_rate}%)"})
        except Exception as e:
            logger.warning(f"风险提取失败: {e}")
        return {"announcements": announcements} if announcements else {"announcements": []}

    def _extract_strategy_signals(self, db_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 etf_alpha_signals 五因子提取策略方向信号
        五大方向映射：
          - phys_ai     → norm_momentum（动量因子）
          - optical     → norm_liquidity（流动性因子）
          - pcb         → norm_volatility（波动率因子）
          - cpo         → norm_money_flow（资金流因子）
          - etf_broad   → composite_score（综合评分）
        """
        etf_list = db_data.get("etf_alpha_signals", [])
        if not etf_list:
            return {"phys_ai": {}, "optical": {}, "pcb": {}, "cpo": {}, "etf_broad": {}}

        def median(values: List[float]) -> float:
            """计算中位数，忽略 None"""
            cleaned = [v for v in values if v is not None and v != 0]
            if not cleaned:
                return 50.0
            cleaned.sort()
            n = len(cleaned)
            return cleaned[n // 2] if n % 2 == 1 else (cleaned[n // 2 - 1] + cleaned[n // 2]) / 2

        # 聚合所有 ETF 的各因子
        mom_values    = [e["norm_momentum"]   for e in etf_list if e.get("norm_momentum") is not None]
        val_values    = [e["norm_value"]       for e in etf_list if e.get("norm_value") is not None]
        liq_values    = [e["norm_liquidity"]   for e in etf_list if e.get("norm_liquidity") is not None]
        vol_values    = [e["norm_volatility"]   for e in etf_list if e.get("norm_volatility") is not None]
        mf_values     = [e["norm_money_flow"]   for e in etf_list if e.get("norm_money_flow") is not None]
        score_values  = [e["composite_score"]  for e in etf_list if e.get("composite_score")]

        mom_med  = median(mom_values)   if mom_values   else 50.0
        val_med  = median(val_values)   if val_values   else None
        liq_med  = median(liq_values)   if liq_values   else 50.0
        vol_med  = median(vol_values)   if vol_values   else 50.0
        mf_med   = median(mf_values)    if mf_values    else 50.0
        score_med = median(score_values) if score_values else 500.0

        def factor_signal(value: float) -> str:
            if value is None: return "无数据"
            if value >= 70: return "强势"
            if value >= 50: return "中性"
            if value >= 30: return "偏弱"
            return "弱势"

        def top_etf_for_factor(values: List, etf_list: List, key: str) -> Dict:
            """找出该因子得分最高的 ETF"""
            if not values:
                return {}
            max_val = max(v for v in values if v is not None)
            for e in etf_list:
                if e.get(key) is not None and abs(e[key] - max_val) < 0.01:
                    return {"name": e["name"], "code": e["code"], "score": e[key]}
            return {}

        # TOP ETF（综合评分）
        top_score_etf = {}
        if etf_list:
            top = min(etf_list, key=lambda e: e.get("score_rank", 9999))
            top_score_etf = {"name": top["name"], "code": top["code"], "rank": top.get("score_rank")}

        return {
            "phys_ai": {
                "signal": factor_signal(mom_med),
                "yesterday": f"动量因子中位数 {mom_med:.1f} 【来源：etf_alpha_signals.norm_momentum】",
                "core_data": {"top_etf": top_etf_for_factor(mom_values, etf_list, "norm_momentum")},
            },
            "optical": {
                "signal": factor_signal(liq_med),
                "yesterday": f"流动性因子中位数 {liq_med:.1f} 【来源：etf_alpha_signals.norm_liquidity】",
                "core_data": {"top_etf": top_etf_for_factor(liq_values, etf_list, "norm_liquidity")},
            },
            "pcb": {
                "signal": factor_signal(vol_med),
                "yesterday": f"波动率因子中位数 {vol_med:.1f} 【来源：etf_alpha_signals.norm_volatility】",
                "core_data": {},
            },
            "cpo": {
                "signal": factor_signal(mf_med),
                "yesterday": f"资金流因子中位数 {mf_med:.1f} 【来源：etf_alpha_signals.norm_money_flow】",
                "core_data": {},
            },
            "etf_broad": {
                "signal": factor_signal(score_med / 10),  # 归一化
                "yesterday": f"综合评分中位数 {score_med:.1f}，TOP: {top_score_etf.get('name','')} rank#{top_score_etf.get('rank','')} 【来源：etf_alpha_signals.composite_score】",
                "core_data": {"top_etf": top_score_etf},
            },
            "来源": "etf_alpha_signals",
        }

    def _extract_etf_premarket(self, db_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 etf_quotes 提取 ETF 盘前溢价率
        分类：宽基（沪深300/创业板/科创50/上证50）、行业、QDII
        """
        quotes = db_data.get("etf_quotes", [])
        if not quotes:
            return {"broad": {}, "industry": [], "qdii": []}

        broad_keywords = ["沪深300", "创业板", "科创50", "上证50", "中证500", "中证1000", "红利"]
        qdii_keywords  = ["纳指", "标普", "纳斯达克", "日经", "港股", "QDII", "全球", "海外"]

        broad_etfs = []
        qdii_etfs  = []
        industry_etfs = []

        for q in quotes:
            name = q.get("name", "")
            track = q.get("track_index", "")
            category = q.get("category", "")
            code = q.get("code", "")
            premium = q.get("premium_rate", 0)
            close = q.get("close")
            iopv = q.get("iopv")
            turnover = q.get("turnover_rate", 0)

            item = {
                "name": name, "code": code,
                "premium_pct": f"{premium:+.2f}",
                "premium_raw": premium,
                "close": close,
                "iopv": iopv,
                "turnover": f"{turnover:.2f}%",
                "track": track or "",
            }

            is_broad = any(kw in (name + (track or '')) for kw in broad_keywords)
            is_qdii  = any(kw in (name + (track or '')) for kw in qdii_keywords)

            if is_broad:
                broad_etfs.append(item)
            elif is_qdii:
                qdii_etfs.append(item)
            else:
                industry_etfs.append(item)

        # 宽基 ETF 取溢价率绝对值最大者（最值得关注的）
        def sort_by_abs_premium(lst):
            return sorted(lst, key=lambda x: abs(x["premium_raw"]), reverse=True)

        broad_top = sort_by_abs_premium(broad_etfs)[:3]
        qdii_top  = sort_by_abs_premium(qdii_etfs)[:5]
        ind_top   = sort_by_abs_premium(industry_etfs)[:3]

        # 宽基 대표：取溢价率偏离最大的那只
        broad_repr = broad_top[0] if broad_top else {}
        if broad_repr:
            broad_repr = {
                "name": broad_repr["name"],
                "code": broad_repr["code"],
                "premium_pct": broad_repr["premium_pct"],
                "close": broad_repr["close"],
                "turnover": broad_repr["turnover"],
            }

        return {
            "broad": broad_repr,
            "industry": ind_top,
            "qdii": qdii_top,
            "来源": "etf_quotes",
        }

    async def _extract_macro_events(self, trade_date_str: str) -> List[Dict[str, Any]]:
        """从 cls_news 获取今日财经新闻，筛选 Top3-5 条宏观/事件面要闻"""
        try:
            result = await self.mcp.call_tool(
                "cls_news",
                date=trade_date_str,
                level="AB",
                limit=50,
                detailLevel="standard",
                format="json",
            )
        except Exception as e:
            logger.warning(f"盘前报：cls_news 调用失败: {e}")
            return []

        if not result or result.get("error"):
            logger.warning("盘前报：cls_news 返回空结果或错误")
            return []

        # 兼容多种响应结构
        items = (
            result.get("content", [{}])[0].get("text", [])
            if result.get("content") and len(result["content"]) > 0
            else None
        )
        if not items:
            items = result.get("data", result.get("news", []))
        if isinstance(items, str):
            try:
                import json as _json

                items = _json.loads(items)
            except (_json.JSONDecodeError, ValueError):
                logger.warning("盘前报：cls_news 新闻数据解析失败")
                return []

        if not items or not isinstance(items, list):
            logger.warning("盘前报：cls_news 数据格式异常")
            return []

        # 筛选 A/B 级要闻，取 Top5
        events = []
        for item in items[:50]:
            keyword = item.get("keyword", "") or item.get("keywords", "") or ""
            title = item.get("title", "") or ""
            desc = item.get("description", "") or item.get("content", "") or item.get("摘要", "") or ""
            time_str = item.get("time", "") or item.get("publishTime", "") or item.get("发布时间", "")

            # 解析时间：兼容多种格式
            parsed_time = self._parse_news_time(time_str)

            sectors = []
            for key in ("sectors", "affectedSectors", "影响板块", "行业", "概念"):
                val = item.get(key, [])
                if val:
                    if isinstance(val, str):
                        sectors = [s.strip() for s in val.split(",") if s.strip()]
                    else:
                        sectors = [str(s) for s in val[:5]]
                    break

            events.append({
                "keyword": keyword or self._extract_keyword_from_title(title),
                "description": (title + ("；" + desc if desc and not desc.startswith(title) else ""))[:200],
                "time": parsed_time,
                "affected_sectors": sectors,
            })

        return events[:5]

    def _parse_news_time(self, raw: str) -> str:
        """将新闻时间字符串标准化为 'HH:MM' 格式"""
        if not raw or not isinstance(raw, str):
            return ""
        import re

        m = re.search(r"(\d{1,2}):(\d{2})", raw)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        # 如果只有日期部分（YYYY-MM-DD），尝试提取日期
        m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
        if m:
            return m.group(1)
        return raw[:16]

    @staticmethod
    def _extract_keyword_from_title(title: str) -> str:
        """从标题提取关键词：优先取括号内内容或前8字"""
        if not title:
            return ""
        import re

        # 先尝试括号内的关键词
        for m in re.finditer(r"[（(](.+?)[）)]", title):
            kw = m.group(1).strip()
            if len(kw) <= 20 and len(kw) >= 2:
                return kw
        # 取前8个中文字符
        chars = [c for c in title if "一" <= c <= "鿿"]
        return "".join(chars[:8]) or title[:16]