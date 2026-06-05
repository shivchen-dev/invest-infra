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
        results = []
        for _, row in df.iterrows():
            equity = row.get("total_equity", 0) or 0
            if not _valid(equity) or float(equity) == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / float(equity)
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class ROACalculator(FactorCalculator):
    """ROA = 净利润 / 总资产；优先用财报原始指标总资产报酬率(ROA)%"""
    factor_key = "roa"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            # 优先用 akshare 直接提供的总资产报酬率（%），除以100转小数
            roa_raw = row.get("roa_raw")
            if _valid(roa_raw):
                val = float(roa_raw) / 100.0
                results.append({"company_id": int(row["company_id"]), "value": round(val, 6)})
                continue
            # 兜底：自己算
            assets = row.get("total_assets", 0) or 0
            if not _valid(assets) or float(assets) == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / float(assets)
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class GrossMarginCalculator(FactorCalculator):
    """毛利率 = (营收 - 营业成本) / 营收"""
    factor_key = "gross_margin"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            rev = row.get("revenue", 0) or 0
            if not _valid(rev) or float(rev) == 0:
                continue
            cost = row.get("cost_of_sales", 0) or 0
            val = (float(rev) - float(cost)) / float(rev)
            results.append({"company_id": int(row["company_id"]), "value": round(val, 6)})
        return results


class NetProfitMarginCalculator(FactorCalculator):
    """净利率 = 净利润 / 营收"""
    factor_key = "net_profit_margin"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            rev = row.get("revenue", 0) or 0
            if not _valid(rev) or float(rev) == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / float(rev)
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class DebtRatioCalculator(FactorCalculator):
    """资产负债率 = 总负债 / 总资产；优先用财报原始指标资产负债率%"""
    factor_key = "debt_ratio"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            # 优先用 akshare 直接提供的资产负债率（%），除以100转小数
            debt_raw = row.get("debt_ratio_raw")
            if _valid(debt_raw):
                val = float(debt_raw) / 100.0
                results.append({"company_id": int(row["company_id"]), "value": round(val, 6)})
                continue
            # 兜底：自己算
            assets = row.get("total_assets", 0) or 0
            if not _valid(assets) or float(assets) == 0:
                continue
            val = (row.get("total_liabilities", 0) or 0) / float(assets)
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class EPSGrowthYoYCalculator(FactorCalculator):
    """归母净利润同比增长率 = (本期-上年同期)/|上年同期|"""
    factor_key = "eps_growth_yoy"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_financial_reports(company_ids)
        if df.empty:
            return []

        # 取每家公司最新一期及其 4 个季度前的对比
        df = df.sort_values(["company_id", "report_date"], ascending=[True, False])
        results = []
        for cid in company_ids:
            sub = df[df["company_id"] == cid]
            if len(sub) < 2:
                continue
            latest = sub.iloc[0]
            # 找上年同期（按年+季度匹配，避免跨季度错误对比）
            latest_date = latest["report_date"]
            target_year = latest_date.year - 1
            prev = sub[(sub["report_date"].dt.year == target_year) &
                       (sub["report_date"].dt.quarter == latest_date.quarter)]
            if prev.empty:
                continue
            prev = prev.iloc[0]

            cur_val = latest.get("parent_net_profit", 0) or 0
            prev_val = prev.get("parent_net_profit", 0) or 0
            if prev_val == 0:
                continue
            val = (cur_val - prev_val) / abs(prev_val)
            results.append({"company_id": int(cid), "value": round(float(val), 6)})
        return results
