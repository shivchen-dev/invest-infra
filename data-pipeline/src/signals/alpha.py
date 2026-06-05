"""
多因子Alpha评分卡
"""

import json
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg

logger = logging.getLogger(__name__)


DEFAULT_WEIGHTS = [
    {"factor_key": "momentum_5d",   "category": "momentum",   "weight": 0.0673, "norm_direction":  1},
    {"factor_key": "momentum_20d",  "category": "momentum",   "weight": 0.0769, "norm_direction":  1},
    {"factor_key": "momentum_60d",  "category": "momentum",   "weight": 0.0481, "norm_direction":  1},
    {"factor_key": "reversal_5d",   "category": "momentum",   "weight": 0.0481, "norm_direction": -1},
    {"factor_key": "reversal_20d",  "category": "momentum",   "weight": 0.0288, "norm_direction": -1},
    {"factor_key": "roe",           "category": "quality",    "weight": 0.0577, "norm_direction":  1},
    {"factor_key": "roa",           "category": "quality",    "weight": 0.0385, "norm_direction":  1},
    {"factor_key": "gross_margin",  "category": "quality",   "weight": 0.0481, "norm_direction":  1},
    {"factor_key": "net_profit_margin","category":"quality", "weight": 0.0481, "norm_direction":  1},
    {"factor_key": "eps_growth_yoy", "category": "quality",   "weight": 0.0481, "norm_direction":  1},
    {"factor_key": "main_net_flow_5d",     "category": "money_flow", "weight": 0.1154, "norm_direction":  1},
    {"factor_key": "main_net_flow_ratio_5d","category": "money_flow", "weight": 0.0769, "norm_direction":  1},
    {"factor_key": "ma5_deviation",  "category": "technical", "weight": 0.0481, "norm_direction":  1},
    {"factor_key": "volatility_20d", "category": "technical", "weight": 0.0481, "norm_direction": -1},
    {"factor_key": "gap_open_pct",   "category": "technical", "weight": 0.0288, "norm_direction":  1},
    {"factor_key": "intraday_break_pct","category":"technical","weight": 0.0192, "norm_direction":  1},
    {"factor_key": "avg_turnover_20d","category": "volume",   "weight": 0.0577, "norm_direction":  1},
    {"factor_key": "volume_ratio_5d","category": "volume",   "weight": 0.0577, "norm_direction":  1},
    {"factor_key": "volume_surge",   "category": "volume",   "weight": 0.0385, "norm_direction":  1},
]


def upsert_weights(conn, weights):
    written = 0
    with conn.cursor() as cur:
        for w in weights:
            cur.execute(
                "INSERT INTO factor_weights (factor_key, category, weight, norm_direction, description) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (factor_key) DO UPDATE SET category=EXCLUDED.category, "
                "weight=EXCLUDED.weight, norm_direction=EXCLUDED.norm_direction",
                (w["factor_key"], w["category"], w["weight"], w["norm_direction"], w.get("description", ""))
            )
            written += 1
        conn.commit()
    return written


def load_weights(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT factor_key, category, weight, norm_direction FROM factor_weights")
        return [{"factor_key": r[0], "category": r[1], "weight": float(r[2]), "norm_direction": int(r[3])}
                for r in cur.fetchall()]


def percentile_rank(values):
    if not values:
        return []
    sr = pd.Series(values, dtype=float)
    ranks = sr.rank(pct=True, ascending=True, method="average")
    return ranks.fillna(50).tolist()


def normalize_factor(raw_values, direction):
    codes = list(raw_values.keys())
    vals = list(raw_values.values())
    if not vals or all(v is None for v in vals):
        return {c: 50.0 for c in codes}
    pct_ranks = percentile_rank(vals)
    if direction == -1:
        sr = pd.Series(vals, dtype=float)
        pct_ranks = sr.rank(pct=True, ascending=False, method="average").fillna(50).tolist()
    return {code: pct_ranks[i] for i, code in enumerate(codes)}


def compute_alpha_scores(conn, calc_date, top_n=100):
    result = {"date": str(calc_date), "signals": 0, "top_signals": []}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT d.company_id FROM daily_quotes d "
            "WHERE d.trade_date BETWEEN %s AND %s "
            "UNION "
            "SELECT fv.company_id FROM factor_values fv "
            "WHERE fv.calc_date = %s AND fv.company_id IS NOT NULL",
            (calc_date - timedelta(days=30), calc_date, calc_date)
        )
        company_ids = [r[0] for r in cur.fetchall()]

    if not company_ids:
        logger.warning("%s 无可计算公司", calc_date)
        return result

    weights = load_weights(conn)
    if not weights:
        upsert_weights(conn, DEFAULT_WEIGHTS)
        weights = DEFAULT_WEIGHTS

    with conn.cursor() as cur:
        cur.execute(
            "SELECT fv.company_id, fd.factor_key, fv.value "
            "FROM factor_values fv JOIN factor_definitions fd ON fd.id = fv.factor_id "
            "WHERE fv.calc_date = %s AND fv.company_id = ANY(%s) AND fv.value IS NOT NULL",
            (calc_date, company_ids)
        )
        raw_factor_rows = cur.fetchall()

    if not raw_factor_rows:
        logger.warning("%s 无因子值", calc_date)
        return result

    company_factors = {}
    for cid, fk, fv in raw_factor_rows:
        company_factors.setdefault(cid, {})[fk] = float(fv)

    categories = {}
    for w in weights:
        categories.setdefault(w["category"], []).append(w)

    company_scores = {}
    for cid, factors in company_factors.items():
        cat_scores = {}
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, cat_weights in categories.items():
            cat_raw = {w["factor_key"]: factors[w["factor_key"]] for w in cat_weights
                       if w["factor_key"] in factors and factors[w["factor_key"]] is not None}
            if cat_raw:
                normed = normalize_factor(cat_raw, cat_weights[0]["norm_direction"])
                cat_score = sum(normed[k] * w["weight"] for k, w in zip(cat_raw.keys(), cat_weights) if k in normed)
                total_weight += sum(w["weight"] for w in cat_weights)
                weighted_sum += cat_score
                cat_scores[cat] = cat_score
        expected_weight = sum(w["weight"] for w in weights)
        if total_weight > 0 and expected_weight > 0:
            coverage = total_weight / expected_weight
            raw_score = weighted_sum / total_weight
            # 归一化到[0,100]，coverage<1 时直接线性衰减，不存在虚高空间
            composite = (raw_score - 50) * 2 * coverage
        else:
            composite = 0.0
        company_scores[cid] = {"company_id": cid, "cat_scores": cat_scores, "composite_score": composite}

    sorted_companies = sorted(company_scores.values(), key=lambda x: x["composite_score"], reverse=True)
    for rank, cs in enumerate(sorted_companies, 1):
        cs["score_rank"] = rank

    written = 0
    with conn.cursor() as cur:
        for cid, cs in company_scores.items():
            comp = cs["composite_score"]
            signal = 1 if comp > 30 else -1 if comp < -30 else 0
            cat_scores = cs.get("cat_scores", {})
            reasons = []
            if cat_scores:
                best_cat = max(cat_scores, key=cat_scores.get)
                reasons.append("强势:" + best_cat)
            if cat_scores.get("momentum", 0) > 60:
                reasons.append("动量强")
            if cat_scores.get("money_flow", 0) > 60:
                reasons.append("资金净流入")
            reason = "|".join(reasons) if reasons else "综合评分"
            cur.execute(
                "INSERT INTO alpha_signals "
                "(company_id, calc_date, cat_scores_json, norm_momentum, norm_value, norm_quality, "
                "norm_money_flow, norm_technical, norm_volume, composite_score, signal, signal_reason, score_rank) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (company_id, calc_date) DO UPDATE SET "
                "composite_score=EXCLUDED.composite_score, signal=EXCLUDED.signal, "
                "signal_reason=EXCLUDED.signal_reason, score_rank=EXCLUDED.score_rank, "
                "norm_momentum=EXCLUDED.norm_momentum, norm_value=EXCLUDED.norm_value, "
                "norm_quality=EXCLUDED.norm_quality, norm_money_flow=EXCLUDED.norm_money_flow, "
                "norm_technical=EXCLUDED.norm_technical, norm_volume=EXCLUDED.norm_volume",
                (cid, calc_date, json.dumps(cat_scores),
                 cat_scores.get("momentum"), cat_scores.get("value"), cat_scores.get("quality"),
                 cat_scores.get("money_flow"), cat_scores.get("technical"), cat_scores.get("volume"),
                 comp, signal, reason, cs["score_rank"])
            )
            written += 1
    conn.commit()

    result["signals"] = written
    result["top_signals"] = [{"rank": c["score_rank"], "company_id": c["company_id"], "score": round(c["composite_score"], 2)} for c in sorted(list(company_scores.values()), key=lambda x: x["composite_score"], reverse=True)[:10]]
    return result


def get_top_signals(conn, calc_date, n=20, signal_filter=None):
    with conn.cursor() as cur:
        query = (
            "SELECT a.score_rank, c.code, c.name, c.industry, a.composite_score, a.signal, "
            "a.signal_reason, a.norm_momentum, a.norm_money_flow "
            "FROM alpha_signals a JOIN companies c ON a.company_id = c.id "
            "WHERE a.calc_date = %s"
        )
        params = [calc_date]
        if signal_filter is not None:
            query += " AND a.signal = %s"
            params.append(signal_filter)
        query += " ORDER BY a.score_rank LIMIT %s"
        params.append(n)
        cur.execute(query, params)
        return [
            {"rank": r[0], "code": r[1], "name": r[2], "industry": r[3],
             "score": round(float(r[4]), 2), "signal": int(r[5]), "reason": r[6],
             "momentum_norm": round(float(r[7]), 2) if r[7] else None,
             "money_flow_norm": round(float(r[8]), 2) if r[8] else None}
            for r in cur.fetchall()
        ]
