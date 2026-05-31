"""基本面因子计算器 — 从 financial_reports 计算各类财务因子"""

import logging
import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Optional

from src.factors.base import FactorCalculator, DataLoader

logger = logging.getLogger(__name__)


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
            if equity == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / equity
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class ROACalculator(FactorCalculator):
    """ROA = 净利润 / 总资产"""
    factor_key = "roa"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            assets = row.get("total_assets", 0) or 0
            if assets == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / assets
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
            if rev == 0:
                continue
            cost = row.get("cost_of_sales", 0) or 0
            val = (rev - cost) / rev
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
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
            if rev == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / rev
            results.append({"company_id": int(row["company_id"]), "value": round(float(val), 6)})
        return results


class DebtRatioCalculator(FactorCalculator):
    """资产负债率 = 总负债 / 总资产"""
    factor_key = "debt_ratio"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            assets = row.get("total_assets", 0) or 0
            if assets == 0:
                continue
            val = (row.get("total_liabilities", 0) or 0) / assets
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
            # 找上年同期
            latest_date = latest["report_date"]
            target_year = latest_date.year - 1
            prev = sub[sub["report_date"].dt.year == target_year]
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
