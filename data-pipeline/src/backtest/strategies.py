"""策略模板 — 基于因子信号的 Backtrader 策略

核心思路：
  因子信号（percentile/zscore）→ 多因子加权合成 → 阈值触发交易
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import backtrader as bt
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorSignalConfig:
    """单个因子的信号配置"""
    factor_key: str
    weight: float = 1.0          # 因子权重
    threshold_entry: float = 0.7  # 百分位阈值（高于此值开多）
    threshold_exit: float = 0.5   # 百分位阈值（低于此值平多）
    higher_better: bool = True    # 是否越大越好


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str = "multi_factor_strategy"
    factors: list[FactorSignalConfig] = field(default_factory=list)
    top_n: int = 0                # 0=使用阈值, >0=选前N只
    max_position_pct: float = 0.25  # 每只股票最大仓位
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rebalance_days: int = 5       # 每N个交易日再平衡


class MultiFactorStrategy(bt.Strategy):
    """多因子加权合成策略 — 核心回测逻辑"""

    params = (
        ("config", None),         # StrategyConfig 实例
        ("factor_cols", []),      # 因子在数据中的列名列表
    )

    def __init__(self):
        self.config: StrategyConfig = self.params.config
        self.orders = {}          # {data: order}
        self.rebalance_bar = 0

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        logger.debug(f"{dt.isoformat()} {txt}")

    def next(self):
        """每日调用 — 核心信号逻辑"""
        # 检查再平衡周期
        self.rebalance_bar += 1
        if self.rebalance_bar % self.params.config.rebalance_days != 0:
            return

        # 计算每只股票的综合因子得分
        scores = []
        for i, d in enumerate(self.datas):
            if len(d) < 1:
                continue
            line = d.close[0]
            if line is None or pd.isna(line):
                continue

            score = self._calc_composite_score(d)
            if score is not None:
                scores.append((i, d, score))

        if not scores:
            return

        # 按得分排序
        scores.sort(key=lambda x: x[2], reverse=True)

        # 阈值模式 或 Top-N 模式
        if self.params.config.top_n > 0:
            selected = scores[:self.params.config.top_n]
        else:
            selected = [s for s in scores if s[2] >= self.params.config.threshold_entry]

        selected_indices = {s[0] for s in selected}
        selected_scores = {s[0]: s[2] for s in selected}

        # 平仓不满足条件的
        for i, d in enumerate(self.datas):
            if i in self.orders and self.orders[i] is not None:
                continue

            pos = self.getposition(d)
            if pos.size > 0:
                if i not in selected_indices:
                    self.orders[i] = self.close(data=d)
                    self.log(f"CLOSE  data[{i}]  (score not in top/threshold)")

        # 开仓/加仓选中的
        for i, d, score in selected:
            if i in self.orders and self.orders[i] is not None:
                continue

            pos = self.getposition(d)
            target_value = self.broker.getvalue() * self.params.config.max_position_pct

            if pos.size == 0:
                # 开仓
                size = int(target_value / d.close[0]) if d.close[0] > 0 else 0
                if size > 0:
                    self.orders[i] = self.buy(data=d, size=size)
                    self.log(f"BUY   data[{i}]  score={score:.3f}  size={size}")
            # 已有仓位 — 暂不调整（rebalance周期内持有）

    def _calc_composite_score(self, data):
        """计算单只股票的综合因子得分"""
        total = 0.0
        weight_sum = 0.0
        for fc in self.params.factors:
            col = fc.factor_key
            if col not in self.params.factor_cols:
                continue
            try:
                col_idx = self.params.factor_cols.index(col)
                val = data.lines[col_idx][0]
            except (IndexError, AttributeError):
                continue

            if val is None or pd.isna(val):
                continue

            signal = val if fc.higher_better else (1.0 - val)
            total += signal * fc.weight
            weight_sum += abs(fc.weight)

        return total / weight_sum if weight_sum > 0 else None


class SimpleMAStrategy(bt.Strategy):
    """简单双均线策略 — 作为 Baseline 对比"""

    params = (
        ("fast", 10),
        ("slow", 30),
    )

    def __init__(self):
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.params.fast)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def make_signal_config(
    factor_keys: list[str],
    weights: Optional[list[float]] = None,
    higher_better: Optional[list[bool]] = None,
    threshold_entry: float = 0.7,
    threshold_exit: float = 0.5,
    top_n: int = 0,
    max_pos_pct: float = 0.25,
    rebalance_days: int = 5,
) -> StrategyConfig:
    """便捷工厂：从因子列表生成策略配置"""
    if weights is None:
        weights = [1.0] * len(factor_keys)
    if higher_better is None:
        higher_better = [True] * len(factor_keys)

    factors = [
        FactorSignalConfig(
            factor_key=fk, weight=w, higher_better=hb,
            threshold_entry=threshold_entry, threshold_exit=threshold_exit,
        )
        for fk, w, hb in zip(factor_keys, weights, higher_better)
    ]

    return StrategyConfig(
        name="+" .join(factor_keys),
        factors=factors,
        top_n=top_n,
        max_position_pct=max_pos_pct,
        rebalance_days=rebalance_days,
    )
