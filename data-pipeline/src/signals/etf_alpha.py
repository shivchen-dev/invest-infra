import json
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)

# ==============================================================
# FQIR-ETF 因子权重表（20 因子 / 5 维度）
# ==============================================================
# 维度权重：
#   Fundamental  30%（行业景气/成分股盈利/集中度/换仓频率/指数编制质量）
#   Quant        25%（动量/估值分位/波动率/最大回撤/回测稳定性）
#   Liquidity    20%（成交额/资金流入/换手率/买卖价差）
#   Information  15%（新闻热度/政策支持/舆情/研报覆盖）
#   Risk         10%（政策风险/财务恶化/波动率异常/流动性风险）
# ==============================================================

ETF_DEFAULT_WEIGHTS = [
    # === Fundamental (30分) ===
    {"factor_key": "index_logic_score",      "category": "fundamental", "weight": 0.078, "norm_direction":  1},
    {"factor_key": "industry_sentiment",     "category": "fundamental", "weight": 0.078, "norm_direction":  1},
    {"factor_key": "component_roe",           "category": "fundamental", "weight": 0.059, "norm_direction":  1},
    {"factor_key": "component_concentration", "category": "fundamental", "weight": 0.039, "norm_direction": -1},
    {"factor_key": "rebalance_freq",         "category": "fundamental", "weight": 0.039, "norm_direction": -1},
    # === Quant (25分) ===
    {"factor_key": "momentum_5d",            "category": "momentum",    "weight": 0.049, "norm_direction":  1},
    {"factor_key": "momentum_20d",           "category": "momentum",    "weight": 0.049, "norm_direction":  1},
    {"factor_key": "momentum_60d",           "category": "momentum",    "weight": 0.029, "norm_direction":  1},
    {"factor_key": "pe_percentile",           "category": "valuation",   "weight": 0.059, "norm_direction": -1},
    {"factor_key": "hv_20d",                 "category": "volatility",  "weight": 0.029, "norm_direction": -1},
    {"factor_key": "max_drawdown",            "category": "risk",        "weight": 0.020, "norm_direction": -1},
    {"factor_key": "backtest_stability",    "category": "momentum",   "weight": 0.010, "norm_direction":  1},
    # === Liquidity (20分) ===
    {"factor_key": "amount_ma5",             "category": "liquidity",   "weight": 0.078, "norm_direction":  1},
    {"factor_key": "main_net_flow",          "category": "money_flow",  "weight": 0.059, "norm_direction":  1},
    {"factor_key": "turnover_rate",          "category": "liquidity",   "weight": 0.039, "norm_direction":  1},
    {"factor_key": "bid_ask_spread",         "category": "liquidity",   "weight": 0.020, "norm_direction": -1},
    # === Information (15分) ===
    {"factor_key": "news_sentiment",         "category": "information", "weight": 0.049, "norm_direction":  1},
    {"factor_key": "policy_support",        "category": "information", "weight": 0.039, "norm_direction":  1},
    {"factor_key": "social_sentiment",       "category": "information", "weight": 0.029, "norm_direction":  1},
    {"factor_key": "industry_info_score",   "category": "information", "weight": 0.049, "norm_direction":  1},
    # === Risk (10分) ===
    {"factor_key": "policy_risk",            "category": "risk",       "weight": 0.039, "norm_direction": -1},
    {"factor_key": "financial_deterioration","category": "risk",        "weight": 0.029, "norm_direction": -1},
    {"factor_key": "volatility_spike",        "category": "risk",        "weight": 0.020, "norm_direction": -1},
    {"factor_key": "liquidity_risk",          "category": "risk",        "weight": 0.010, "norm_direction": -1},
]

# ==============================================================
# 数据获取
# ==============================================================

def get_etf_quotes_for_factor(conn, etf_ids, start_date, end_date):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT eq.etf_id, eq.trade_date, eq.close_price, eq.volume, eq.amount, "
            "eq.turnover_rate, eq.premium_rate, eq.iopv, eq.change_pct, eq.amplitude "
            "FROM etf_quotes eq WHERE eq.etf_id = ANY(%s) AND eq.trade_date BETWEEN %s AND %s "
            "ORDER BY eq.etf_id, eq.trade_date",
            (etf_ids, start_date, end_date))
        cols = [desc[0] for desc in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)

def get_etf_spot_for_factor(conn, calc_date):
    """获取最新实时行情，按 etf_id 取最新一条记录"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT eq.etf_id, eq.trade_date, eq.close_price, eq.premium_rate, eq.iopv, """
            "eq.turnover_rate, eq.volume, eq.amount, eq.change_pct, eq.amplitude "
            "FROM etf_quotes eq "
            "WHERE eq.trade_date <= %s "
            "ORDER BY eq.etf_id, eq.trade_date DESC",
            (calc_date,))
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=cols)
        df = df.groupby("etf_id", sort=False).first().reset_index()
        for col in ["close_price","premium_rate","iopv","turnover_rate","volume","amount","change_pct","amplitude"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

def get_etf_fundamental_scores(conn, calc_date):
    """读取基本面因子（从 etf_fundamental_scores 表）"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT etf_id, industry_sentiment, component_roe, component_gross_margin,
                      cr5, cr10, rebalance_freq, index_quality_score
               FROM etf_fundamental_scores
               WHERE calc_date = %s""",
            (calc_date,))
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            "etf_id","industry_sentiment","component_roe","component_gross_margin",
            "cr5","cr10","rebalance_freq","index_quality_score"])

def get_etf_info_scores(conn, calc_date):
    """读取信息流因子（从 etf_info_scores 表）"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT etf_id, news_sentiment, news_count, policy_support,
                      social_sentiment, report_coverage, industry_info_score
               FROM etf_info_scores
               WHERE calc_date = %s""",
            (calc_date,))
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            "etf_id","news_sentiment","news_count","policy_support",
            "social_sentiment","report_coverage","industry_info_score"])

def get_etf_risk_scores(conn, calc_date):
    """读取风险因子（从 etf_risk_scores 表）"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT etf_id, policy_risk, financial_deterioration,
                      volatility_spike, liquidity_risk, max_drawdown
               FROM etf_risk_scores
               WHERE calc_date = %s""",
            (calc_date,))
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=[
            "etf_id","policy_risk","financial_deterioration",
            "volatility_spike","liquidity_risk","max_drawdown"])

# ==============================================================
# 因子计算
# ==============================================================

def _compute_max_drawdown(prices: pd.Series) -> float:
    """计算最大回撤（0-1）"""
    if len(prices) < 2:
        return 0.0
    peak = prices.cummax()
    drawdown = (prices - peak) / peak
    return abs(drawdown.min())

def _compute_backtest_stability(mom5, mom20, mom60) -> float:
    """计算多周期动量一致性（0-100）"""
    # 三个周期方向一致得高分
    score = 0
    if mom5 is not None and mom20 is not None:
        if (mom5 > 0) == (mom20 > 0):
            score += 33
    if mom20 is not None and mom60 is not None:
        if (mom20 > 0) == (mom60 > 0):
            score += 33
    if mom5 is not None and mom60 is not None:
        if (mom5 > 0) == (mom60 > 0):
            score += 34
    return score

def compute_etf_indicators(df):
    """
    从行情历史 DataFrame 计算技术因子。
    支持因子（部分需要外部表补充）：
      - momentum_5d / momentum_20d / momentum_60d
      - hv_20d（历史波动率）
      - max_drawdown
      - backtest_stability
      - iopv_diff / premium_rate / volume_ma5 / amount_ma5
    """
    if df.empty:
        return pd.DataFrame()
    grp = df.sort_values("trade_date").groupby("etf_id")
    frames = {}
    for etf_id, g in grp:
        close = pd.to_numeric(g["close_price"], errors="coerce").dropna()
        vol = pd.to_numeric(g["volume"], errors="coerce").dropna()
        amount = pd.to_numeric(g["amount"], errors="coerce").dropna()
        if len(close) < 2:
            continue
        # 动量
        mom5 = (float(close.iloc[-1]) / float(close.iloc[-6])) - 1 if len(close) >= 6 else None
        mom20 = (float(close.iloc[-1]) / float(close.iloc[-21])) - 1 if len(close) >= 21 else None
        mom60 = (float(close.iloc[-1]) / float(close.iloc[-61])) - 1 if len(close) >= 61 else None
        # 波动率
        vol20 = close.pct_change().iloc[-20:].std() if len(close) >= 20 else None
        # 最大回撤
        max_dd = _compute_max_drawdown(close) if len(close) >= 20 else 0.0
        # 回测稳定性
        stability = _compute_backtest_stability(mom5, mom20, mom60)
        # 其他
        amp5 = g["amplitude"].iloc[-5:].mean() if len(g) >= 5 else None
        iopv = pd.to_numeric(g["iopv"], errors="coerce").iloc[-1]
        close_price = float(close.iloc[-1])
        iopv_diff = (close_price - iopv) / iopv if (iopv and iopv != 0) else None
        premium = g["premium_rate"].iloc[-1]
        vol_ma5 = vol.iloc[-5:].mean() if len(vol) >= 5 else (vol.mean() if len(vol) > 0 else None)
        amt_ma5 = amount.iloc[-5:].mean() if len(amount) >= 5 else (amount.mean() if len(amount) > 0 else None)
        # 买卖价差：用 amplitude 代理（amplitude 越大买卖价差越大）
        bid_ask = amp5  # 已归约到 0~100 范围

        frames[etf_id] = {
            "momentum_5d": mom5,
            "momentum_20d": mom20,
            "momentum_60d": mom60,
            "hv_20d": vol20,
            "max_drawdown": max_dd,
            "backtest_stability": stability,
            "iopv_diff": iopv_diff,
            "premium_rate": premium,
            "volume_ma5": vol_ma5,
            "amount_ma5": amt_ma5,
            "bid_ask_spread": bid_ask,
        }
    return pd.DataFrame.from_dict(frames, orient="index")

def percentile_rank(values):
    """"横跨全市场 ETF 的 percentile rank (0-100)"""
    if not values:
        return []
    sr = pd.Series(values, dtype=float)
    ranks = sr.rank(pct=True, ascending=True, method="average")
    return ranks.fillna(50).tolist()

def _zscore_norm(raw_values, direction):
    """
    Z-score 标准化：z = (x - mean) / std
    direction=1: 值越大分数越高
    direction=-1: 值越大分数越低（越贵/越差）
    结果以 50 为中心，±1 std ≈ ±1 个等级差
    """
    codes = list(raw_values.keys())
    vals = list(raw_values.values())
    if not vals or all(v is None for v in vals):
        return {c: 50.0 for c in codes}
    numeric_vals = [float(v) for v in vals if v is not None]
    if not numeric_vals:
        return {c: 50.0 for c in codes}
    mean = sum(numeric_vals) / len(numeric_vals)
    variance = sum((v - mean) ** 2 for v in numeric_vals) / len(numeric_vals)
    std = variance ** 0.5
    if std == 0:
        std = 1.0
    results = {}
    for c in codes:
        v = raw_values[c]
        if v is None:
            results[c] = 50.0
            continue
        z = (float(v) - mean) / std
        if direction == -1:
            z = -z
        # z ∈ [-3, +3] → scale to [0, 100], centered at 50
        score = 50.0 + z * 10.0
        results[c] = max(0.0, min(100.0, score))
    return results

def _min_max_norm(raw_values, direction):
    """
    基于全市场分布的 min-max 标准化（有 floor，防止单因子导致极端分）。
    direction=1: 值越大分数越高
    direction=-1: 值越大分数越低（越贵/越差）
    """
    codes = list(raw_values.keys())
    vals = list(raw_values.values())
    if not vals or all(v is None for v in vals):
        return {c: 50.0 for c in codes}
    numeric_vals = [float(v) for v in vals if v is not None]
    if not numeric_vals:
        return {c: 50.0 for c in codes}
    vmin, vmax = min(numeric_vals), max(numeric_vals)
    results = {}
    for c in codes:
        v = raw_values[c]
        if v is None:
            results[c] = 50.0
            continue
        if vmin == vmax:
            results[c] = 50.0
        else:
            if direction == -1:
                results[c] = 100.0 - (float(v) - vmin) / (vmax - vmin) * 100.0
            else:
                results[c] = (float(v) - vmin) / (vmax - vmin) * 100.0
        results[c] = max(20.0, min(90.0, results[c]))  # 收紧 floor
    return results

def normalize(raw_values, direction):
    # 优先用 z-score（有自我中心化优点），回退 min-max
    try:
        return _zscore_norm(raw_values, direction)
    except (TypeError, ValueError) as e:
        import logging
        logging.getLogger(__name__).warning("zscore_norm failed (%s), falling back to min-max", e)
        return _min_max_norm(raw_values, direction)

# ==============================================================
# 主入口
# ==============================================================

def compute_etf_alpha(conn, calc_date, lookback_days=60):
    """
    计算 ETF FQIR 综合评分（20 因子 / 5 维度）。
    因子来源优先级：
      1. compute_etf_indicators() 计算的技术因子
      2. etf_fundamental_scores 表（行业景气/成分股盈利/集中度）
      3. etf_info_scores 表（新闻/政策/舆情/研报）
      4. etf_risk_scores 表（政策风险/财务恶化/波动率异常）
      5. 实时行情字段（premium_rate / turnover_rate / volume / amount）
    """
    result = {"date": str(calc_date), "signals": 0, "top_etfs": []}
    spot = get_etf_spot_for_factor(conn, calc_date)
    if spot.empty:
        logger.warning("%s has no ETF data", calc_date)
        return result
    etf_ids = spot["etf_id"].tolist()
    start = calc_date - timedelta(days=lookback_days)
    hist = get_etf_quotes_for_factor(conn, etf_ids, start, calc_date)
    indicators = compute_etf_indicators(hist) if not hist.empty else pd.DataFrame()
    # 外部因子表
    fund_df = get_etf_fundamental_scores(conn, calc_date)
    info_df = get_etf_info_scores(conn, calc_date)
    risk_df = get_etf_risk_scores(conn, calc_date)
    # 合并
    spot = spot.set_index("etf_id")
    if not indicators.empty:
        indicators = indicators.add_prefix("ind_")
        combined = spot.join(indicators, how="left")
    else:
        combined = spot
    if not fund_df.empty:
        fund_df = fund_df.set_index("etf_id").add_prefix("fund_")
        combined = combined.join(fund_df, how="left")
    if not info_df.empty:
        info_df = info_df.set_index("etf_id").add_prefix("info_")
        combined = combined.join(info_df, how="left")
    if not risk_df.empty:
        risk_df = risk_df.set_index("etf_id").add_prefix("risk_")
        combined = combined.join(risk_df, how="left")
    combined["iopv_diff"] = np.where(combined["iopv"] != 0, (combined["close_price"] / combined["iopv"] - 1), np.nan)
    combined["abs_premium"] = combined["premium_rate"].abs().fillna(0)
    # 构建因子映射（factor_key → 列名，支持多前缀）
    categories = {}
    for w in ETF_DEFAULT_WEIGHTS:
        categories.setdefault(w["category"], []).append(w)
    etf_scores = {}
    for etf_id in combined.index:
        row = combined.loc[etf_id]
        factors = {}
        for w in ETF_DEFAULT_WEIGHTS:
            fk = w["factor_key"]
            # 尝试多个可能的前缀
            val = None
            for prefix in ("ind_", "fund_", "info_", "risk_", ""):
                col = prefix + fk
                if col in row.index:
                    v = row[col]
                    if v is not None and not (isinstance(v, float) and np.isnan(v)):
                        val = float(v)
                        break
            if val is not None:
                factors[fk] = val
        if not factors:
            continue
        cat_scores = {}
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, cat_ws in categories.items():
            cat_raw = {w["factor_key"]: factors[w["factor_key"]]
                       for w in cat_ws if w["factor_key"] in factors}
            cat_weight = sum(w["weight"] for w in cat_ws)
            if cat_raw:
                direction = cat_ws[0]["norm_direction"]
                normed = normalize(cat_raw, direction)
                # normed[k] 是 0-100，cat_score 是加权平均（scale 与 weight 同量纲）
                cat_score = sum(normed[k] * w["weight"] for k in cat_raw for w in cat_ws if w["factor_key"] == k and k in normed)
                total_weight += cat_weight
                weighted_sum += cat_score
            else:
                # 无数据维度 → 默认中性分 50（直接贡献 50，不再乘 cat_weight）
                cat_score = 50.0
                total_weight += cat_weight
                weighted_sum += cat_score
            cat_scores[cat] = cat_score
        if total_weight > 0:
            raw_score = weighted_sum / total_weight
            composite = (raw_score - 50) * 2
        else:
            composite = 0.0
        etf_scores[etf_id] = {"etf_id": etf_id, "cat_scores": cat_scores,
                              "composite_score": composite, "factors": factors}
    sorted_etfs = sorted(etf_scores.values(), key=lambda x: x["composite_score"], reverse=True)
    for rank, e in enumerate(sorted_etfs, 1):
        e["score_rank"] = rank
    written = _write_etf_signals(conn, calc_date, sorted_etfs)
    result["signals"] = written
    result["top_etfs"] = [{"rank": e["score_rank"], "etf_id": e["etf_id"],
                            "score": round(e["composite_score"], 2)}
                           for e in sorted_etfs[:10]]
    return result

def _write_etf_signals(conn, calc_date, etf_scores):
    """写入 etf_alpha_signals（兼容扩展字段）"""
    written = 0
    with conn.cursor() as cur:
        for e in etf_scores:
            comp = e["composite_score"]
            signal = 1 if comp > 25 else -1 if comp < -25 else 0  # 当前阈值：±25
            reasons = []
            cs = e.get("cat_scores", {})
            if cs.get("fundamental", 50) > 65:
                reasons.append("基本面优")
            if cs.get("value", 50) > 65:
                reasons.append("折价")
            if cs.get("liquidity", 50) > 65:
                reasons.append("高流动性")
            if cs.get("momentum", 50) > 65:
                reasons.append("动量强")
            if cs.get("money_flow", 50) > 65:
                reasons.append("资金净流入")
            if cs.get("information", 50) > 65:
                reasons.append("信息热度高")
            if cs.get("risk", 50) < 35:
                reasons.append("低风险")
            reason = "|".join(reasons) if reasons else "综合评分"
            cur.execute(
                "INSERT INTO etf_alpha_signals "
                "(etf_id, calc_date, composite_score, signal, signal_reason, "
                "norm_value, norm_liquidity, norm_momentum, norm_volatility, norm_money_flow, score_rank, "
                "fundamental_score, quant_score, liquidity_score, info_score, risk_score) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (etf_id, calc_date) DO UPDATE SET "
                "composite_score=EXCLUDED.composite_score, signal=EXCLUDED.signal, "
                "signal_reason=EXCLUDED.signal_reason, norm_value=EXCLUDED.norm_value, "
                "norm_liquidity=EXCLUDED.norm_liquidity, norm_momentum=EXCLUDED.norm_momentum, "
                "norm_volatility=EXCLUDED.norm_volatility, norm_money_flow=EXCLUDED.norm_money_flow, "
                "score_rank=EXCLUDED.score_rank, "
                "fundamental_score=EXCLUDED.fundamental_score, quant_score=EXCLUDED.quant_score, "
                "liquidity_score=EXCLUDED.liquidity_score, info_score=EXCLUDED.info_score, "
                "risk_score=EXCLUDED.risk_score",
                (e["etf_id"], calc_date, comp, signal, reason,
                 cs.get("value"), cs.get("liquidity"), cs.get("momentum"),
                 cs.get("volatility"), cs.get("money_flow"), e["score_rank"],
                 cs.get("fundamental"), cs.get("quant"),
                 cs.get("liquidity"), cs.get("information"), cs.get("risk")))
            written += 1
    conn.commit()
    return written

def get_etf_signals(conn, calc_date, n=20, signal_filter=None):
    with conn.cursor() as cur:
        query = (
            "SELECT a.score_rank, e.code, e.name, e.category, a.composite_score, "
            "a.signal, a.signal_reason, a.norm_value, a.norm_liquidity, a.norm_momentum, "
            "a.fundamental_score, a.quant_score, a.liquidity_score, a.info_score, a.risk_score "
            "FROM etf_alpha_signals a JOIN etfs e ON a.etf_id = e.id "
            "WHERE a.calc_date = %s"
        )
        params = [calc_date]
        if signal_filter is not None:
            query += " AND a.signal = %s"
            params.append(signal_filter)
        query += " ORDER BY a.score_rank LIMIT %s"
        params.append(n)
        cur.execute(query, params)
        return [{"rank": r[0], "code": r[1], "name": r[2], "category": r[3],
                 "score": round(float(r[4]), 2), "signal": int(r[5]), "reason": r[6],
                 "fundamental": round(float(r[10]), 2) if r[10] else None,
                 "quant": round(float(r[11]), 2) if r[11] else None,
                 "liquidity": round(float(r[12]), 2) if r[12] else None,
                 "info": round(float(r[13]), 2) if r[13] else None,
                 "risk": round(float(r[14]), 2) if r[14] else None}
                for r in cur.fetchall()]