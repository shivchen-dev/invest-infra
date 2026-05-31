"""
ETF 因子层

提供 ETF 特有因子：
- premium_rate:           溢价率 (%) = (价格 - IOPV) / IOPV × 100
- iopv_diff:             IOPV差值 = 价格 - IOPV
- iopv_diff_pct:         IOPV差值百分比
- abs_premium:           绝对溢价率（用于筛选套利机会）
- liquidity_score:       流动性评分（基于成交量/成交额百分位）
"""

import logging
from datetime import date, timedelta

import numpy as np
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


# ─── 因子定义 ────────────────────────────────────────────────────────────────

FACTOR_DEFINITIONS = [
    {
        "factor_key": "premium_rate",
        "name": "ETF溢价率",
        "category": "etf",
        "sub_category": "pricing",
        "formula_desc": "溢价率(%) = (收盘价 - IOPV) / IOPV × 100，正值表示溢价，负值表示折价",
        "data_source": "etf_quotes",
        "frequency": "daily",
    },
    {
        "factor_key": "iopv_diff",
        "name": "IOPV差值",
        "category": "etf",
        "sub_category": "pricing",
        "formula_desc": "IOPV差值 = 收盘价 - IOPV，即价格偏离净值的绝对值",
        "data_source": "etf_quotes",
        "frequency": "daily",
    },
    {
        "factor_key": "iopv_diff_pct",
        "name": "IOPV差值百分比",
        "category": "etf",
        "sub_category": "pricing",
        "formula_desc": "IOPV差值百分比 = (收盘价 - IOPV) / IOPV × 100",
        "data_source": "etf_quotes",
        "frequency": "daily",
    },
    {
        "factor_key": "abs_premium",
        "name": "绝对溢价率",
        "category": "etf",
        "sub_category": "arbitrage",
        "formula_desc": "溢价率绝对值，用于筛选套利机会，绝对值越大套利空间越大",
        "data_source": "etf_quotes",
        "frequency": "daily",
    },
    {
        "factor_key": "liquidity_score",
        "name": "流动性评分",
        "category": "etf",
        "sub_category": "liquidity",
        "formula_desc": "基于成交量百分位排名，0-1之间，越高表示流动性越好",
        "data_source": "etf_quotes",
        "frequency": "daily",
    },
]


# ─── 计算引擎 ────────────────────────────────────────────────────────────────


def calc_premium_rate(conn, calc_date: date) -> list[dict]:
    """
    计算溢价率因子：premium_rate = (close - iopv) / iopv * 100
    仅计算当日有 IOPV 数据的记录。
    """
    results = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.id, e.code, e.name,
                   eq.close_price, eq.iopv,
                   CASE WHEN eq.iopv > 0
                        THEN (eq.close_price - eq.iopv) / eq.iopv * 100
                        ELSE NULL END AS premium_rate,
                   CASE WHEN eq.iopv > 0
                        THEN eq.close_price - eq.iopv
                        ELSE NULL END AS iopv_diff,
                   CASE WHEN eq.iopv > 0
                        THEN (eq.close_price - eq.iopv) / eq.iopv * 100
                        ELSE NULL END AS iopv_diff_pct,
                   CASE WHEN eq.iopv > 0
                        THEN ABS((eq.close_price - eq.iopv) / eq.iopv * 100)
                        ELSE NULL END AS abs_premium
            FROM etfs e
            JOIN etf_quotes eq ON e.id = eq.etf_id
            WHERE eq.trade_date = %s
              AND eq.iopv IS NOT NULL
              AND eq.iopv > 0
              AND eq.close_price IS NOT NULL
            """,
            (calc_date,),
        )
        for row in cur.fetchall():
            results.append({
                "etf_id": row[0],
                "code": row[1],
                "name": row[2],
                "close_price": row[3],
                "iopv": row[4],
                "premium_rate": row[5],
                "iopv_diff": row[6],
                "iopv_diff_pct": row[7],
                "abs_premium": row[8],
            })
    return results


def calc_liquidity_score(conn, calc_date: date, lookback_days: int = 20) -> list[dict]:
    """
    计算流动性评分：基于过去 N 天成交量百分位排名。
    0-1，越高流动性越好。
    """
    end_date = calc_date
    start_date = calc_date - timedelta(days=lookback_days)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH vol_stats AS (
                SELECT eq.etf_id,
                       PERCENT_RANK() OVER (PARTITION BY eq.trade_date ORDER BY eq.volume)
                          AS vol_percentile
                FROM etf_quotes eq
                WHERE eq.trade_date BETWEEN %s AND %s
                  AND eq.volume > 0
            )
            SELECT vs.etf_id, AVG(vs.vol_percentile) AS liquidity_score
            FROM vol_stats vs
            GROUP BY vs.etf_id
            """,
            (start_date, end_date),
        )
        return [{"etf_id": row[0], "liquidity_score": row[1]} for row in cur.fetchall()]


def save_etf_factors(conn, calc_date: date, premium_data: list, liquidity_data: list) -> int:
    """
    将 ETF 因子值写入 etf_factor_values 表。
    """
    # 构建 lookup
    liq_map = {s["etf_id"]: s["liquidity_score"] for s in liquidity_data}

    written = 0
    with conn.cursor() as cur:
        for p in premium_data:
            etf_id = p["etf_id"]
            liq = liq_map.get(etf_id)
            cur.execute(
                """
                INSERT INTO etf_factor_values
                    (etf_id, calc_date, premium_rate, iopv_diff, iopv_diff_pct, abs_premium, liquidity_score)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                    premium_rate = EXCLUDED.premium_rate,
                    iopv_diff = EXCLUDED.iopv_diff,
                    iopv_diff_pct = EXCLUDED.iopv_diff_pct,
                    abs_premium = EXCLUDED.abs_premium,
                    liquidity_score = EXCLUDED.liquidity_score,
                    quality_flag = 'good'
                """,
                (etf_id, calc_date,
                 p.get("premium_rate"), p.get("iopv_diff"),
                 p.get("iopv_diff_pct"), p.get("abs_premium"),
                 liq),
            )
            written += 1

        # 仅流动性数据但无溢价数据
        premium_ids = {p["etf_id"] for p in premium_data}
        for s in liquidity_data:
            if s["etf_id"] not in premium_ids:
                cur.execute(
                    """
                    INSERT INTO etf_factor_values
                        (etf_id, calc_date, liquidity_score)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                        liquidity_score = EXCLUDED.liquidity_score
                    """,
                    (s["etf_id"], calc_date, s["liquidity_score"]),
                )
                written += 1

        conn.commit()
    return written


def register_etf_factors(conn) -> int:
    """注册 ETF 因子定义到 factor_definitions 表。"""
    written = 0
    with conn.cursor() as cur:
        for f in FACTOR_DEFINITIONS:
            cur.execute(
                """
                INSERT INTO factor_definitions
                    (factor_key, name, category, sub_category, formula_desc, data_source, frequency)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (factor_key) DO UPDATE SET
                    name = EXCLUDED.name,
                    formula_desc = EXCLUDED.formula_desc,
                    data_source = EXCLUDED.data_source,
                    sub_category = EXCLUDED.sub_category,
                    version = factor_definitions.version + 1
                """,
                (f["factor_key"], f["name"], f["category"], f["sub_category"],
                 f["formula_desc"], f["data_source"], f["frequency"]),
            )
            written += 1
        conn.commit()
    logger.info(f"ETF因子注册完成: {written} 个")
    return written


def run_etf_factor_calc(days: int = 20) -> dict:
    """
    运行 ETF 因子计算全流程：
    1. 注册因子定义
    2. 计算当日溢价率/IOPV差值/绝对溢价率
    3. 计算流动性评分
    4. 写入 etf_factor_values
    """
    import time
    result = {"steps": {}, "records": 0}
    today = date.today()

    conn = psycopg2.connect(pg.uri)
    try:
        t0 = time.time()
        register_etf_factors(conn)
        result["steps"]["register"] = {"elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        premia = calc_premium_rate(conn, today)
        result["steps"]["premium"] = {"etfs": len(premia), "elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        liq_scores = calc_liquidity_score(conn, today, lookback_days=days)
        result["steps"]["liquidity"] = {"etfs": len(liq_scores), "elapsed_s": round(time.time() - t0, 2)}

        t0 = time.time()
        written = save_etf_factors(conn, today, premia, liq_scores)
        result["steps"]["save"] = {"records": written, "elapsed_s": round(time.time() - t0, 2)}
        result["records"] = written

        return result
    finally:
        conn.close()
