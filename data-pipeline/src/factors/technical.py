"""技术面因子计算器 — 从 daily_quotes 计算各类量价因子"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.factors.base import FactorCalculator, DataLoader

logger = logging.getLogger(__name__)


class MomentumCalculator(FactorCalculator):
    """动量因子基类 (可配置窗口)"""
    factor_key = "momentum"

    def __init__(self, window: int = 5):
        self.window = window

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=self.window * 2 + 10)
        with DataLoader() as dl:
            df = dl.load_quotes(company_ids, start_date=start, end_date=calc_date)
        if df.empty:
            return []
        results = []
        for cid in company_ids:
            try:
                if cid not in df.index.get_level_values("company_id"):
                    continue
                sub = df.xs(cid, level="company_id").sort_index()
                if len(sub) < self.window:
                    continue
                recent = sub.tail(self.window)
                momentum = (recent["close_price"].iloc[-1] / recent["close_price"].iloc[0] - 1)
                results.append({"company_id": int(cid), "value": round(float(momentum), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class Momentum5dCalculator(MomentumCalculator):
    factor_key = "momentum_5d"
    def __init__(self):
        super().__init__(window=5)


class Momentum20dCalculator(MomentumCalculator):
    factor_key = "momentum_20d"
    def __init__(self):
        super().__init__(window=20)


class Momentum60dCalculator(MomentumCalculator):
    factor_key = "momentum_60d"
    def __init__(self):
        super().__init__(window=60)


class Volatility20dCalculator(FactorCalculator):
    """20日年化波动率"""
    factor_key = "volatility_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=60)
        with DataLoader() as dl:
            df = dl.load_quotes(company_ids, start_date=start, end_date=calc_date)
        if df.empty:
            return []
        results = []
        for cid in company_ids:
            try:
                if cid not in df.index.get_level_values("company_id"):
                    continue
                sub = df.xs(cid, level="company_id").sort_index()
                if len(sub) < 20:
                    continue
                returns = sub["close_price"].pct_change().dropna()
                if len(returns) < 20:
                    continue
                vol = returns.tail(20).std() * np.sqrt(252)
                results.append({"company_id": int(cid), "value": round(float(vol), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class AvgTurnover20dCalculator(FactorCalculator):
    """20日平均换手率"""
    factor_key = "avg_turnover_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=40)
        with DataLoader() as dl:
            df = dl.load_quotes(company_ids, start_date=start, end_date=calc_date)
        if df.empty:
            return []
        results = []
        for cid in company_ids:
            try:
                if cid not in df.index.get_level_values("company_id"):
                    continue
                sub = df.xs(cid, level="company_id").sort_index()
                if len(sub) < 20:
                    continue
                val = sub["turnover_rate"].tail(20).mean()
                if pd.notna(val):
                    results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError):
                continue
        return results


class MA5DeviationCalculator(FactorCalculator):
    """5日均线偏离度 = (收盘价-MA5)/MA5"""
    factor_key = "ma5_deviation"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=20)
        with DataLoader() as dl:
            df = dl.load_quotes(company_ids, start_date=start, end_date=calc_date)
        if df.empty:
            return []
        results = []
        for cid in company_ids:
            try:
                if cid not in df.index.get_level_values("company_id"):
                    continue
                sub = df.xs(cid, level="company_id").sort_index()
                if len(sub) < 5:
                    continue
                ma5 = sub["close_price"].tail(5).mean()
                last_close = sub["close_price"].iloc[-1]
                if ma5 > 0:
                    val = (last_close / ma5) - 1
                    results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError):
                continue
        return results


class VolumeRatio5dCalculator(FactorCalculator):
    """5日量比 = 当日成交量/5日均量"""
    factor_key = "volume_ratio_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=20)
        with DataLoader() as dl:
            df = dl.load_quotes(company_ids, start_date=start, end_date=calc_date)
        if df.empty:
            return []
        results = []
        for cid in company_ids:
            try:
                if cid not in df.index.get_level_values("company_id"):
                    continue
                sub = df.xs(cid, level="company_id").sort_index()
                if len(sub) < 6:
                    continue
                avg_vol = sub["volume"].tail(6).head(5).mean()
                last_vol = sub["volume"].iloc[-1]
                if avg_vol > 0:
                    val = last_vol / avg_vol
                    results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError):
                continue
        return results
