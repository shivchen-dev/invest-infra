"""
多因子综合评分卡

对标的池中的每只股票/ETF 计算综合评分（0-100），
用于辅助投资决策和信号生成。

评分维度：
  1. 质量（fundamental）   — ROE/ROA/毛利率/净利率
  2. 成长（growth）        — 净利润增速
  3. 动量（momentum）      — 5日/20日/60日动量
  4. 趋势（trend）         — MA5/MA20/MA60 多头排列
  5. 波动（risk）          — 20日波动率（低波动加权）
  6. 流动性（liquidity）   — 换手率
  7. 反转（reversal）      — 超跌反弹信号
  8. 主力资金（main_flow） — 主力净流入
  9. 日内形态（pattern）   — 开盘跳空

每维度标准化到 [0, 100]，加权求和得到总分。
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


# ─── 维度权重配置 ─────────────────────────────────────────────────────────

SCORING_WEIGHTS = {
    "fundamental": 0.15,
    "growth":      0.10,
    "momentum":    0.20,
    "trend":       0.10,
    "risk":        0.10,
    "liquidity":   0.05,
    "reversal":    0.10,
    "main_flow":   0.10,
    "pattern":     0.05,
    "etf":         0.05,
}

ETFS_WEIGHTS = {
    "etf":         0.30,
    "momentum":    0.20,
    "trend":       0.10,
    "liquidity":   0.15,
    "risk":        0.10,
    "reversal":    0.10,
    "pattern":     0.05,
}


# ─── 数据获取 ────────────────────────────────────────────────────────────────

def fetch_stock_factor_matrix(conn, calc_date: date) -> list[dict]:
    """拉取所有股票的因子值矩阵。"""
    start_60 = calc_date - timedelta(days=65)
    start_5  = calc_date - timedelta(days=10)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH mom AS (
                SELECT d.company_id,
                       MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_5d,
                       MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_20d,
                       MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_60d
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            ),
            trend AS (
                SELECT d.company_id,
                       MAX(d.close_price) FILTER(WHERE d.trade_date = %s) AS close_now,
                       AVG(d.close_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS ma5,
                       AVG(d.close_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS ma20,
                       AVG(d.close_price) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS ma60
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            ),
            vol AS (
                SELECT d.company_id,
                       AVG(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS avg_volatility,
                       STDDEV(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS std_volatility
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            ),
            liq AS (
                SELECT d.company_id,
                       AVG(d.turnover_rate) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS turnover_rate
                FROM daily_quotes d
                WHERE d.trade_date BETWEEN %s AND %s
                GROUP BY d.company_id
            ),
            mf AS (
                SELECT fbd.company_id,
                       COALESCE(SUM(fbd.amount) FILTER(WHERE fbd.deal_nature LIKE '%%买入%%'), 0) -
                       COALESCE(SUM(fbd.amount) FILTER(WHERE fbd.deal_nature LIKE '%%卖出%%'), 0) AS main_net_flow
                FROM fund_flow_big_deal fbd
                WHERE fbd.trade_time::date BETWEEN %s AND %s
                GROUP BY fbd.company_id
            ),
            fundy AS (
                SELECT c.id AS company_id,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'roe') AS roe,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'roa') AS roa,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'gross_margin') AS gross_margin,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'net_profit_margin') AS net_profit_margin,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'debt_ratio') AS debt_ratio,
                       MAX(fv.value) FILTER(WHERE fd.factor_key = 'eps_growth_yoy') AS eps_growth
                FROM companies c
                LEFT JOIN factor_values fv ON c.id = fv.company_id
                LEFT JOIN factor_definitions fd ON fv.factor_id = fd.id
                WHERE fd.factor_key IN ('roe','roa','gross_margin','net_profit_margin','debt_ratio','eps_growth_yoy')
                  AND fv.calc_date = %s
                GROUP BY c.id
            )
            SELECT
                c.id, c.code, c.name,
                t.close_now,
                m.mom_5d, m.mom_20d, m.mom_60d,
                t.ma5, t.ma20, t.ma60,
                v.avg_volatility, v.std_volatility,
                lq.turnover_rate,
                mf.main_net_flow,
                f.roe, f.roa, f.gross_margin, f.net_profit_margin, f.eps_growth
            FROM companies c
            JOIN trend t  ON c.id = t.company_id
            LEFT JOIN mom m   ON c.id = m.company_id
            LEFT JOIN vol v   ON c.id = v.company_id
            LEFT JOIN liq lq  ON c.id = lq.company_id
            LEFT JOIN mf mf   ON c.id = mf.company_id
            LEFT JOIN fundy f ON c.id = f.company_id
            WHERE t.close_now IS NOT NULL
            LIMIT 200
            """,
            (calc_date - timedelta(days=5), calc_date,
             calc_date - timedelta(days=20), calc_date,
             start_60, calc_date,
             start_60, calc_date,
             calc_date,
             calc_date - timedelta(days=5), calc_date,
             calc_date - timedelta(days=20), calc_date,
             calc_date - timedelta(days=20), calc_date,
             start_5, calc_date,
             start_5, calc_date,
             calc_date - timedelta(days=5), calc_date,
             calc_date)
        )
        return [
            {
                "id": row[0], "code": row[1], "name": row[2],
                "close_now": row[3],
                "mom_5d": row[4], "mom_20d": row[5], "mom_60d": row[6],
                "ma5": row[7], "ma20": row[8], "ma60": row[9],
                "avg_volatility": row[10], "std_volatility": row[11],
                "turnover_rate": row[12], "main_net_flow": row[13],
                "roe": row[14], "roa": row[15], "gross_margin": row[16],
                "net_profit_margin": row[17], "eps_growth": row[18],
            }
            for row in cur.fetchall()
        ]


def fetch_etf_factor_matrix(conn, calc_date: date) -> list[dict]:
    """拉取所有ETF的因子值矩阵。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH etf_mom AS (
                SELECT eq.etf_id,
                       MAX(eq.change_pct) FILTER(WHERE eq.trade_date BETWEEN %s AND %s) AS mom_5d,
                       MAX(eq.change_pct) FILTER(WHERE eq.trade_date BETWEEN %s AND %s) AS mom_20d
                FROM etf_quotes eq
                WHERE eq.trade_date BETWEEN %s AND %s
                  AND eq.source = 'akshare-hist'
                GROUP BY eq.etf_id
            ),
            etf_spot AS (
                SELECT eq.etf_id,
                       MAX(eq.change_pct) FILTER(WHERE eq.trade_date = %s) AS mom_spot,
                       MAX(eq.volume) FILTER(WHERE eq.trade_date = %s) AS volume
                FROM etf_quotes eq
                WHERE eq.trade_date = %s
                GROUP BY eq.etf_id
            )
            SELECT e.id, e.code, e.name,
                   efv.premium_rate, efv.abs_premium, efv.liquidity_score,
                   m.mom_5d, m.mom_20d,
                   s.mom_spot, s.volume
            FROM etfs e
            JOIN etf_factor_values efv ON e.id = efv.etf_id
            LEFT JOIN etf_mom m ON e.id = m.etf_id
            LEFT JOIN etf_spot s ON e.id = s.etf_id
            WHERE efv.calc_date = %s
            """,
            (calc_date - timedelta(days=5), calc_date,
             calc_date - timedelta(days=20), calc_date,
             calc_date - timedelta(days=25), calc_date,
             calc_date, calc_date, calc_date,
             calc_date)
        )
        return [
            {
                "id": row[0], "code": row[1], "name": row[2],
                "premium_rate": row[3], "abs_premium": row[4],
                "liquidity_score": row[5],
                "mom_5d": row[6], "mom_20d": row[7],
                "mom_spot": row[8], "volume": row[9],
            }
            for row in cur.fetchall()
        ]


# ─── 单标的评分计算 ─────────────────────────────────────────────────────────

def score_stock(record: dict) -> dict:
    """计算单只股票的综合评分（0-100）。"""
    w = SCORING_WEIGHTS
    scores = {}

    # 质量维度（越大越好）
    for fk, key in [("roe", "roe"), ("roa", "roa"),
                     ("gross_margin", "gross_margin"), ("net_profit_margin", "net_profit_margin")]:
        v = record.get(key)
        if v is not None:
            scores["fundamental"] = scores.get("fundamental", 0) + max(0, min(100, v * 4)) / 4
    scores["fundamental"] = scores.get("fundamental", 0)

    # 成长维度
    eg = record.get("eps_growth")
    if eg is not None:
        scores["growth"] = max(0, min(100, (eg + 50) / 1.5))

    # 动量维度
    mom_vals = [v for v in [record.get("mom_5d"), record.get("mom_20d"), record.get("mom_60d")]
                if v is not None]
    if mom_vals:
        avg_mom = sum(mom_vals) / len(mom_vals)
        scores["momentum"] = max(0, min(100, 50 + avg_mom * 8))

    # 趋势维度（MA多头排列）
    ma5, ma20, ma60 = record.get("ma5"), record.get("ma20"), record.get("ma60")
    if all(v is not None for v in [ma5, ma20, ma60]):
        ts = 0
        if ma5 > ma20: ts += 33
        if ma20 > ma60: ts += 33
        if ma5 > ma60: ts += 34
        scores["trend"] = ts
    elif ma5 is not None and ma20 is not None:
        scores["trend"] = 100 if ma5 > ma20 else 0

    # 波动维度（低波动 → 高分）
    vol = record.get("avg_volatility") or record.get("std_volatility")
    if vol is not None:
        scores["risk"] = max(0, min(100, 55 - abs(vol) * 8))

    # 流动性维度
    tr = record.get("turnover_rate")
    if tr is not None:
        scores["liquidity"] = max(0, min(100, tr * 4))

    # 主力资金维度
    mf = record.get("main_net_flow")
    if mf is not None:
        scores["main_flow"] = max(0, min(100, 50 + mf / 500))

    # 加权求和
    total_score = 0.0
    total_weight = 0.0
    for dim, weight in w.items():
        if dim in scores and scores[dim] is not None:
            total_score += scores[dim] * weight
            total_weight += weight

    final = round(total_score / total_weight, 2) if total_weight > 0 else None
    return {"score": final, "dimensions": {k: round(v, 2) for k, v in scores.items()}}


def score_etf(record: dict) -> dict:
    """计算单只ETF的综合评分（0-100）。"""
    w = ETFS_WEIGHTS
    scores = {}

    # ETF特有（流动性+溢价率）
    if record.get("liquidity_score") is not None:
        scores["etf"] = max(0, min(100, record["liquidity_score"] * 100))
        scores["liquidity"] = max(0, min(100, record["liquidity_score"] * 100))

    # 动量
    mom_vals = [v for v in [record.get("mom_5d"), record.get("mom_20d")]
                if v is not None]
    if mom_vals:
        scores["momentum"] = max(0, min(100, 50 + (sum(mom_vals)/len(mom_vals)) * 8))

    # 溢价率（低溢价/低折价 → 套利空间小 → 好）
    ap = record.get("abs_premium")
    if ap is not None:
        scores["reversal"] = max(0, min(100, 50 - ap * 10))

    total_score = sum(scores.get(d, 0) * w.get(d, 0) for d in w)
    total_weight = sum(w.get(d, 0) for d in w if d in scores)

    return {
        "score": round(total_score / total_weight, 2) if total_weight > 0 else None,
        "dimensions": {k: round(v, 2) for k, v in scores.items()},
    }


# ─── 主入口 ─────────────────────────────────────────────────────────────────

def run_scoring(min_score: float = 60.0,
                limit: int = 50,
                calc_date: Optional[date] = None) -> dict:
    """
    计算全市场综合评分。

    Args:
        min_score:  最低评分阈值
        limit:      每类最多输出标的数
        calc_date:  计算日期（默认自动找最近交易日）

    Returns:
        {"calc_date": ..., "summary": {...}, "stocks": [...], "etfs": [...]}
    """
    if calc_date is None:
        calc_date = date.today()

    conn = psycopg2.connect(pg.uri)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date) FROM daily_quotes")
            latest = cur.fetchone()[0]
        if latest and latest < calc_date:
            logger.info(f"使用最近交易日 {latest}")
            calc_date = latest

        stock_records = fetch_stock_factor_matrix(conn, calc_date)
        etf_records   = fetch_etf_factor_matrix(conn, calc_date)
        logger.info(f"评分: {len(stock_records)} 只股票, {len(etf_records)} 只ETF")

        scored_stocks = []
        for rec in stock_records:
            result = score_stock(rec)
            if result["score"] is not None and result["score"] >= min_score:
                scored_stocks.append({
                    "code": rec["code"], "name": rec["name"],
                    "close": rec.get("close_now"),
                    **result,
                })

        scored_etfs = []
        for rec in etf_records:
            result = score_etf(rec)
            if result["score"] is not None and result["score"] >= min_score:
                scored_etfs.append({
                    "code": rec["code"], "name": rec["name"],
                    "premium_rate": rec.get("premium_rate"),
                    "liquidity_score": rec.get("liquidity_score"),
                    **result,
                })

        scored_stocks.sort(key=lambda x: x["score"], reverse=True)
        scored_etfs.sort(key=lambda x: x["score"], reverse=True)

        return {
            "calc_date": calc_date.isoformat(),
            "summary": {
                "total_stocks": len(stock_records),
                "top_stocks": len(scored_stocks),
                "total_etfs": len(etf_records),
                "top_etfs": len(scored_etfs),
            },
            "stocks": scored_stocks[:limit],
            "etfs": scored_etfs[:limit],
        }
    finally:
        conn.close()
