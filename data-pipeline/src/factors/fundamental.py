"""基本面因子计算器 — 从 financial_reports 计算各类财务因子"""

import logging
import math
import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Optional

from src.factors.base import FactorCalculator, DataLoader

logger = logging.getLogger(__name__)


def _valid(v) -> bool:
    """判断因子值是否有效（非NULL、非NaN）"""
    if v is None:
        return False
    try:
        return not math.isnan(float(v))
    except (TypeError, ValueError):
        return False


class ROECalculator(FactorCalculator):
    """ROE = 净利润 / 净资产"""
    factor_key = "roe"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        equity = df["total_equity"].astype(float).replace(0, np.nan)
        net_profit = df["net_profit"].astype(float).replace(0, np.nan)
        valid = ~(equity.isna() | equity.eq(0))
        vals = net_profit / equity
        results = []
        for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results


class ROACalculator(FactorCalculator):
    """ROA = 净利润 / 总资产；优先用财报原始指标总资产报酬率(ROA)%"""
    factor_key = "roa"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        roa_raw = pd.to_numeric(df["roa_raw"], errors="coerce")
        valid_raw = roa_raw.notna() & (roa_raw != 0)
        vals = np.where(valid_raw, roa_raw / 100.0, np.nan)
        assets = df["total_assets"].astype(float).replace(0, np.nan)
        net_profit = df["net_profit"].astype(float).replace(0, np.nan)
        valid_calc = ~(assets.isna() | assets.eq(0))
        calc_vals = net_profit / assets
        vals = np.where(valid_raw, vals, calc_vals)
        valid = ~(np.isnan(vals))
        results = []
        for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results


class GrossMarginCalculator(FactorCalculator):
    """毛利率 = (营收 - 营业成本) / 营收"""
    factor_key = "gross_margin"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        revenue = df["revenue"].astype(float).replace(0, np.nan)
        cost = df["cost_of_sales"].astype(float).replace(0, np.nan)
        valid = ~(revenue.isna() | revenue.eq(0))
        vals = (revenue - cost) / revenue
        results = []
        for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results


class NetProfitMarginCalculator(FactorCalculator):
    """净利率 = 净利润 / 营收"""
    factor_key = "net_profit_margin"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        revenue = df["revenue"].astype(float).replace(0, np.nan)
        net_profit = df["net_profit"].astype(float).replace(0, np.nan)
        valid = ~(revenue.isna() | revenue.eq(0))
        vals = net_profit / revenue
        results = []
        for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results


class DebtRatioCalculator(FactorCalculator):
    """资产负债率 = 总负债 / 总资产；优先用财报原始指标资产负债率%"""
    factor_key = "debt_ratio"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        debt_raw = pd.to_numeric(df["debt_ratio_raw"], errors="coerce")
        valid_raw = debt_raw.notna() & (debt_raw != 0)
        vals = np.where(valid_raw, debt_raw / 100.0, np.nan)
        assets = df["total_assets"].astype(float).replace(0, np.nan)
        liabilities = df["total_liabilities"].astype(float).replace(0, np.nan)
        calc_vals = liabilities / assets
        vals = np.where(valid_raw, vals, calc_vals)
        valid = ~(np.isnan(vals))
        results = []
        for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results


class EPSGrowthYoYCalculator(FactorCalculator):
    """归母净利润同比增长率 = (本期-上年同期)/|上年同期|"""
    factor_key = "eps_growth_yoy"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_financial_reports(company_ids)
        if df.empty:
            return []

        # 取每家公司最新一期及其上年同期的对比（向量化 merge，替代 iterrows）
        cur_df = df.sort_values("report_date").groupby("company_id").last().reset_index()
        cur_df["prev_year"] = cur_df["report_date"].dt.year - 1
        cur_df["prev_quarter"] = cur_df["report_date"].dt.quarter

        prev_lookup = (
            df[["company_id", "parent_net_profit"]]
            .copy()
            .assign(
                rep_year=lambda d: d["report_date"].dt.year,
                rep_quarter=lambda d: d["report_date"].dt.quarter,
            )
        ).sort_values("report_date").groupby(["company_id", "rep_year", "rep_quarter"]).last().reset_index()

        merged = cur_df.merge(
            prev_lookup,
            on=["company_id"],
            right_on=["rep_year", "rep_quarter"],
            suffixes=("_cur", "_prev"),
        )
        valid = (merged["prev_year"] == merged["rep_year"]) & \
                (merged["prev_quarter"] == merged["rep_quarter"])

        parent_net_profit_cur = pd.to_numeric(merged["parent_net_profit_cur"], errors="coerce")
        parent_net_profit_prev = pd.to_numeric(merged["parent_net_profit_prev"], errors="coerce")

        valid &= parent_net_profit_prev.notna() & (parent_net_profit_prev != 0)
        cur_vals = parent_net_profit_cur.where(valid, 0)
        prev_vals = parent_net_profit_prev.where(valid, 1)  # avoid div by zero
        vals = (cur_vals - prev_vals) / prev_vals.abs()

        results = []
        for cid, val in zip(merged.loc[valid, "company_id"], vals[valid]):
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results
