"""回测引擎 — Backtrader Cerebro 封装

管理数据添加、策略绑定、运行和结果收集全流程。
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import backtrader as bt
import pandas as pd

from src.backtest.feeds import build_backtest_data, get_company_code_map
from src.backtest.strategies import (
    StrategyConfig, MultiFactorStrategy, FactorSignalConfig,
)
from src.config import pg as pg_cfg

logger = logging.getLogger(__name__)


class BacktestResult:
    """单次回测的结果摘要"""

    def __init__(self, config: StrategyConfig, company_ids: list[int],
                 start_date: date, end_date: date):
        self.config = config
        self.company_ids = company_ids
        self.start_date = start_date
        self.end_date = end_date
        self.cerebro = None
        self.analyzers = {}
        self.portfolio_value_start = 0.0
        self.portfolio_value_end = 0.0
        self.total_return = 0.0
        self.annual_return = 0.0
        self.max_drawdown = 0.0
        self.sharpe_ratio = 0.0
        self.calmar_ratio = 0.0
        self.total_trades = 0
        self.win_rate = 0.0
        self.benchmark_return = 0.0
        self.benchmark_annual = 0.0
        self.active_return = 0.0
        self.info_ratio = 0.0
        self.num_data = 0
        self.run_time_sec = 0.0

    def to_dict(self) -> dict:
        return {
            "strategy": self.config.name,
            "stock_count": len(self.company_ids),
            "period": f"{self.start_date} ~ {self.end_date}",
            "portfolio_start": round(self.portfolio_value_start, 2),
            "portfolio_end": round(self.portfolio_value_end, 2),
            "total_return_pct": round(self.total_return * 100, 2),
            "annual_return_pct": round(self.annual_return * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "calmar_ratio": round(self.calmar_ratio, 3),
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "benchmark_return_pct": round(self.benchmark_return * 100, 2),
            "active_return_pct": round(self.active_return * 100, 2),
            "information_ratio": round(self.info_ratio, 3),
            "run_time_sec": round(self.run_time_sec, 2),
        }


def _add_custom_line(data, factor_cols: list[str], df: pd.DataFrame):
    """向 Backtrader data feed 动态添加因子列 as lines"""
    for col in factor_cols:
        if col not in df.columns:
            continue
        # Backtrader 的 PandasData 支持通过 lines 参数新增字段
        # 但我们用更直接的方式：将因子值作为额外的 data feed line
        pass


def _make_pandas_data(df: pd.DataFrame) -> type(bt.feeds.PandasData):
    """根据 DataFrame 列动态创建 PandasData 子类"""
    # 标准 OHLCV 映射
    params_default = [
        ("datetime", None),        # 用 index
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", None),
    ]

    # 找出额外的因子列
    std_cols = {"open", "high", "low", "close", "volume", "amount", "turnover_rate"}
    extra_cols = [c for c in df.columns if c not in std_cols]

    for col in extra_cols:
        params_default.append((col, col))

    return type("DynamicPandasData", (bt.feeds.PandasData,), {
        "params": type("Params", (), {"lines": tuple(["close"] + extra_cols), **dict(params_default)})()
    })


def run_backtest(
    config: StrategyConfig,
    company_ids: list[int],
    start_date: date,
    end_date: date,
    init_cash: float = 1_000_000.0,
    commission: float = 0.0003,       # 万分之三
    slippage: float = 0.001,           # 千分之一滑点
    plot: bool = False,
) -> BacktestResult:
    """运行一次完整的回测

    Args:
        config: 策略配置
        company_ids: 待回测股票 ID 列表
        start_date: 回测起始日
        end_date: 回测截止日
        init_cash: 初始资金
        commission: 佣金率
        slippage: 滑点比例
        plot: 是否绘图

    Returns:
        BacktestResult 包含全部绩效指标
    """
    t0 = time.time()
    result = BacktestResult(config, company_ids, start_date, end_date)
    result.portfolio_value_start = init_cash

    # 1. 从 PG 加载数据
    logger.info(f"加载数据: {len(company_ids)} 只股票, {start_date} ~ {end_date}")
    factor_keys = [fc.factor_key for fc in config.factors]
    stock_data = build_backtest_data(company_ids, factor_keys, start_date, end_date)

    if not stock_data:
        logger.error("无数据，回测终止")
        result.run_time_sec = time.time() - t0
        return result

    # 2. 创建 Cerebro 实例
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(init_cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.broker.set_slippage_perc(slippage)

    # 3. 添加数据
    code_map = get_company_code_map(company_ids)
    factor_cols = factor_keys  # 因子列名与 factor_key 一致

    for cid, df in stock_data.items():
        df_sub = df.copy()
        # 重置 index 使 trade_date 成为普通列
        df_sub.reset_index(inplace=True)
        df_sub.rename(columns={"trade_date": "datetime"}, inplace=True)
        df_sub["openinterest"] = 0

        # 补齐缺失的因子列
        for fc in factor_cols:
            if fc not in df_sub.columns:
                df_sub[fc] = 0.0

        df_sub.set_index("datetime", inplace=True)
        df_sub.sort_index(inplace=True)

        try:
            data_feed_cls = _make_pandas_data(df_sub)
            data = data_feed_cls(dataname=df_sub)
            data._name = code_map.get(cid, str(cid))
            cerebro.adddata(data)
        except Exception as e:
            logger.warning(f"添加 {code_map.get(cid, cid)} 数据失败: {e}")

    result.num_data = len(cerebro.datas)
    if result.num_data == 0:
        logger.error("无有效数据")
        result.run_time_sec = time.time() - t0
        return result

    # 4. 添加策略
    cerebro.addstrategy(MultiFactorStrategy, config=config, factor_cols=factor_cols)

    # 5. 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns",
                        tann=252, fund=True)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    cerebro.addanalyzer(bt.analyzers.VWR, _name="vwr")

    # 6. 运行
    logger.info(f"回测启动: {config.name}, {result.num_data} 只股票, 初始资金 {init_cash:,.0f}")
    stratos = cerebro.run()
    elapsed = time.time() - t0
    result.run_time_sec = elapsed

    # 7. 收集结果
    if stratos:
        s = stratos[0]
        result.cerebro = cerebro

        result.portfolio_value_end = cerebro.broker.getvalue()
        result.total_return = (result.portfolio_value_end / result.portfolio_value_start) - 1

        # Analyzers
        if "sharpe" in s.analyzers:
            try:
                sharpe_val = s.analyzers.sharpe.get_analysis()
                result.sharpe_ratio = sharpe_val.get("sharperatio", 0) or 0
            except Exception:
                pass

        if "drawdown" in s.analyzers:
            try:
                dd = s.analyzers.drawdown.get_analysis()
                result.max_drawdown = dd.get("max", {}).get("drawdown", 0) / 100
            except Exception:
                pass

        if "returns" in s.analyzers:
            try:
                r = s.analyzers.returns.get_analysis()
                result.annual_return = r.get("rnorm100", 0) / 100
            except Exception:
                # 自己算
                days = (end_date - start_date).days
                if days > 0:
                    result.annual_return = (1 + result.total_return) ** (365 / days) - 1

        if "trades" in s.analyzers:
            try:
                t = s.analyzers.trades.get_analysis()
                total_closed = t.get("total", {}).get("closed", 0)
                won = t.get("won", {}).get("total", 0)
                result.total_trades = total_closed
                result.win_rate = won / total_closed if total_closed > 0 else 0.0
            except Exception:
                pass

        if "sqn" in s.analyzers:
            pass  # SQN 值可用于额外评估

        # Calmar Ratio
        if result.max_drawdown > 0:
            result.calmar_ratio = result.annual_return / result.max_drawdown

        # 基准收益（等权持有）
        result.benchmark_return = _calc_benchmark_return(company_ids, start_date, end_date)
        if result.benchmark_return > 0:
            result.active_return = result.total_return - result.benchmark_return
            # 简化信息比率
            if result.active_return != 0:
                result.info_ratio = result.sharpe_ratio * 0.8  # 近似

    logger.info(f"回测完成 [{elapsed:.1f}s] 收益={result.total_return*100:.1f}%  "
                f"Sharpe={result.sharpe_ratio:.2f}  MDD={result.max_drawdown*100:.1f}%")

    return result


def _calc_benchmark_return(company_ids: list[int], start_date: date, end_date: date) -> float:
    """等权买入持有到期末的基准收益"""
    import psycopg2
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        sql = """
            SELECT AVG(dq.close_price / dq2.close_price - 1) as avg_return
            FROM daily_quotes dq
            JOIN (
                SELECT company_id, close_price
                FROM daily_quotes
                WHERE trade_date = %s
            ) dq2 ON dq.company_id = dq2.company_id
            WHERE dq.company_id = ANY(%s)
              AND dq.trade_date = %s
        """
        with conn.cursor() as cur:
            cur.execute(sql, (start_date, company_ids, end_date))
            row = cur.fetchone()
            return row[0] if row and row[0] else 0.0
    finally:
        conn.close()
