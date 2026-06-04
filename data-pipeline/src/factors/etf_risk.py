"""
factors/etf_risk.py — ETF 风险因子（R 维度）
============================================================

指标（共 4 个）：
  policy_risk            政策风险（30%权重）：监管/限制关键词命中
  financial_deterioration 财务恶化（25%权重）：行业成分股亏损占比
  volatility_spike      波动率异常（25%权重）：HV突增检测
  liquidity_risk        流动性风险（20%权重）：成交额萎缩 + 买卖价差

数据缺口策略：
  - 无成分股权重 → 等权计算成分股财务恶化
  - 无历史K线 → 用 amplitude_proxy 代理波动率异常
  - 无买卖价差 → bid_ask_spread 用 amplitude 代理

存储：写入 etf_risk_scores
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)

# 风险关键词
RISK_KEYWORDS = [
    "监管", "整改", "调查", "处罚", "警告", "风险", "违规", "违约",
    "退市", "ST", "戴帽", "暂停上市", "破产", "债务危机",
    "产能过剩", "出清", "淘汰", "限制出口", "安全风险", "泄露",
]
POLICY_HIT_KW = [
    "限制", "监管收紧", "规范", "整改", "清退", "淘汰落后",
    "防止无序扩张", "反垄断", "安全审查", "数据安全",
]


# ─── 政策风险 ──────────────────────────────────────────────────────────────

def _policy_risk_by_industry(conn, industry: str, lookback_days: int = 30) -> float:
    """
    政策风险（0-100，越高风险越大）：
    基于 news_articles 表，按行业统计风险关键词命中率和风险新闻比例。
    """
    if not industry:
        return 50.0  # 无行业信息，默认中性
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, content_summary, sentiment_label
                FROM news_articles na
                JOIN companies c ON c.id = na.company_id
                WHERE c.industry = %s
                  AND na.published_at >= NOW() - INTERVAL '%s days'
                """,
                (industry, lookback_days),
            )
            rows = cur.fetchall()
            if not rows:
                return 50.0

            total = len(rows)
            risk_hit = 0
            neg_count = sum(1 for r in rows if r[2] == "negative")

            for title, content, _ in rows:
                text = f"{title or ''} {content or ''}"
                for kw in RISK_KEYWORDS + POLICY_HIT_KW:
                    if kw in text:
                        risk_hit += 1
                        break  # 一条新闻只计1次

            # 风险得分 = 风险新闻比例 * 50 + 关键词命中率 * 50
            risk_ratio = risk_hit / max(1, total)
            neg_ratio = neg_count / max(1, total)
            score = risk_ratio * 50 + neg_ratio * 50
            return max(0.0, min(100.0, score))
    except Exception:
        return 50.0


# ─── 财务恶化 ──────────────────────────────────────────────────────────────

def _financial_deterioration(conn, industry: str) -> Optional[float]:
    """
    成分股财务恶化比例（0-100，越高表示行业财务越差）：
    基于 financial_reports 表，按行业统计 ROE 同比下降和亏损占比。
    """
    if not industry:
        return None
    try:
        with conn.cursor() as cur:
            # 获取行业公司最近两个报告期的 ROE
            cur.execute(
                """
                SELECT fr.value, fr.report_date
                FROM financial_reports fr
                JOIN companies c ON c.id = fr.company_id
                WHERE fr.report_type = 'annual'
                  AND fr.indicator = 'ROE'
                  AND c.industry = %s
                ORDER BY c.id, fr.report_date DESC
                LIMIT 200
                """,
                (industry,),
            )
            rows = cur.fetchall()
            if not rows or len(rows) < 4:
                return None

            # 按公司分组，取最近两期
            company_roes = {}
            for val, rdate in rows:
                idx = len(rows) - rows.index((val, rdate))  # 简化，用索引模拟
                pass

            # 简化：用 ROE 均值和负值比例估算
            roe_values = [float(r[0]) for r in rows if r[0] is not None]
            if not roe_values:
                return None
            neg_ratio = sum(1 for v in roe_values if v < 0) / len(roe_values)
            avg_roe = np.mean(roe_values)
            # ROE 均值越低、负值比例越高 → 财务恶化越严重
            # avg_roe ∈ [-20%, 30%] → 映射到 [0, 100]
            roe_score = (avg_roe + 20) / 50 * 50  # -20%→0, 30%→50
            deterioration = neg_ratio * 50 + (50 - roe_score)
            return max(0.0, min(100.0, deterioration))
    except Exception:
        return None


# ─── 波动率异常 ────────────────────────────────────────────────────────────

def _volatility_spike(conn, etf_id: int, lookback_days: int = 20) -> float:
    """
    波动率异常（0-100，越高表示波动越异常）：
    基于 etf_quotes 表，计算 HV20d 并与近 60 天均值比较。
    数据缺失时：用 amplitude 的变异系数代理（amplitude 越大波动越大）。
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT close_price, amplitude, amount
                FROM etf_quotes
                WHERE etf_id = %s
                  AND trade_date >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY trade_date DESC
                LIMIT 60
                """,
                (etf_id, lookback_days),
            )
            rows = cur.fetchall()
            if not rows or len(rows) < 10:
                return 50.0  # 数据不足，默认中性

            close_prices = [float(r[0]) for r in rows if r[0] is not None]
            amplitudes = [float(r[1]) for r in rows if r[1] is not None and not np.isnan(float(r[1]))]

            if len(close_prices) >= 20:
                # HV20d：最近20日收盘价收益率标准差 * sqrt(252)
                returns = np.diff(close_prices) / close_prices[:-1]
                hv_20 = np.std(returns[-20:]) * np.sqrt(252) if len(returns) >= 20 else 0
                hv_60_mean = np.std(returns) * np.sqrt(252) if len(returns) > 5 else 0
                if hv_60_mean > 0:
                    spike = hv_20 / hv_60_mean
                    # spike ∈ [0.5, 2.0] → 映射到 [0, 100]
                    score = (spike - 0.5) / 1.5 * 100
                    return max(0.0, min(100.0, score))
                return 50.0
            elif amplitudes:
                # 用 amplitude 变异系数代理（amplitude 波动越大 → 波动异常越大）
                amp_mean = np.mean(amplitudes)
                amp_std = np.std(amplitudes)
                if amp_mean > 0:
                    cv = amp_std / amp_mean  # 变异系数
                    # cv ∈ [0, 2] → 映射到 [0, 100]
                    score = min(100.0, cv * 50)
                    return max(0.0, score)
                return 50.0
            else:
                return 50.0
    except Exception:
        return 50.0


# ─── 流动性风险 ────────────────────────────────────────────────────────────

def _liquidity_risk(conn, etf_id: int, lookback_days: int = 20) -> float:
    """
    流动性风险（0-100，越高表示流动性越差）：
    基于成交额趋势和买卖价差代理：
    1. 近5日成交额 vs 近20日均值（萎缩比例）
    2. amplitude 代理买卖价差（amplitude 大 → 价差大 → 流动性差）
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT amount, amplitude, turnover_rate
                FROM etf_quotes
                WHERE etf_id = %s
                  AND trade_date >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY trade_date DESC
                LIMIT 30
                """,
                (etf_id, lookback_days),
            )
            rows = cur.fetchall()
            if not rows or len(rows) < 5:
                return 50.0

            amounts = [float(r[0]) for r in rows if r[0] is not None]
            amplitudes = [float(r[1]) for r in rows if r[1] is not None]

            # 成交额萎缩检测
            if len(amounts) >= 20:
                ma20 = np.mean(amounts[:20])
                ma5 = np.mean(amounts[:5])
                if ma20 > 0:
                    shrink_ratio = 1 - ma5 / ma20  # 萎缩比例
                    amount_risk = min(100.0, shrink_ratio * 200)  # 萎缩50%→100分
                else:
                    amount_risk = 50.0
            else:
                amount_risk = 50.0

            # amplitude 代理买卖价差
            if amplitudes:
                amp_mean = np.mean(amplitudes[:5])
                # amplitude ∈ [0, 10] → 价差风险 [0, 100]
                amp_risk = min(100.0, amp_mean * 10)
            else:
                amp_risk = 50.0

            # 综合：成交额风险 60% + 价差风险 40%
            score = amount_risk * 0.6 + amp_risk * 0.4
            return max(0.0, min(100.0, score))
    except Exception:
        return 50.0


# ─── 主入口 ────────────────────────────────────────────────────────────────

def compute_etf_risk(conn, calc_date: date, dry_run: bool = False) -> pd.DataFrame:
    """
    主入口：计算 ETF 风险因子（R 维度）
    """
    logger.info("[risk] 开始计算 R 维度因子 (date=%s)", calc_date)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, code, name, 跟踪指数 FROM etfs WHERE is_active = true"
        )
        etf_rows = cur.fetchall()

    if not etf_rows:
        logger.warning("[risk] 无活跃ETF")
        return pd.DataFrame()

    results = []
    for (etf_id, code, name, track_index) in etf_rows:
        row_result = {"etf_id": etf_id, "calc_date": calc_date}

        # 从跟踪指数提取行业
        industry = ""
        if track_index:
            industry = track_index.replace("指数", "").replace("沪深", "").replace("中证", "").replace("上证", "").strip()

        # ── policy_risk ──
        policy_risk = _policy_risk_by_industry(conn, industry)
        row_result["policy_risk"] = round(policy_risk, 2)

        # ── financial_deterioration ──
        fin_det = _financial_deterioration(conn, industry)
        row_result["financial_deterioration"] = round(fin_det, 2) if fin_det is not None else None

        # ── volatility_spike ──
        vol_spike = _volatility_spike(conn, etf_id)
        row_result["volatility_spike"] = round(vol_spike, 2)

        # ── liquidity_risk ──
        liq_risk = _liquidity_risk(conn, etf_id)
        row_result["liquidity_risk"] = round(liq_risk, 2)

        # ── max_drawdown（沿用 etf_alpha 的计算值，这里用行情计算）──
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT close_price FROM etf_quotes
                    WHERE etf_id = %s
                    ORDER BY trade_date DESC LIMIT 60
                    """,
                    (etf_id,)
                )
                prices = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
                if len(prices) >= 20:
                    peak = np.maximum.accumulate(prices)
                    dd = (np.array(prices) - peak) / peak
                    row_result["max_drawdown"] = round(abs(np.min(dd)), 4)
                else:
                    row_result["max_drawdown"] = None
        except Exception:
            row_result["max_drawdown"] = None

        results.append(row_result)

    df = pd.DataFrame(results)

    if not dry_run and not df.empty:
        _write_risk_scores(conn, df, calc_date)

    logger.info("[risk] 完成，计算 %d 只ETF风险因子", len(df))
    return df


def _write_risk_scores(conn, df: pd.DataFrame, calc_date: date):
    """写入 etf_risk_scores 表（ON CONFLICT UPDATE）"""
    if df.empty:
        return
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO etf_risk_scores
                  (etf_id, calc_date, policy_risk, financial_deterioration,
                   volatility_spike, liquidity_risk, max_drawdown)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                  policy_risk=EXCLUDED.policy_risk,
                  financial_deterioration=EXCLUDED.financial_deterioration,
                  volatility_spike=EXCLUDED.volatility_spike,
                  liquidity_risk=EXCLUDED.liquidity_risk,
                  max_drawdown=EXCLUDED.max_drawdown
                """,
                (row["etf_id"], calc_date,
                 row.get("policy_risk"), row.get("financial_deterioration"),
                 row.get("volatility_spike"), row.get("liquidity_risk"),
                 row.get("max_drawdown"))
            )
    conn.commit()
    logger.info("[risk] 已写入 %d 条记录到 etf_risk_scores", len(df))


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")
    os.environ.update({"PGPASSWORD": "REDACTED_PG_PASSWORD"})

    from src.config import pg
    conn = psycopg2.connect(pg.uri)
    calc_date = date.today()
    df = compute_etf_risk(conn, calc_date, dry_run=True)
    print(df.head(10).to_string())
    conn.close()