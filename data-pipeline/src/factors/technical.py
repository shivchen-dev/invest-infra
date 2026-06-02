"""技术面因子计算器 — 从 daily_quotes 计算各类量价因子"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

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


class Reversal5dCalculator(FactorCalculator):
    """5日反转因子 = -(近5日涨幅)，做空短期动量反转"""
    factor_key = "reversal_5d"

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
                recent = sub.tail(5)
                ret = (recent["close_price"].iloc[-1] / recent["close_price"].iloc[0] - 1)
                val = -ret  # 反转：跌得多 → 值正（超跌反弹）
                results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class Reversal20dCalculator(FactorCalculator):
    """20日反转因子 = -(近20日涨幅)"""
    factor_key = "reversal_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=50)
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
                recent = sub.tail(20)
                ret = (recent["close_price"].iloc[-1] / recent["close_price"].iloc[0] - 1)
                val = -ret
                results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class GapOpenPctCalculator(FactorCalculator):
    """跳空幅度 = (今日开盘价 - 昨日收盘价) / 昨日收盘价"""
    factor_key = "gap_open_pct"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=10)
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
                if len(sub) < 2:
                    continue
                last = sub.iloc[-1]
                prev = sub.iloc[-2]
                prev_close = float(prev["close_price"])
                if prev_close == 0:
                    continue
                gap = (float(last["open_price"]) - prev_close) / prev_close
                results.append({"company_id": int(cid), "value": round(float(gap), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class IntradayBreakPctCalculator(FactorCalculator):
    """日内突破幅度 = (日内最高价 - 日内最低价) / 日内最低价"""
    factor_key = "intraday_break_pct"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=10)
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
                if len(sub) < 1:
                    continue
                last = sub.iloc[-1]
                low = float(last["low_price"])
                high = float(last["high_price"])
                if low == 0:
                    continue
                val = (high - low) / low
                results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class VolumeSurgeCalculator(FactorCalculator):
    """量能爆发 = 今日成交量 / 20日均量 - 1"""
    factor_key = "volume_surge"

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
                if len(sub) < 21:
                    continue
                avg_vol = sub["volume"].tail(21).head(20).mean()
                last_vol = sub["volume"].iloc[-1]
                if avg_vol == 0:
                    continue
                val = (last_vol / avg_vol) - 1
                results.append({"company_id": int(cid), "value": round(float(val), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class VolumeCVCalculator(FactorCalculator):
    """成交量变异系数 = 20日成交量标准差 / 20日成交量均值"""
    factor_key = "volume_cv"

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
                vol_series = sub["volume"].tail(20)
                mean_vol = vol_series.mean()
                if mean_vol == 0:
                    continue
                cv = vol_series.std() / mean_vol
                results.append({"company_id": int(cid), "value": round(float(cv), 6)})
            except (KeyError, ValueError, IndexError):
                continue
        return results


class MainNetFlow5dCalculator(FactorCalculator):
    """5日主力净流入 = 近5日 (买盘金额 - 卖盘金额)，需 fund_flow_big_deal 表"""
    factor_key = "main_net_flow_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg
        conn = psycopg2.connect(pg_cfg.uri)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT company_id,
                               SUM(CASE WHEN deal_nature = '买盘' THEN amount ELSE -amount END) AS net_flow
                        FROM fund_flow_big_deal
                        WHERE company_id = ANY(%s)
                          AND trade_time >= %s
                        GROUP BY company_id
                    """, (company_ids, start))
                    results = [
                        {"company_id": int(row[0]), "value": round(float(row[1]), 2)}
                        for row in cur.fetchall()
                    ]
                    return results
        finally:
            conn.close()


class MainNetFlowRatio5dCalculator(FactorCalculator):
    """5日主力净流入占比 = 主力净流入 / 总成交金额，需 fund_flow_big_deal 表"""
    factor_key = "main_net_flow_ratio_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg
        conn = psycopg2.connect(pg_cfg.uri)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT company_id,
                               SUM(CASE WHEN deal_nature = '买盘' THEN amount ELSE -amount END) AS net_flow,
                               SUM(amount) AS total_amount
                        FROM fund_flow_big_deal
                        WHERE company_id = ANY(%s)
                          AND trade_time >= %s
                        GROUP BY company_id
                    """, (company_ids, start))
                    results = []
                    for row in cur.fetchall():
                        if row[2] and row[2] > 0:
                            results.append({"company_id": int(row[0]), "value": round(float(row[1] / row[2]), 6)})
                    return results
        finally:
            conn.close()
