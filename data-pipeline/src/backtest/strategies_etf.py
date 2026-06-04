"""ETF动量-风控双因子轮动策略 — Backtrader 策略实现

策略规则（用户定义）：
1. 调仓频率：每月（每月最后一个交易日收盘后计算，T+1执行）
2. 持仓：Top 4 ETF，等权配置
3. 复权：前复权价格用于因子计算
4. 动量因子：20日年化收益 × R²
5. 风控因子：波动率 + 成交额CV
6. 综合得分：α×动量排名 - β×风险排名（α=β=1）
7. 止损：单只ETF亏损超-5%立即止损
8. 降仓：高波动ETF降50%仓位
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import backtrader as bt
import numpy as np
import pandas as pd

from src.backtest.feeds_etf import (
    build_etf_backtest_data,
    compute_all_factors,
    compute_momentum_factor,
    compute_risk_factor,
)

logger = logging.getLogger(__name__)


@dataclass
class ETFBacktestConfig:
    """ETF轮动策略配置"""
    name: str = "etf_momentum_risk_strategy"
    # 候选ETF
    etf_codes: list[str] = field(default_factory=list)
    # 持仓数量
    hold_count: int = 4
    # 再平衡周期（天）
    rebalance_days: int = 21  # 约每月
    # 动量窗口
    momentum_window: int = 20
    # 风控窗口
    risk_window: int = 20
    # 止损线
    stop_loss_pct: float = -0.05  # -5%
    # 降仓波动率阈值（百分位）
    reduce_threshold: float = 0.80  # 波动率排名前80%时降仓
    # 降仓比例
    reduce_ratio: float = 0.50  # 降50%
    # 单只最大仓位
    max_position_pct: float = 0.30  # 30%
    # 因子权重
    alpha_weight: float = 1.0
    beta_weight: float = 1.0
    # 初始资金
    initial_cash: float = 1000000.0


class ETFMomentumRiskStrategy(bt.Strategy):
    """ETF动量-风控双因子轮动策略"""

    params = (
        ("config", None),          # ETFBacktestConfig 实例
        ("etf_data", None),       # {code: df} 预加载的ETF数据
        ("rebalance_days", 21),
        ("momentum_window", 20),
        ("stop_loss_pct", -0.05),
        ("reduce_threshold", 0.80),
        ("reduce_ratio", 0.50),
        ("hold_count", 4),
        ("max_position_pct", 0.30),
        ("alpha_weight", 1.0),
        ("beta_weight", 1.0),
    )

    def __init__(self):
        self.config = self.params.config
        self.etf_data = self.params.etf_data or {}
        self.rebalance_bar = 0
        self.last_rebalance_date = None
        self.orders = {}   # {data: order}
        self.position_entry_prices = {}  # {data: entry_price}
        self.month_end_dates = self._compute_month_ends()
        self.pending_rebalance = False

    def _compute_month_ends(self) -> list:
        """计算回测区间内的月末日期列表（用于触发调仓）"""
        if not self.etf_data:
            return []

        # 取所有ETF中最长的时间范围
        all_dates = set()
        for df in self.etf_data.values():
            all_dates.update(df.index.tolist())
        if not all_dates:
            return []

        dates = sorted(all_dates)
        month_ends = set()
        for d in dates:
            # 统一转换为 date 类型
            d_date = d.date() if hasattr(d, 'date') else d
            year = d_date.year
            month = d_date.month
            # 该月最后一天
            if month == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month + 1, 1)
            month_end = next_month - timedelta(days=1)
            if d_date == month_end:
                month_ends.add(d_date)

        return sorted(month_ends)

    def log(self, txt, dt=None):
        try:
            dt = dt or self.datas[0].datetime.date(0)
        except Exception:
            dt = "N/A"
        logger.debug(f"{dt} {txt}")

    def notify_order(self, order):
        """订单状态更新"""
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY COMPLETED: {order.data._name}, price={order.executed.price:.4f}, size={order.executed.size}")
            elif order.issell():
                self.log(f"SELL COMPLETED: {order.data._name}, price={order.executed.price:.4f}, size={order.executed.size}")

    def next(self):
        """每日调用"""
        try:
            current_date = self.datas[0].datetime.date(0)
        except Exception:
            return

        # ── 止损检查：每日检查所有持仓 ──────────────────────
        self._check_stop_loss(current_date)

        # ── 月末再平衡 ─────────────────────────────────────
        if current_date in self.month_end_dates:
            self._do_rebalance(current_date)

    def _check_stop_loss(self, current_date):
        """检查止损：单只ETF亏损超过阈值立即清仓"""
        for d in self.datas:
            if d._name not in self.position_entry_prices:
                continue

            pos = self.getposition(d)
            if pos.size <= 0:
                continue

            entry_price = self.position_entry_prices[d._name]
            current_price = d.close[0]
            if current_price <= 0 or entry_price <= 0:
                continue

            pnl_pct = (current_price / entry_price) - 1

            if pnl_pct < self.params.stop_loss_pct:
                self.log(f"STOP LOSS triggered: {d._name} pnl={pnl_pct:.2%} entry={entry_price:.4f} curr={current_price:.4f}")
                self.close(data=d)
                if d in self.orders:
                    self.orders[d] = None
                self.position_entry_prices.pop(d._name, None)

    def _do_rebalance(self, rebalance_date):
        """月末调仓逻辑

        T日（月末）收盘后计算动量+风控因子
        T+1日开盘执行（Backtrader next()在下个bar自动以当日收盘价模拟执行）
        """
        self.log(f"=== REBALANCE at {rebalance_date} ===")

        # ── 步骤1：计算所有候选ETF的因子 ──────────────────
        factor_df = compute_all_factors(self.etf_data, window=self.params.momentum_window)

        if factor_df.empty:
            self.log("无有效因子数据，跳过本次调仓")
            return

        # 过滤掉缺失动量因子的ETF
        factor_df = factor_df.dropna(subset=["momentum"])
        if len(factor_df) < self.params.hold_count:
            self.log(f"候选ETF不足 {len(factor_df)} < {self.params.hold_count}，跳过本次调仓")
            return

        # ── 步骤2：按综合得分排序选Top N ───────────────────
        factor_df = factor_df.sort_values("composite_score", ascending=False)
        top_etfs = factor_df.head(self.params.hold_count)
        selected_codes = top_etfs.index.tolist()

        self.log(f"选中ETF: {selected_codes}")
        self.log(f"因子详情:\n{top_etfs[['momentum', 'volatility', 'cv_amount', 'composite_score']].to_string()}")

        # ── 步骤3：确定目标持仓 ──────────────────────────
        # 计算目标仓位（等权，考虑降仓）
        total_value = self.broker.getvalue()
        target_weights = {}

        for code in selected_codes:
            row = top_etfs.loc[code]

            # 高波动降仓
            vol_pct = row.get("volatility_pct", 0.5)
            if vol_pct >= self.params.reduce_threshold:
                weight = (1.0 / self.params.hold_count) * self.params.reduce_ratio
                self.log(f"降仓: {code} 波动率百分位={vol_pct:.2f} 仓位={weight:.2%}")
            else:
                weight = 1.0 / self.params.hold_count

            target_weights[code] = weight

        # ── 步骤4：调仓操作 ────────────────────────────────
        # 先平仓不在候选池的ETF
        current_holdings = {d._name: self.getposition(d) for d in self.datas}

        for d in self.datas:
            code = d._name
            if code not in selected_codes and current_holdings.get(d, bt.position.Position()).size > 0:
                self.log(f"平仓（不在候选池）: {code}")
                self.close(data=d)
                self.position_entry_prices.pop(code, None)
                self.orders[d] = None

        # 再按目标权重买入
        for code in selected_codes:
            target_weight = target_weights[code]
            target_value = total_value * target_weight

            # 找到对应的data
            d_target = None
            for d in self.datas:
                if d._name == code:
                    d_target = d
                    break

            if d_target is None:
                continue

            current_pos = self.getposition(d_target)
            current_value = current_pos.size * d_target.close[0] if current_pos.size > 0 else 0

            # 仓位差异超过5%才调仓（减少频繁交易）
            weight_diff = abs(target_value - current_value) / total_value
            if weight_diff < 0.05:
                self.log(f"仓位差异小，跳过: {code} diff={weight_diff:.2%}")
                continue

            # 执行买入/调仓
            needed_value = target_value - current_value
            price = d_target.close[0]

            if price <= 0 or not np.isfinite(price):
                self.log(f"跳过: {code} price={price}无效")
                continue

            if not np.isfinite(needed_value):
                self.log(f"跳过: {code} needed_value={needed_value}无效")
                continue

            size = int(needed_value / price)
            if size > 0:
                self.buy(data=d_target, size=size)
                self.log(f"买入: {code} price={price:.4f} size={size} 目标权重={target_weight:.2%}")
                self.position_entry_prices[code] = price
            elif size < 0:
                self.close(data=d_target)
                self.log(f"卖出（降仓）: {code} size={size}")
                if code in self.position_entry_prices:
                    del self.position_entry_prices[code]

    def stop(self):
        """回测结束"""
        self.log(f"=== 回测结束，最终净值: {self.broker.getvalue():.2f} ===")


def run_etf_backtest(
    config: ETFBacktestConfig,
    start_date: date,
    end_date: date,
) -> dict:
    """运行ETF回测的主入口

    Args:
        config: ETFBacktestConfig 配置
        start_date: 回测开始日期
        end_date: 回测结束日期

    Returns:
        回测结果字典
    """
    logger.info(f"开始ETF回测: {config.name}")
    logger.info(f"候选ETF: {config.etf_codes}")
    logger.info(f"回测区间: {start_date} ~ {end_date}")

    # ── 步骤1：加载数据 ────────────────────────────────────
    etf_data = build_etf_backtest_data(
        config.etf_codes,
        start_date=start_date,
        end_date=end_date,
        lookback_days=max(config.momentum_window, config.risk_window) * 3,
    )

    if not etf_data:
        logger.error("无ETF数据，回测失败")
        return {"error": "no data"}

    logger.info(f"数据加载完成: {list(etf_data.keys())}")

    # ── 步骤2：构建Backtrader Cerebro ──────────────────────
    cerebro = bt.Cerebro(optreturn=False)

    # 设置初始资金
    cerebro.broker.setcash(config.initial_cash)

    # 佣金：ETF万0.5（0.00005），单边收取
    cerebro.broker.setcommission(commission=0.00005, margin=None)

    # 滑点（万一）
    cerebro.broker.set_slippage_fixed(0.0001)

    # 添加数据feed
    for code, df in etf_data.items():
        if df.empty or len(df) < 30:
            logger.warning(f"跳过数据不足的ETF: {code} ({len(df)} bars)")
            continue

        # 构建Backtrader可用的pandas DataFrame
        data_feed = bt.feeds.PandasData(
            dataname=df,
            datetime=None,       # index作为datetime
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
        )
        cerebro.adddata(data_feed, name=code)

    # 添加策略
    cerebro.addstrategy(
        ETFMomentumRiskStrategy,
        config=config,
        etf_data=etf_data,
        rebalance_days=config.rebalance_days,
        momentum_window=config.momentum_window,
        stop_loss_pct=config.stop_loss_pct,
        reduce_threshold=config.reduce_threshold,
        reduce_ratio=config.reduce_ratio,
        hold_count=config.hold_count,
        max_position_pct=config.max_position_pct,
        alpha_weight=config.alpha_weight,
        beta_weight=config.beta_weight,
    )

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03, annualize=True)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    # ── 步骤3：运行回测 ───────────────────────────────────
    logger.info(f"初始资金: {cerebro.broker.getvalue():.2f}")
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    logger.info(f"回测结束，最终净值: {final_value:.2f}")

    # ── 步骤4：收集分析结果 ────────────────────────────────
    strat = results[0]
    result = {
        "strategy_name": config.name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_cash": config.initial_cash,
        "final_value": final_value,
        "total_return": (final_value / config.initial_cash - 1),
        "etf_codes": config.etf_codes,
        "hold_count": config.hold_count,
    }

    # 提取分析器结果
    analyzers = strat.analyzers

    # Returns analyzer
    if hasattr(analyzers, 'returns'):
        ret = analyzers.returns.rets
        result["annual_return"] = ret.get('rtot', 0)
        result["total_return_an"] = ret.get('rnorm100', 0) / 100 if 'rnorm100' in ret else 0

    # DrawDown analyzer
    if hasattr(analyzers, 'drawdown'):
        dd = analyzers.drawdown.rets
        result["max_drawdown"] = dd.get('max', {}).get('drawdown', 0) / 100 if 'max' in dd else 0

    # SharpeRatio analyzer
    if hasattr(analyzers, 'sharpe'):
        sr = analyzers.sharpe.rets
        result["sharpe_ratio"] = sr.get('sharperatio', 0)

    # TradeAnalyzer
    if hasattr(analyzers, 'trades'):
        ta = analyzers.trades.rets
        total_closed = ta.get('total', {}).get('closed', 0)
        result["total_trades"] = int(ta.get('total', {}).get('total', 0))
        won_count = int(ta.get('won', {}).get('total', 0))
        lost_count = int(ta.get('lost', {}).get('total', 0))
        result["win_rate"] = won_count / max(total_closed, 1)
        
        # 盈亏计算：使用 gross（未扣佣金）更准确反映策略本身
        avg_win = ta.get('won', {}).get('pnl', {}).get('average', 0) or 0
        avg_loss = abs((ta.get('lost', {}).get('pnl', {}).get('average', 0) or 0))
        
        # 盈亏比：avg_win / avg_loss（盈利交易平均收益 / 亏损交易平均损失）
        result["profit_loss_ratio"] = avg_win / max(avg_loss, 0.01)
        result["avg_win"] = avg_win
        result["avg_loss"] = avg_loss
        result["won_trades"] = won_count
        result["lost_trades"] = lost_count
    else:
        result["total_trades"] = 0
        result["win_rate"] = 0
        result["profit_loss_ratio"] = 0
        result["avg_win"] = 0
        result["avg_loss"] = 0
        result["won_trades"] = 0
        result["lost_trades"] = 0

    # 卡玛比率
    if result["max_drawdown"] != 0:
        result["calmar_ratio"] = result["annual_return"] / abs(result["max_drawdown"])
    else:
        result["calmar_ratio"] = 0

    return result