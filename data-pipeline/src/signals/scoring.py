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
from scipy.stats import rankdata

from src.config import pg

logger = logging.getLogger(__name__)

# Fundamental metrics whose raw values span wildly different scales.
# Each is percentile-ranked within the batch before scoring.
_FUNDAMENTAL_METRICS = ("roe", "roa", "gross_margin", "net_profit_margin")


def _normalize_fundamentals(records: list[dict]) -> None:
    """在批次内对 fundamental 指标做百分位排名，写入 record[fundamental_pct]。

    用 scipy.stats.rankdata 计算每个值在其同指标子集内的百分位排名 [0,100]，
    避免固定乘数 (v*4) 对不同量纲数据的扭曲——例如 ROE 20%→0.8、毛利率 50%→200。

    Modifies records in-place.
    """
    for key in _FUNDAMENTAL_METRICS:
        pairs: list[tuple[int, float]] = []  # (index, value)
        for idx, rec in enumerate(records):
            v = rec.get(key)
            if v is not None:
                try:
                    f = float(v)
                    if f == f:  # filter NaN
                        pairs.append((idx, f))
                except (TypeError, ValueError):
                    pass
        if len(pairs) < 2:
            # 不足 2 个有效值时统一给中性分 50
            for idx, _ in pairs:
                records[idx]["fundamental_pct"] = {
                    **records[idx].get("fundamental_pct", {}), key: 50.0,
                }
            continue
        indices, vals = zip(*pairs)
        ranks = rankdata(vals, method="average")
        percentiles = {i: (r / len(vals)) * 100.0 for i, r in zip(indices, ranks)}
        for idx, pct in percentiles.items():
            records[idx]["fundamental_pct"] = {
                **records[idx].get("fundamental_pct", {}), key: pct,
            }


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

FQIR_WEIGHTS = {
    "fundamental":  0.30,
    "quant":        0.25,
    "liquidity":    0.20,
    "information": 0.15,
    "risk":         0.10,
}


def compute_fqir_etf_score(conn, calc_date: date) -> dict:
    """
    计算 ETF FQIR 五维度聚合评分（核心函数）。
    从 etf_fundamental / etf_info / etf_risk 三张因子表读取分项，
    映射到 F/Q/L/I/R 五个维度后加权聚合，写入 etf_alpha_signals。
    """
    import pandas as pd
    from src.signals.etf_alpha import (
        get_etf_spot_for_factor, get_etf_fundamental_scores,
        get_etf_info_scores, get_etf_risk_scores,
        get_etf_quotes_for_factor, compute_etf_indicators,
        ETF_DEFAULT_WEIGHTS, normalize,
    )
    logger_etf = logging.getLogger("compute_fqir_etf_score")
    result = {"date": str(calc_date), "signals": 0, "top_etfs": [], "scores": {}}

    # Step 1: 基础行情
    spot = get_etf_spot_for_factor(conn, calc_date)
    if spot.empty:
        logger_etf.warning("%s has no ETF data", calc_date)
        return result
    etf_ids = spot["etf_id"].tolist()

    # Step 2: 三张因子表
    fund_df = get_etf_fundamental_scores(conn, calc_date)
    info_df = get_etf_info_scores(conn, calc_date)
    risk_df = get_etf_risk_scores(conn, calc_date)

    # Step 3: 技术因子（Q/L）
    hist = get_etf_quotes_for_factor(conn, etf_ids, calc_date - timedelta(days=60), calc_date)
    indicators = compute_etf_indicators(hist) if not hist.empty else pd.DataFrame()

    # Step 4: 合并（注意：indicators 已经是 etf_id 做索引，fund/info/risk_df 是普通 DataFrame）
    combined = spot.set_index("etf_id")
    for df, prefix in [(indicators, "ind_"), (fund_df, "fund_"),
                        (info_df, "info_"), (risk_df, "risk_")]:
        if not df.empty:
            # indicators: etf_id is already index
            # fund/info/risk: etf_id is a column, need to set_index
            df_local = df.copy()
            if "etf_id" in df_local.columns:
                df_local = df_local.set_index("etf_id")
            combined = combined.join(df_local.add_prefix(prefix), how="left")

    # category → FQIR dimension 映射
    cat_to_fqir = {
        "fundamental": "fundamental",
        "momentum":     "quant",
        "valuation":    "quant",
        "volatility":   "quant",
        "liquidity":    "liquidity",
        "money_flow":   "liquidity",
        "information":  "information",
        "risk":         "risk",
    }

    # Step 5: 计算每个 ETF 的 FQIR 维度分
    categories = {}
    for w in ETF_DEFAULT_WEIGHTS:
        categories.setdefault(w["category"], []).append(w)

    etf_scores = {}
    for etf_id in combined.index:
        row = combined.loc[etf_id]

        # 收集因子值
        factors = {}
        for w in ETF_DEFAULT_WEIGHTS:
            for prefix in ("ind_", "fund_", "info_", "risk_", ""):
                col = prefix + w["factor_key"]
                if col in row.index:
                    v = row[col]
                    if v is not None and not (isinstance(v, float) and pd.isna(v)):
                        factors[w["factor_key"]] = float(v)
                        break

        if not factors:
            continue

        # 每个 category 的 cat_score（0-100 均值，排除缺失因子）
        cat_scores = {}
        for cat, cat_ws in categories.items():
            cat_raw = {w["factor_key"]: factors[w["factor_key"]]
                       for w in cat_ws if w["factor_key"] in factors}
            if cat_raw:
                normed = normalize(cat_raw, cat_ws[0]["norm_direction"])
                total_cat_weight = sum(w["weight"] for w in cat_ws if w["factor_key"] in cat_raw)
                cat_score = sum(normed[k] * w["weight"]
                                for k in cat_raw for w in cat_ws if w["factor_key"] == k)
                cat_score = cat_score / total_cat_weight if total_cat_weight > 0 else 50.0
            else:
                cat_score = 50.0
            cat_scores[cat] = cat_score

        # 映射到 FQIR 维度（取各 source category 的均值）
        fqir_sources = {
            "fundamental": ["fundamental"],
            "quant":       ["momentum", "valuation", "volatility"],
            "liquidity":  ["liquidity", "money_flow"],
            "information": ["information"],
            "risk":       ["risk"],
        }
        fqir_dim_scores = {d: sum(cat_scores.get(c, 50.0) for c in src) / len(src)
                           for d, src in fqir_sources.items()}

        # FQIR 加权聚合
        raw_score = sum(fqir_dim_scores[d] * FQIR_WEIGHTS[d] for d in FQIR_WEIGHTS)
        composite = (raw_score - 50) * 2

        etf_scores[etf_id] = {
            "fundamental": round(fqir_dim_scores["fundamental"], 4),
            "quant":       round(fqir_dim_scores["quant"],       4),
            "liquidity":   round(fqir_dim_scores["liquidity"],   4),
            "information": round(fqir_dim_scores["information"], 4),
            "risk":        round(fqir_dim_scores["risk"],        4),
            "composite":   round(composite, 4),
        }

    # Step 6: 写入 DB + 排序
    sorted_etfs = sorted(etf_scores.items(),
                         key=lambda x: x[1]["composite"], reverse=True)
    with conn.cursor() as cur:
        for rank, (etf_id, scores) in enumerate(sorted_etfs, 1):
            comp = scores["composite"]
            signal = 1 if comp > 25 else -1 if comp < -25 else 0
            reasons = []
            if scores["fundamental"] > 65: reasons.append("基本面优")
            if scores["liquidity"]   > 65: reasons.append("高流动性")
            if scores["quant"]       > 65: reasons.append("动量强")
            if scores["information"] > 65: reasons.append("信息热度高")
            if scores["risk"]        < 35: reasons.append("低风险")
            reason = "|".join(reasons) if reasons else "综合评分"

            cur.execute(
                """INSERT INTO etf_alpha_signals
                (etf_id, calc_date, composite_score, signal, signal_reason, score_rank,
                 fundamental_score, quant_score, liquidity_score, info_score, risk_score)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (etf_id, calc_date) DO UPDATE SET
                composite_score=EXCLUDED.composite_score, signal=EXCLUDED.signal,
                signal_reason=EXCLUDED.signal_reason, score_rank=EXCLUDED.score_rank,
                fundamental_score=EXCLUDED.fundamental_score, quant_score=EXCLUDED.quant_score,
                liquidity_score=EXCLUDED.liquidity_score, info_score=EXCLUDED.info_score,
                risk_score=EXCLUDED.risk_score""",
                (etf_id, calc_date, comp, signal, reason, rank,
                 scores["fundamental"], scores["quant"],
                 scores["liquidity"], scores["information"], scores["risk"])
            )
    conn.commit()

    result["signals"] = len(etf_scores)
    result["scores"] = etf_scores
    result["top_etfs"] = [
        {"rank": i+1, "etf_id": eid, "score": round(s["composite"], 2)}
        for i, (eid, s) in enumerate(sorted_etfs[:10])
    ]
    return result


DEFAULT_FILTERS = {
    # FIXME: 数据完备后恢复 min_composite=60.0, max_risk=40.0（当前为临时宽松值）
    "min_composite":   0.0,    # 综合评分 ≥ 0（临时宽松值，待数据完备后调整为 60）
    "min_amount":    5_000_000, # 日均成交额 ≥ 500万
    "max_risk":       60.0,   # 风险评分 ≤ 60（临时宽松值，待数据完备后调整为 40）
}


def filter_candidate_pool(conn, calc_date: date,
                          filters: dict | None = None,
                          top_n: int = 20) -> list[dict]:
    """筛选 Top ETF 候选池（默认：score≥65，成交额≥500万，风险≤40）"""
    flt = {**DEFAULT_FILTERS, **(filters or {})}
    with conn.cursor() as cur:
        # 成交额用 spot（当日最新行情，已经按 etf_id 取了一条）
        cur.execute(
            """SELECT
                a.score_rank, e.id AS etf_id, e.code, e.name, e.category,
                a.composite_score, a.signal_reason,
                a.fundamental_score, a.quant_score,
                a.liquidity_score, a.info_score, a.risk_score,
                s.amount
            FROM etf_alpha_signals a
            JOIN etfs e ON e.id = a.etf_id
            LEFT JOIN LATERAL (
                SELECT eq.amount FROM etf_quotes eq
                WHERE eq.etf_id = e.id AND eq.trade_date <= %s
                ORDER BY eq.trade_date DESC LIMIT 1
            ) s ON true
            WHERE a.calc_date = %s
              AND a.composite_score >= %s
            ORDER BY a.composite_score DESC
            LIMIT 200""",
            (calc_date, calc_date, flt["min_composite"])
        )
        rows = cur.fetchall()

    candidates = []
    for r in rows:
        amount = float(r[12]) if r[12] is not None else 0.0
        risk = float(r[11]) if r[11] is not None else 100.0
        if amount < flt["min_amount"]:
            continue
        if risk > flt["max_risk"]:
            continue
        candidates.append({
            "rank":            r[0],
            "etf_id":          r[1],
            "code":            r[2],
            "name":            r[3],
            "category":        r[4],
            "composite_score": round(float(r[5]), 2),
            "signal_reason":   r[6],
            "fundamental": round(float(r[7]), 2)  if r[7] is not None else None,
            "quant":      round(float(r[8]), 2)   if r[8] is not None else None,
            "liquidity":  round(float(r[9]), 2)   if r[9] is not None else None,
            "information":round(float(r[10]), 2)  if r[10] is not None else None,
            "risk":       round(float(r[11]), 2)  if r[11] is not None else None,
            "amount_ma5": round(amount, 0),
        })
        if len(candidates) >= top_n:
            break

    for i, c in enumerate(candidates, 1):
        c["rank"] = i
    return candidates

def fetch_stock_factor_matrix(conn, calc_date: date) -> list[dict]:
    """拉取所有股票的因子值矩阵。"""
    start_60 = calc_date - timedelta(days=65)
    start_5  = calc_date - timedelta(days=10)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH mom AS (
                SELECT
                    ce.company_id,
                    (ld.close_price / NULLIF(e5.close_price, 0)) - 1 AS mom_5d,
                    (ld.close_price / NULLIF(e20.close_price, 0)) - 1 AS mom_20d,
                    (ld.close_price / NULLIF(e60.close_price, 0)) - 1 AS mom_60d
                FROM (
                    SELECT
                        company_id,
                        MIN(trade_date) FILTER(WHERE trade_date >= %s) AS earliest_5d_date,
                        MIN(trade_date) FILTER(WHERE trade_date >= %s) AS earliest_20d_date,
                        MIN(trade_date) FILTER(WHERE trade_date >= %s) AS earliest_60d_date,
                        MAX(trade_date) AS latest_date
                    FROM daily_quotes
                    WHERE trade_date BETWEEN %s AND %s
                    GROUP BY company_id
                ) ce
                LEFT JOIN daily_quotes ld ON ld.company_id = ce.company_id AND ld.trade_date = ce.latest_date
                LEFT JOIN daily_quotes e5 ON e5.company_id = ce.company_id AND e5.trade_date = ce.earliest_5d_date
                LEFT JOIN daily_quotes e20 ON e20.company_id = ce.company_id AND e20.trade_date = ce.earliest_20d_date
                LEFT JOIN daily_quotes e60 ON e60.company_id = ce.company_id AND e60.trade_date = ce.earliest_60d_date
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
                       COALESCE(SUM(fbd.amount) FILTER(WHERE fbd.deal_nature LIKE '%%买盘%%'), 0) -
                       COALESCE(SUM(fbd.amount) FILTER(WHERE fbd.deal_nature LIKE '%%卖盘%%'), 0) AS main_net_flow
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
                f.roe, f.roa, f.gross_margin, f.net_profit_margin, f.debt_ratio, f.eps_growth
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
            (
            # === mom (5) ===
            calc_date - timedelta(days=5),          # earliest_5d_date >=
            calc_date - timedelta(days=20),          # earliest_20d_date >=
            start_60,                                  # earliest_60d_date >=
            start_60, calc_date,                      # WHERE BETWEEN
            # === trend (9) = close(1) + ma5/20/60(6) + WHERE(2)
            calc_date,                                            # close_now = calc_date
            calc_date - timedelta(days=5), calc_date,            # ma5 BETWEEN
            calc_date - timedelta(days=20), calc_date,          # ma20 BETWEEN
            start_60, calc_date,                                  # ma60 BETWEEN
            start_60, calc_date,                                  # trend WHERE BETWEEN
            # === vol (6) = avg+std(4) + WHERE(2)
            calc_date - timedelta(days=20), calc_date,           # avg_volatility BETWEEN
            calc_date - timedelta(days=20), calc_date,           # std_volatility BETWEEN
            calc_date - timedelta(days=20), calc_date,           # vol WHERE BETWEEN
            # === liq (4) = turnover(2) + WHERE(2)
            start_5, calc_date,                                   # turnover_rate BETWEEN
            start_5, calc_date,                                   # liq WHERE BETWEEN
            # === mf (2) = WHERE(2)
            start_5, calc_date,                                   # mf WHERE BETWEEN
            # fundy: no date filter (uses latest available)
            )
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
                "net_profit_margin": row[17], "debt_ratio": row[18], "eps_growth": row[19],
            }
            for row in cur.fetchall()
        ]


def fetch_etf_factor_matrix(conn, calc_date: date) -> list[dict]:
    """拉取所有ETF的因子值矩阵。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH etf_mom AS (
                SELECT
                    ce.etf_id,
                    (ld.close_price / NULLIF(e5.close_price, 0)) - 1 AS mom_5d,
                    (ld.close_price / NULLIF(e20.close_price, 0)) - 1 AS mom_20d
                FROM (
                    SELECT
                        etf_id,
                        MIN(trade_date) FILTER(WHERE trade_date >= %s) AS earliest_5d_date,
                        MIN(trade_date) FILTER(WHERE trade_date >= %s) AS earliest_20d_date,
                        MAX(trade_date) AS latest_date
                    FROM etf_quotes
                    WHERE trade_date BETWEEN %s AND %s
                      AND source = 'akshare-hist'
                    GROUP BY etf_id
                ) ce
                LEFT JOIN etf_quotes ld ON ld.etf_id = ce.etf_id AND ld.trade_date = ce.latest_date
                LEFT JOIN etf_quotes e5 ON e5.etf_id = ce.etf_id AND e5.trade_date = ce.earliest_5d_date
                LEFT JOIN etf_quotes e20 ON e20.etf_id = ce.etf_id AND e20.trade_date = ce.earliest_20d_date
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
            (calc_date - timedelta(days=5),          # earliest_5d_date >=
             calc_date - timedelta(days=20),          # earliest_20d_date >=
             calc_date - timedelta(days=25), calc_date,  # WHERE BETWEEN
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

    def _f(v):
        """将任何数值转为 float，None→None，NaN→None"""
        if v is None:
            return None
        try:
            f = float(v)
            return None if f != f else f  # filter NaN
        except (TypeError, ValueError):
            return None

    # 质量维度 — 百分位排名（已在批次级归一化），均值聚合
    pctls = record.get("fundamental_pct", {})
    for key in _FUNDAMENTAL_METRICS:
        pct = pctls.get(key)  # [0, 100] from batch-level percentile rank
        if pct is not None:
            scores["fundamental"] = scores.get("fundamental", 0) + pct / 4.0
    scores["fundamental"] = scores.get("fundamental", 0)

    # 成长维度
    eg = _f(record.get("eps_growth"))
    if eg is not None:
        scores["growth"] = max(0, min(100, (eg + 50) / 1.5))

    # 动量维度
    mom_vals = [_f(v) for v in [record.get("mom_5d"), record.get("mom_20d"), record.get("mom_60d")]
                if _f(v) is not None]
    if mom_vals:
        avg_mom = sum(mom_vals) / len(mom_vals)
        scores["momentum"] = max(0, min(100, 50 + avg_mom * 8))

    # 趋势维度（MA多头排列）
    ma5, ma20, ma60 = _f(record.get("ma5")), _f(record.get("ma20")), _f(record.get("ma60"))
    if all(v is not None for v in [ma5, ma20, ma60]):
        ts = 0
        if ma5 > ma20: ts += 33
        if ma20 > ma60: ts += 33
        if ma5 > ma60: ts += 34
        scores["trend"] = ts
    elif ma5 is not None and ma20 is not None:
        scores["trend"] = 100 if ma5 > ma20 else 0

    # 波动维度（低波动 → 高分）
    vol = _f(record.get("avg_volatility") or record.get("std_volatility"))
    if vol is not None:
        scores["risk"] = max(0, min(100, 55 - abs(vol) * 8))

    # 流动性维度
    tr = _f(record.get("turnover_rate"))
    if tr is not None:
        scores["liquidity"] = max(0, min(100, tr * 4))

    # 主力资金维度
    mf = _f(record.get("main_net_flow"))
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

        # 百分位排名归一化 fundamental 指标（批次内，避免固定乘数扭曲量纲）
        _normalize_fundamentals(stock_records)

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
