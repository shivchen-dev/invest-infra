"""因子计算基类 — 定义因子计算接口和数据加载工具"""

import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
import psycopg2
import psycopg2.extras

from src.config import pg as pg_cfg

logger = logging.getLogger(__name__)


class FactorCalculator(ABC):
    """因子计算器抽象基类"""

    factor_key: str = ""  # 子类必须设置

    @abstractmethod
    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        """计算因子值

        Args:
            company_ids: 要计算的公司 ID 列表
            calc_date: 计算基准日期
        Returns:
            list[dict]: [{"company_id": int, "value": float}, ...]
        """
        ...


class DataLoader:
    """因子计算数据加载工具 — 从 PostgreSQL 读取源数据
    
    建议使用 with 语句管理生命周期：
    
        with DataLoader() as dl:
            df = dl.load_quotes(...)
        # 或手动关闭：dl.close()
    """

    def __init__(self):
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(pg_cfg.uri)
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 行情数据 ──

    def load_quotes(self, company_ids: list[int], start_date: date, end_date: date) -> pd.DataFrame:
        """加载日行情数据
        
        注意：返回数据为不复权价格（raw price），如需复权数据请使用 adjust_mode 参数。
        """
        sql = """
            SELECT dq.company_id, dq.trade_date, dq.open_price, dq.high_price,
                   dq.low_price, dq.close_price, dq.volume,
                   dq.amount, dq.turnover_rate, dq.change_pct
            FROM daily_quotes dq
            WHERE dq.company_id = ANY(%s)
              AND dq.trade_date BETWEEN %s AND %s
            ORDER BY dq.company_id, dq.trade_date
        """
        return pd.read_sql(sql, self.conn, params=(company_ids, start_date, end_date),
                           parse_dates=["trade_date"],
                           index_col=["company_id", "trade_date"])

    # ── 财报数据 ──

    def load_financial_reports(self, company_ids: list[int]) -> pd.DataFrame:
        """加载财务报表历史数据
        
        注意：返回全部历史记录（与 load_latest_financial 的最新一期不同），
        用于需要历史序列的因子计算场景。
        """
        sql = """
            SELECT fr.company_id, fr.report_date, fr.report_type, fr.fiscal_year,
                   fr.revenue, fr.cost_of_sales, fr.net_profit,
                   fr.parent_net_profit, fr.total_assets,
                   fr.total_liabilities, fr.total_equity, fr.operating_cf,
                   fr.gross_profit
            FROM financial_reports fr
            WHERE fr.company_id = ANY(%s)
            ORDER BY fr.company_id, fr.report_date DESC
        """
        df = pd.read_sql(sql, self.conn, params=(company_ids,),
                         parse_dates=["report_date"])
        return df

    def load_latest_financial(self, company_ids: list[int]) -> pd.DataFrame:
        """加载每家公司的最新一期完整财报"""
        sql = """
            SELECT DISTINCT ON (fr.company_id)
                   fr.company_id, fr.report_date, fr.report_type, fr.fiscal_year,
                   fr.revenue, fr.cost_of_sales, fr.net_profit,
                   fr.parent_net_profit, fr.total_assets,
                   fr.total_liabilities, fr.total_equity,
                   fr.roa_raw, fr.debt_ratio_raw
            FROM financial_reports fr
            WHERE fr.company_id = ANY(%s)
              AND fr.revenue IS NOT NULL
              AND fr.net_profit IS NOT NULL
            ORDER BY fr.company_id, fr.report_date DESC
        """
        df = pd.read_sql(sql, self.conn, params=(company_ids,),
                         parse_dates=["report_date"])
        return df

    def load_financial_by_year(self, company_ids: list[int], fiscal_year: int) -> pd.DataFrame:
        """加载指定财年的财报"""
        sql = """
            SELECT fr.company_id, fr.report_date, fr.report_type, fr.fiscal_year,
                   fr.revenue, fr.net_profit, fr.parent_net_profit,
                   fr.total_assets, fr.total_liabilities, fr.total_equity,
                   fr.roa_raw, fr.debt_ratio_raw
            FROM financial_reports fr
            WHERE fr.company_id = ANY(%s)
              AND fr.fiscal_year = %s
            ORDER BY fr.company_id, fr.report_date DESC
        """
        return pd.read_sql(sql, self.conn, params=(company_ids, fiscal_year),
                           parse_dates=["report_date"])
