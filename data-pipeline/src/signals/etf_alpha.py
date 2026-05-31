import json
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)

ETF_DEFAULT_WEIGHTS = [
    {"factor_key": "premium_rate",  "category": "value",     "weight": 0.15, "norm_direction": -1},
    {"factor_key": "iopv_diff",     "category": "value",     "weight": 0.10, "norm_direction": -1},
    {"factor_key": "abs_premium",   "category": "value",     "weight": 0.08, "norm_direction": -1},
    {"factor_key": "turnover_rate", "category": "liquidity",  "weight": 0.12, "norm_direction":  1},
    {"factor_key": "volume_ma5",    "category": "liquidity",  "weight": 0.10, "norm_direction":  1},
    {"factor_key": "amount_ma5",    "category": "liquidity",  "weight": 0.08, "norm_direction":  1},
    {"factor_key": "momentum_5d",   "category": "momentum",   "weight": 0.10, "norm_direction":  1},
    {"factor_key": "momentum_20d",  "category": "momentum",   "weight": 0.08, "norm_direction":  1},
    {"factor_key": "volatility_20d","category": "volatility", "weight": 0.06, "norm_direction": -1},
    {"factor_key": "amplitude_5d", "category": "volatility", "weight": 0.05, "norm_direction": -1},
    {"factor_key": "main_net_flow", "category": "money_flow", "weight": 0.08, "norm_direction":  1},
]

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
            "SELECT eq.etf_id, eq.trade_date, eq.close_price, eq.premium_rate, eq.iopv, "
            "eq.turnover_rate, eq.volume, eq.amount, eq.change_pct, eq.amplitude "
            "FROM etf_quotes eq ORDER BY eq.etf_id, eq.trade_date DESC"
        )
        cols = [desc[0] for desc in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        if df.empty:
            return pd.DataFrame()
        # 按 etf_id 取最新一条，并转float
        df = df.groupby("etf_id").first().reset_index()
        for col in ["close_price","premium_rate","iopv","turnover_rate","volume","amount","change_pct","amplitude"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

def compute_etf_indicators(df):
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
        mom5 = (float(close.iloc[-1]) / float(close.iloc[-6])) - 1 if len(close) >= 6 else None
        mom20 = (float(close.iloc[-1]) / float(close.iloc[-21])) - 1 if len(close) >= 21 else None
        vol20 = close.pct_change().iloc[-20:].std() if len(close) >= 20 else None
        amp5 = g["amplitude"].iloc[-5:].mean() if len(g) >= 5 else None
        iopv = pd.to_numeric(g["iopv"], errors="coerce").iloc[-1]
        close_price = float(close.iloc[-1])
        iopv_diff = (close_price - iopv) / iopv if (iopv and iopv != 0) else None
        premium = g["premium_rate"].iloc[-1]
        vol_ma5 = vol.iloc[-5:].mean() if len(vol) >= 5 else (vol.mean() if len(vol) > 0 else None)
        amt_ma5 = amount.iloc[-5:].mean() if len(amount) >= 5 else (amount.mean() if len(amount) > 0 else None)
        frames[etf_id] = {
            "momentum_5d": mom5, "momentum_20d": mom20,
            "volatility_20d": vol20, "amplitude_5d": amp5,
            "iopv_diff": iopv_diff, "premium_rate": premium,
            "volume_ma5": vol_ma5, "amount_ma5": amt_ma5,
        }
    return pd.DataFrame.from_dict(frames, orient="index")

def percentile_rank(values):
    if not values:
        return []
    sr = pd.Series(values, dtype=float)
    ranks = sr.rank(pct=True, ascending=True, method="average")
    return ranks.fillna(50).tolist()

def normalize(raw_values, direction):
    codes = list(raw_values.keys())
    vals = list(raw_values.values())
    if not vals or all(v is None for v in vals):
        return {c: 50.0 for c in codes}
    pct_ranks = percentile_rank(vals)
    if direction == -1:
        pct_ranks = [100.0 - p for p in pct_ranks]
    return {code: pct_ranks[i] for i, code in enumerate(codes)}

def compute_etf_alpha(conn, calc_date, lookback_days=60):
    result = {"date": str(calc_date), "signals": 0, "top_etfs": []}
    spot = get_etf_spot_for_factor(conn, calc_date)  # 取每个ETF最新行情
    if spot.empty:
        logger.warning("%s has no ETF data", calc_date)
        return result
    etf_ids = spot["etf_id"].tolist()
    start = calc_date - timedelta(days=lookback_days)
    hist = get_etf_quotes_for_factor(conn, etf_ids, start, calc_date)
    indicators = compute_etf_indicators(hist) if not hist.empty else pd.DataFrame()
    spot = spot.set_index("etf_id")
    if not indicators.empty:
        indicators = indicators.add_prefix("ind_")
        combined = spot.join(indicators, how="left")
    else:
        combined = spot
    combined["iopv_diff"] = (combined["close_price"] - combined["iopv"]) / combined["iopv"].replace(0, np.nan)
    combined["iopv_diff"] = combined["iopv_diff"].where(combined["iopv_diff"].notna(), other=np.nan)
    combined["abs_premium"] = combined["premium_rate"].abs().fillna(0)
    categories = {}
    for w in ETF_DEFAULT_WEIGHTS:
        categories.setdefault(w["category"], []).append(w)
    etf_scores = {}
    for etf_id in combined.index:
        row = combined.loc[etf_id]
        factors = {}
        for w in ETF_DEFAULT_WEIGHTS:
            fk = w["factor_key"]
            # 优先用计算指标(ind_*)的值，没有则用实时字段
            val = None
            if "ind_" + fk in row.index:
                val = row["ind_" + fk]
            elif fk in row.index:
                val = row[fk]
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                factors[fk] = float(val)
        if not factors:
            continue
        cat_scores = {}
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, cat_ws in categories.items():
            cat_raw = {w["factor_key"]: factors[w["factor_key"]]
                       for w in cat_ws if w["factor_key"] in factors}
            if cat_raw:
                direction = cat_ws[0]["norm_direction"]
                normed = normalize(cat_raw, direction)
                cat_score = sum(normed[k] * w["weight"] for k, w in zip(cat_raw.keys(), cat_ws) if k in normed)
                total_weight += sum(w["weight"] for w in cat_ws)
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
    written = 0
    with conn.cursor() as cur:
        for e in etf_scores:
            comp = e["composite_score"]
            signal = 1 if comp > 25 else -1 if comp < -25 else 0
            reasons = []
            cs = e.get("cat_scores", {})
            if cs.get("value", 50) > 65:
                reasons.append("折价")
            if cs.get("liquidity", 50) > 65:
                reasons.append("高流动性")
            if cs.get("momentum", 50) > 65:
                reasons.append("动量强")
            if cs.get("money_flow", 50) > 65:
                reasons.append("资金净流入")
            reason = "|".join(reasons) if reasons else "综合评分"
            cur.execute(
                "INSERT INTO etf_alpha_signals "
                "(etf_id, calc_date, composite_score, signal, signal_reason, "
                "norm_value, norm_liquidity, norm_momentum, norm_volatility, norm_money_flow, score_rank) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (etf_id, calc_date) DO UPDATE SET "
                "composite_score=EXCLUDED.composite_score, signal=EXCLUDED.signal, "
                "signal_reason=EXCLUDED.signal_reason, norm_value=EXCLUDED.norm_value, "
                "norm_liquidity=EXCLUDED.norm_liquidity, norm_momentum=EXCLUDED.norm_momentum, "
                "norm_volatility=EXCLUDED.norm_volatility, norm_money_flow=EXCLUDED.norm_money_flow, "
                "score_rank=EXCLUDED.score_rank",
                (e["etf_id"], calc_date, comp, signal, reason,
                 cs.get("value"), cs.get("liquidity"), cs.get("momentum"),
                 cs.get("volatility"), cs.get("money_flow"), e["score_rank"]))
            written += 1
    conn.commit()
    return written

def get_etf_signals(conn, calc_date, n=20, signal_filter=None):
    with conn.cursor() as cur:
        query = (
            "SELECT a.score_rank, e.code, e.name, e.category, a.composite_score, "
            "a.signal, a.signal_reason, a.norm_value, a.norm_liquidity, a.norm_momentum "
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
                 "value_norm": round(float(r[7]), 2) if r[7] else None,
                 "liquidity_norm": round(float(r[8]), 2) if r[8] else None,
                 "momentum_norm": round(float(r[9]), 2) if r[9] else None}
                for r in cur.fetchall()]
