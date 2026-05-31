"""PG → Backtrader DataFeed 适配器

从 PostgreSQL 加载行情数据和因子信号，转为 Backtrader 可消费的 pandas DataFrame。
"""

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras

from src.config import pg as pg_cfg

logger = logging.getLogger(__name__)


def load_market_data(
    company_ids: list[int],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """从 PG 加载行情数据

    Returns:
        MultiIndex DataFrame: (company_id, trade_date) columns=[open,high,low,close,volume,amount,turnover_rate]
    """
    sql = """
        SELECT company_id, trade_date,
               open_price, high_price, low_price, close_price,
               volume, amount, turnover_rate
        FROM daily_quotes
        WHERE company_id = ANY(%s)
          AND trade_date BETWEEN %s AND %s
        ORDER BY company_id, trade_date
    """
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        df = pd.read_sql(sql, conn, params=(company_ids, start_date, end_date),
                         parse_dates=["trade_date"])
        df.set_index(["company_id", "trade_date"], inplace=True)
        df.columns = [c.replace("_price", "") for c in df.columns]
        return df
    finally:
        conn.close()


def load_factor_signals(
    company_ids: list[int],
    factor_keys: list[str],
    start_date: date,
    end_date: date,
    use_percentile: bool = True,
) -> pd.DataFrame:
    """从 factor_values 加载因子信号

    Args:
        use_percentile: True 用百分位, False 用 Z-score
    Returns:
        MultiIndex DataFrame: (company_id, trade_date) columns=factor_key values
    """
    value_col = "percentile" if use_percentile else "zscore"
    sql = f"""
        SELECT fv.company_id, fv.calc_date, fd.factor_key, fv.{value_col} as signal_value
        FROM factor_values fv
        JOIN factor_definitions fd ON fv.factor_id = fd.id
        WHERE fv.company_id = ANY(%s)
          AND fd.factor_key = ANY(%s)
          AND fv.calc_date BETWEEN %s AND %s
        ORDER BY fv.company_id, fv.calc_date
    """
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        df = pd.read_sql(sql, conn, params=(company_ids, factor_keys, start_date, end_date),
                         parse_dates=["calc_date"])
        if df.empty:
            return df
        df.rename(columns={"calc_date": "trade_date"}, inplace=True)
        df.set_index(["company_id", "trade_date", "factor_key"], inplace=True)
        df = df.unstack("factor_key")
        df.columns = df.columns.droplevel(0)
        return df
    finally:
        conn.close()


def build_backtest_data(
    company_ids: list[int],
    factor_keys: list[str],
    start_date: date,
    end_date: date,
    fill_method: str = "ffill",
) -> dict[int, pd.DataFrame]:
    """组装每只股票的 Backtest 数据集（行情+因子合并）

    Returns:
        {company_id: pd.DataFrame(with OHLCV + factor columns)}
    """
    mkt = load_market_data(company_ids, start_date, end_date)
    fac = load_factor_signals(company_ids, factor_keys, start_date, end_date)

    result = {}
    for cid in company_ids:
        try:
            m = mkt.xs(cid, level="company_id") if cid in mkt.index.get_level_values("company_id") else None
            f = fac.xs(cid, level="company_id") if not fac.empty and cid in fac.index.get_level_values("company_id") else None
        except KeyError:
            continue

        if m is None or m.empty:
            continue

        # Merge: factor 日期可能与行情不完全对齐
        if f is not None and not f.empty:
            df = m.join(f, how="left")
        else:
            df = m.copy()

        # 前向填充因子值（保留上次信号直到下次计算）
        if fill_method:
            df.ffill(inplace=True)
        df.fillna(0.0, inplace=True)  # 仍有空缺填 0

        df.sort_index(inplace=True)
        result[cid] = df

    return result


def get_company_code_map(company_ids: list[int]) -> dict[int, str]:
    """{company_id: code} 映射"""
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, code FROM companies WHERE id = ANY(%s)", (company_ids,))
            return dict(cur.fetchall())
    finally:
        conn.close()
