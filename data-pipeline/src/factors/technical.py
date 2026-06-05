"""技术面因子计算器 — 全量向量化解法，无 Python for 循环

所有 calculator 共享同一个 DataLoader 流程：
  1. 一次性 load_quotes 全量数据
  2. groupby + apply 向量化计算
  3. 过滤无效值后返回 list[dict]
"""

import logging
from datetime import date, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
import psycopg2

from src.factors.base import FactorCalculator, DataLoader

logger = logging.getLogger(__name__)

# ── 公共工具 ──────────────────────────────────────────────────────────


def _load_for_calcs(
    company_ids: list[int],
    calc_date: date,
    lookback: int,
    loader: DataLoader,
) -> pd.DataFrame:
    """统一数据加载：取 calc_date 之前 lookback 天，但每个股票独立排序后取实际交易日"""
    start = calc_date - timedelta(days=lookback)
    df = loader.load_quotes(company_ids, start_date=start, end_date=calc_date)
    if df.empty:
        return df
    # 确保按 stock + date 升序，为后续 rolling/groupby 提供确定性顺序
    df = df.sort_index()
    return df


def _filter_for_calculator(quotes_df: pd.DataFrame, company_ids: list[int],
                          calc_date: date, lookback: int) -> pd.DataFrame:
    """对预加载的 quotes_df 按计算器需求做筛选。

    逻辑与 _load_for_calcs 一致，但在已加载的 DataFrame 上操作而非新建 DataLoader。
    """
    start = calc_date - timedelta(days=lookback)
    df = quotes_df[
        (quotes_df["company_id"].isin(company_ids)) &
        (quotes_df["trade_date"] >= start) &
        (quotes_df["trade_date"] <= calc_date)
    ]
    if df.empty:
        return df
    df = df.sort_index()
    return df


def _momentum(close: pd.Series, window: int) -> Optional[float]:
    if len(close) < window:
        return None
    result = (close.iloc[-1] / close.iloc[-window]) - 1
    return round(float(result), 6) if pd.notna(result) else None


def _volatility(close: pd.Series, window: int = 20) -> Optional[float]:
    if len(close) < window:
        return None
    ret = close.pct_change().dropna()
    if len(ret) < window:
        return None
    vol = ret.tail(window).std() * np.sqrt(252)
    return round(float(vol), 6) if pd.notna(vol) else None


def _avg_turnover(turnover: pd.Series, window: int = 20) -> Optional[float]:
    if len(turnover) < window:
        return None
    val = turnover.tail(window).mean()
    return round(float(val), 6) if pd.notna(val) else None


def _ma5_deviation(close: pd.Series) -> Optional[float]:
    if len(close) < 5:
        return None
    ma5 = close.tail(5).mean()
    if ma5 <= 0:
        return None
    val = (float(close.iloc[-1]) / ma5) - 1
    return round(val, 6)


def _volume_ratio(volume: pd.Series) -> Optional[float]:
    if len(volume) < 6:
        return None
    avg5 = volume.tail(6).head(5).mean()
    last = volume.iloc[-1]
    if avg5 <= 0:
        return None
    return round(float(last / avg5), 6)


def _reversal(close: pd.Series, window: int) -> Optional[float]:
    if len(close) < window:
        return None
    ret = (close.iloc[-1] / close.iloc[-window]) - 1
    return round(float(-ret), 6) if pd.notna(ret) else None


def _gap_open(open_: pd.Series, close: pd.Series) -> Optional[float]:
    if len(open_) < 2 or len(close) < 2:
        return None
    prev_close = float(close.iloc[-2])
    if prev_close == 0:
        return None
    gap = (float(open_.iloc[-1]) - prev_close) / prev_close
    return round(gap, 6)


def _intraday_break(high: pd.Series, low: pd.Series) -> Optional[float]:
    if len(high) < 1 or len(low) < 1:
        return None
    low_val = float(low.iloc[-1])
    if low_val == 0:
        return None
    return round((float(high.iloc[-1]) - low_val) / low_val, 6)


def _volume_surge(volume: pd.Series) -> Optional[float]:
    if len(volume) < 21:
        return None
    avg20 = volume.tail(21).head(20).mean()
    last = volume.iloc[-1]
    if avg20 <= 0:
        return None
    return round(float(last / avg20) - 1, 6)


def _volume_cv(volume: pd.Series) -> Optional[float]:
    if len(volume) < 20:
        return None
    tail = volume.tail(20)
    mean = tail.mean()
    if mean == 0:
        return None
    return round(float(tail.std() / mean), 6)


# ── 基础类（保留 ABC 接口，但 compute 已向量化）───────────────────────────


class MomentumCalculator(FactorCalculator):
    """动量因子基类（可配置窗口）— 全量 groupby 向量化"""
    factor_key = "momentum"

    def __init__(self, window: int = 5):
        self.window = window

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        lookback = self.window * 2 + 10
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, lookback)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, lookback, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _momentum(grp["close_price"], self.window)

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


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
    factor_key = "volatility_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 60)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 60, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _volatility(grp["close_price"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class AvgTurnover20dCalculator(FactorCalculator):
    factor_key = "avg_turnover_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 40)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 40, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _avg_turnover(grp["turnover_rate"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class MA5DeviationCalculator(FactorCalculator):
    factor_key = "ma5_deviation"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 20)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 20, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _ma5_deviation(grp["close_price"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class VolumeRatio5dCalculator(FactorCalculator):
    factor_key = "volume_ratio_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 20)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 20, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _volume_ratio(grp["volume"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class Reversal5dCalculator(FactorCalculator):
    factor_key = "reversal_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 20)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 20, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _reversal(grp["close_price"], 5)

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class Reversal20dCalculator(FactorCalculator):
    factor_key = "reversal_20d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 50)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 50, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _reversal(grp["close_price"], 20)

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class GapOpenPctCalculator(FactorCalculator):
    factor_key = "gap_open_pct"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 10)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 10, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _gap_open(grp["open_price"], grp["close_price"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class IntradayBreakPctCalculator(FactorCalculator):
    factor_key = "intraday_break_pct"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        quotes_df = kwargs.get("quotes_df")
        if quotes_df is not None:
            df = _filter_for_calculator(quotes_df, company_ids, calc_date, 10)
        else:
            with DataLoader() as dl:
                df = _load_for_calcs(company_ids, calc_date, 10, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _intraday_break(grp["high_price"], grp["low_price"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class VolumeSurgeCalculator(FactorCalculator):
    factor_key = "volume_surge"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = _load_for_calcs(company_ids, calc_date, 40, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _volume_surge(grp["volume"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class VolumeCVCalculator(FactorCalculator):
    factor_key = "volume_cv"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = _load_for_calcs(company_ids, calc_date, 40, dl)
        if df.empty:
            return []

        def calc_one(cid: int, grp: pd.DataFrame) -> Optional[float]:
            return _volume_cv(grp["volume"])

        results = (
            df.groupby(level="company_id", sort=False)
            .apply(calc_one)
            .dropna()
            .rename("value")
            .reset_index()
        )
        results["value"] = results["value"].astype(float)
        return results.to_dict(orient="records")


class MainNetFlow5dCalculator(FactorCalculator):
    factor_key = "main_net_flow_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg

        conn = psycopg2.connect(pg_cfg.uri)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT company_id,
                               SUM(CASE WHEN deal_nature = '买盘' THEN amount ELSE -amount END) AS net_flow
                        FROM fund_flow_big_deal
                        WHERE company_id = ANY(%s)
                          AND trade_time >= %s
                        GROUP BY company_id
                        """,
                        (company_ids, start),
                    )
                    return [
                        {"company_id": int(row[0]), "value": round(float(row[1]), 2)}
                        for row in cur.fetchall()
                    ]
        finally:
            conn.close()


class MainNetFlowRatio5dCalculator(FactorCalculator):
    factor_key = "main_net_flow_ratio_5d"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg

        conn = psycopg2.connect(pg_cfg.uri)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT company_id,
                               SUM(CASE WHEN deal_nature = '买盘' THEN amount ELSE -amount END) AS net_flow,
                               SUM(amount) AS total_amount
                        FROM fund_flow_big_deal
                        WHERE company_id = ANY(%s)
                          AND trade_time >= %s
                        GROUP BY company_id
                        """,
                        (company_ids, start),
                    )
                    results = []
                    for row in cur.fetchall():
                        if row[2] and row[2] > 0:
                            results.append(
                                {"company_id": int(row[0]), "value": round(float(row[1] / row[2]), 6)}
                            )
                    return results
        finally:
            conn.close()