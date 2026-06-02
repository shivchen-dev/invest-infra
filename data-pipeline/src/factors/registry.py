"""因子定义注册表 — 所有因子的元数据定义"""

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class FactorCategory(str, Enum):
    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    ALTERNATIVE = "alternative"


class FactorFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass
class FactorDef:
    """单个因子的元数据定义"""
    key: str                          # 唯一标识: roe_ttm, momentum_60d
    name: str                         # 中文名: ROE(TTM)
    category: FactorCategory          # 类别
    sub_category: str                 # 子类: profitability/valuation/momentum/...
    description: str                  # 计算逻辑描述
    data_source: str                  # 依赖数据源: financial_reports/daily_quotes/news
    frequency: FactorFrequency        # 计算频率
    higher_better: bool = True        # 是否越大越好
    pct_rank: bool = True             # 是否做百分位排名
    version: int = 1


# ── 注册表 ────────────────────────────────────────────────────
_FACTORS: dict[str, FactorDef] = {}


def register(fd: FactorDef):
    """注册一个因子定义"""
    _FACTORS[fd.key] = fd
    logger.debug(f"注册因子: {fd.key} ({fd.name})")


def get_factor(key: str) -> Optional[FactorDef]:
    return _FACTORS.get(key)


def list_factors(category: Optional[FactorCategory] = None) -> list[FactorDef]:
    if category:
        return [f for f in _FACTORS.values() if f.category == category]
    return list(_FACTORS.values())


def register_all():
    """注册所有内置因子（幂等）"""
    if _FACTORS:
        return  # 已注册

    # ── 基本面因子 ──
    register(FactorDef("roe", "ROE净资产收益率", FactorCategory.FUNDAMENTAL, "profitability",
                        "净利润 / 净资产", "financial_reports", FactorFrequency.QUARTERLY))
    register(FactorDef("roa", "ROA总资产收益率", FactorCategory.FUNDAMENTAL, "profitability",
                        "净利润 / 总资产", "financial_reports", FactorFrequency.QUARTERLY))
    register(FactorDef("gross_margin", "毛利率", FactorCategory.FUNDAMENTAL, "profitability",
                        "(营收-营业成本)/营收", "financial_reports", FactorFrequency.QUARTERLY))
    register(FactorDef("net_profit_margin", "净利率", FactorCategory.FUNDAMENTAL, "profitability",
                        "净利润/营收", "financial_reports", FactorFrequency.QUARTERLY))
    register(FactorDef("debt_ratio", "资产负债率", FactorCategory.FUNDAMENTAL, "risk",
                        "总负债/总资产", "financial_reports", FactorFrequency.QUARTERLY, higher_better=False))
    register(FactorDef("eps_growth_yoy", "归母净利润同比增长率", FactorCategory.FUNDAMENTAL, "growth",
                        "(本期归母净利润-上年同期)/|上年同期|", "financial_reports", FactorFrequency.QUARTERLY))

    # ── 技术面因子 ──
    register(FactorDef("momentum_5d", "5日动量", FactorCategory.TECHNICAL, "momentum",
                        "过去5个交易日累计涨跌幅", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("momentum_20d", "20日动量", FactorCategory.TECHNICAL, "momentum",
                        "过去20个交易日累计涨跌幅", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("momentum_60d", "60日动量", FactorCategory.TECHNICAL, "momentum",
                        "过去60个交易日累计涨跌幅", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("volatility_20d", "20日波动率", FactorCategory.TECHNICAL, "risk",
                        "过去20日收益率标准差(年化)", "daily_quotes", FactorFrequency.DAILY, higher_better=False))
    register(FactorDef("avg_turnover_20d", "20日平均换手率", FactorCategory.TECHNICAL, "liquidity",
                        "过去20日平均换手率", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("ma5_deviation", "5日均线偏离度", FactorCategory.TECHNICAL, "pattern",
                        "(收盘价-MA5)/MA5", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("volume_ratio_5d", "5日量比", FactorCategory.TECHNICAL, "volume",
                        "当日成交量/5日均量", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("reversal_5d", "5日反转因子", FactorCategory.TECHNICAL, "reversal",
                        "-(近5日涨幅)，做空短期动量", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("reversal_20d", "20日反转因子", FactorCategory.TECHNICAL, "reversal",
                        "-(近20日涨幅)", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("gap_open_pct", "跳空幅度", FactorCategory.TECHNICAL, "pattern",
                        "(今日开盘价-昨日收盘价)/昨日收盘价", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("intraday_break_pct", "日内突破幅度", FactorCategory.TECHNICAL, "pattern",
                        "(最高价-最低价)/最低价", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("volume_surge", "量能爆发", FactorCategory.TECHNICAL, "volume",
                        "今日成交量/20日均量 - 1", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("volume_cv", "成交量变异系数", FactorCategory.TECHNICAL, "volume",
                        "20日成交量标准差/均值", "daily_quotes", FactorFrequency.DAILY))
    register(FactorDef("main_net_flow_5d", "5日主力净流入", FactorCategory.TECHNICAL, "money_flow",
                        "近5日买盘金额-卖盘金额", "fund_flow_big_deal", FactorFrequency.DAILY))
    register(FactorDef("main_net_flow_ratio_5d", "5日主力净流入占比", FactorCategory.TECHNICAL, "money_flow",
                        "主力净流入/总成交金额", "fund_flow_big_deal", FactorFrequency.DAILY))

    # ── 另类因子 ──
    register(FactorDef("sentiment_score", "新闻情感分数", FactorCategory.ALTERNATIVE, "sentiment",
                        "过去7日新闻情感平均分", "news_articles", FactorFrequency.WEEKLY))
    register(FactorDef("news_volume_7d", "7日新闻量", FactorCategory.ALTERNATIVE, "coverage",
                        "过去7日新闻报道数量", "news_articles", FactorFrequency.WEEKLY))
    register(FactorDef("news_volume_change", "新闻量变化率", FactorCategory.ALTERNATIVE, "coverage",
                        "(本周新闻量-上周)/上周", "news_articles", FactorFrequency.WEEKLY))

    logger.info(f"因子注册完成: 共 {len(_FACTORS)} 个")


def get_factor_ids(conn=None) -> dict[str, int]:
    """从 PG factor_definitions 表获取 {key: id} 映射。
    优先复用传入的 conn，否则新建（调用方负责关闭）。"""
    from src.config import pg
    _conn = conn or psycopg2.connect(pg.uri)
    _close = conn is None  # 只有我们自己创建连接时才关闭
    try:
        with _conn:
            with _conn.cursor() as cur:
                cur.execute("SELECT factor_key, id FROM factor_definitions")
                return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        if _close:
            _conn.close()
