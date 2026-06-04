"""因子计算引擎 — 编排计算、截面标准化、批量写入 Gold 层"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import numpy as np
import psycopg2
import psycopg2.extras

from src.config import pg as pg_cfg
from src.factors.registry import register_all, list_factors, get_factor_ids, FactorCategory

logger = logging.getLogger(__name__)

# 因子计算器映射（registry key → calculator 类）
# 在 _build_calculators() 中动态构造
_CALCULATOR_MAP: dict[str, object] = {}


def _build_calculators():
    """构建因子 key → 计算器实例 的映射"""
    if _CALCULATOR_MAP:
        return

    from src.factors.fundamental import (
        ROECalculator, ROACalculator, GrossMarginCalculator,
        NetProfitMarginCalculator, DebtRatioCalculator, EPSGrowthYoYCalculator,
    )
    from src.factors.technical import (
        Momentum5dCalculator, Momentum20dCalculator, Momentum60dCalculator,
        Volatility20dCalculator, AvgTurnover20dCalculator,
        MA5DeviationCalculator, VolumeRatio5dCalculator,
        Reversal5dCalculator, Reversal20dCalculator,
        GapOpenPctCalculator, IntradayBreakPctCalculator,
        VolumeSurgeCalculator, VolumeCVCalculator,
        MainNetFlow5dCalculator, MainNetFlowRatio5dCalculator,
    )
    from src.factors.alternative import (
        SentimentScoreCalculator, NewsVolume7dCalculator, NewsVolumeChangeCalculator,
    )

    _CALCULATOR_MAP.update({
        "roe": ROECalculator(),
        "roa": ROACalculator(),
        "gross_margin": GrossMarginCalculator(),
        "net_profit_margin": NetProfitMarginCalculator(),
        "debt_ratio": DebtRatioCalculator(),
        "eps_growth_yoy": EPSGrowthYoYCalculator(),
        "momentum_5d": Momentum5dCalculator(),
        "momentum_20d": Momentum20dCalculator(),
        "momentum_60d": Momentum60dCalculator(),
        "volatility_20d": Volatility20dCalculator(),
        "avg_turnover_20d": AvgTurnover20dCalculator(),
        "ma5_deviation": MA5DeviationCalculator(),
        "volume_ratio_5d": VolumeRatio5dCalculator(),
        "reversal_5d": Reversal5dCalculator(),
        "reversal_20d": Reversal20dCalculator(),
        "gap_open_pct": GapOpenPctCalculator(),
        "intraday_break_pct": IntradayBreakPctCalculator(),
        "volume_surge": VolumeSurgeCalculator(),
        "volume_cv": VolumeCVCalculator(),
        "main_net_flow_5d": MainNetFlow5dCalculator(),
        "main_net_flow_ratio_5d": MainNetFlowRatio5dCalculator(),
        "sentiment_score": SentimentScoreCalculator(),
        "news_volume_7d": NewsVolume7dCalculator(),
        "news_volume_change": NewsVolumeChangeCalculator(),
    })


def sync_definitions_to_db(conn=None):
    """将注册表中的因子定义写入 PostgreSQL factor_definitions 表（幂等）"""
    register_all()
    _build_calculators()

    _conn = conn or psycopg2.connect(pg_cfg.uri)
    _close = conn is None
    try:
        with _conn:
            with _conn.cursor() as cur:
                inserted = updated = 0
                for fd in list_factors():
                    cur.execute(
                        """
                        INSERT INTO factor_definitions
                            (factor_key, name, category, sub_category, formula_desc, data_source, frequency)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (factor_key) DO UPDATE SET
                            name=EXCLUDED.name, category=EXCLUDED.category,
                            sub_category=EXCLUDED.sub_category,
                            formula_desc=EXCLUDED.formula_desc,
                            data_source=EXCLUDED.data_source,
                            frequency=EXCLUDED.frequency,
                            updated_at=now()
                        """,
                        (fd.key, fd.name, fd.category.value, fd.sub_category,
                         fd.description, fd.data_source, fd.frequency.value),
                    )
                    if cur.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
                _conn.commit()
        logger.info(f"因子定义同步: 新增 {inserted}, 更新 {updated}")
        return {"inserted": inserted, "updated": updated}
    finally:
        if _close:
            _conn.close()


def get_active_company_ids() -> list[int]:
    """获取所有活跃公司 ID"""
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE is_active = TRUE ORDER BY id")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def _compute_percentile(values: list[float]) -> list[float]:
    """截面百分位排名 (0-1)"""
    arr = np.array(values)
    n = len(arr)
    if n == 0:
        return []
    # 处理 None
    mask = ~np.isnan(arr)
    ranks = np.zeros_like(arr, dtype=float)
    if mask.sum() > 0:
        valid = arr[mask]
        sorted_idx = np.argsort(valid)
        rank = np.zeros(len(valid), dtype=float)
        rank[sorted_idx] = np.arange(len(valid))
        ranked = rank / (len(valid) - 1) if len(valid) > 1 else np.array([0.5])
        ranks[mask] = ranked
    return [round(float(x), 6) for x in ranks]


def _compute_zscore(values: list[float]) -> list[float]:
    """截面 Z-score 标准化"""
    arr = np.array(values, dtype=float)
    mask = ~np.isnan(arr)
    if mask.sum() < 2:
        return [None] * len(values)
    mean = arr[mask].mean()
    std = arr[mask].std()
    if std == 0:
        return [0.0 if not np.isnan(x) else None for x in arr]
    scores = np.full_like(arr, np.nan, dtype=float)
    scores[mask] = (arr[mask] - mean) / std
    return [round(float(x), 6) if not np.isnan(x) else None for x in scores]


def compute_factors(
    factor_keys: Optional[list[str]] = None,
    company_ids: Optional[list[int]] = None,
    calc_date: Optional[date] = None,
    batch_label: Optional[str] = None,
) -> dict:
    """计算指定因子并写入 Gold 层

    Args:
        factor_keys: 因子列表，None=全部
        company_ids: 公司列表，None=全市场
        calc_date: 计算日期，默认今天
        batch_label: 批次标签
    Returns:
        统计结果
    """
    register_all()
    _build_calculators()

    if calc_date is None:
        calc_date = date.today()
    if company_ids is None:
        company_ids = get_active_company_ids()
    if factor_keys is None:
        factor_keys = [f.key for f in list_factors()]
    if batch_label is None:
        batch_label = f"batch_{calc_date.isoformat()}"

    logger.info(f"因子计算开始: {len(factor_keys)} 个因子 × {len(company_ids)} 只股票")

    # 确保 factor_definitions 表有记录
    sync_definitions_to_db()
    key2id = get_factor_ids()

    conn = psycopg2.connect(pg_cfg.uri)
    try:
        stats = {"factors_computed": 0, "values_written": 0, "errors": []}

        for fk in factor_keys:
            calc = _CALCULATOR_MAP.get(fk)
            if calc is None:
                stats["errors"].append(f"因子 {fk}: 无计算器")
                continue
            fd_id = key2id.get(fk)
            if fd_id is None:
                stats["errors"].append(f"因子 {fk}: 未在 factor_definitions 中找到")
                continue

            t0 = time.time()
            try:
                values = calc.compute(company_ids, calc_date)
            except Exception as e:
                logger.error(f"因子 {fk} 计算失败: {e}")
                stats["errors"].append(f"{fk}: {e}")
                continue

            if not values:
                logger.warning(f"因子 {fk}: 无计算结果")
                continue

            # 提取有效数值做截面标准化（保留 company_id 用于映射）
            valid_values = [v for v in values if v["value"] is not None]
            percentiles = _compute_percentile([v["value"] for v in valid_values]) if valid_values else []
            zscores = _compute_zscore([v["value"] for v in valid_values]) if valid_values else []

            pct_map = {v["company_id"]: p for v, p in zip(valid_values, percentiles)}
            zscore_map = {v["company_id"]: z for v, z in zip(valid_values, zscores)}

            # 写 factor_values
            written = 0
            with conn.cursor() as cur:
                for v in values:
                    if v["value"] is None:
                        continue
                    pct = pct_map.get(v["company_id"])
                    zsc = zscore_map.get(v["company_id"])
                    cur.execute(
                        """
                        INSERT INTO factor_values
                            (company_id, factor_id, calc_date, value, percentile, zscore, calc_batch_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (company_id, factor_id, calc_date) DO UPDATE SET
                            value=EXCLUDED.value, percentile=EXCLUDED.percentile,
                            zscore=EXCLUDED.zscore, calc_batch_id=EXCLUDED.calc_batch_id
                        """,
                        (v["company_id"], fd_id, calc_date, v["value"],
                         pct, zsc, batch_label),
                    )
                    written += 1

            conn.commit()
            elapsed = round(time.time() - t0, 2)
            stats["factors_computed"] += 1
            stats["values_written"] += written
            logger.info(f"  {fk}: {written} 条 (共 {len(values)} 项) [{elapsed}s]")

        logger.info(f"因子计算完成: {stats['factors_computed']} 个因子, {stats['values_written']} 条值")
        return stats
    finally:
        conn.close()
