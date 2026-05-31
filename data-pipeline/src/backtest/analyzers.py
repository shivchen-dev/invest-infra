"""绩效分析 — 回测结果的高级指标和对比分析

提供基于 VectorBT 的快速因子扫描和 IC 分析，
以及结合回测结果的多维度绩效评估。
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

import vectorbt as vbt

from src.backtest.feeds import load_market_data, load_factor_signals
from src.backtest.engine import BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class FactorICReport:
    """单因子的 IC 分析报告"""
    factor_key: str
    rank_ic_mean: float = 0.0
    rank_ic_std: float = 0.0
    rank_ic_ir: float = 0.0
    rank_ic_positive_pct: float = 0.0
    ic_decay: list[float] = field(default_factory=list)


def compute_rank_ic(
    company_ids: list[int],
    factor_key: str,
    start_date: date,
    end_date: date,
    forward_days: int = 5,
) -> FactorICReport:
    """计算截面 Rank IC（秩相关系数）"""
    # 加载因子值
    fac = load_factor_signals(company_ids, [factor_key], start_date, end_date,
                              use_percentile=False)
    # 加载未来收益
    mkt = load_market_data(company_ids, start_date,
                           end_date + pd.Timedelta(days=forward_days + 5))

    if fac.empty or mkt.empty:
        return FactorICReport(factor_key=factor_key)

    ic_values = []
    # 遍历每个交易日
    for dt in fac.index.get_level_values("trade_date").unique():
        try:
            # 当日因子截面
            today_fac = fac.xs(dt, level="trade_date") if not fac.empty else None
            if today_fac is None or today_fac.empty:
                continue

            # 未来 forward_days 收益
            future_dt = dt + pd.Timedelta(days=forward_days)
            # 找未来最近的交易日
            try:
                future_prices = mkt.xs(future_dt, level="trade_date") if future_dt in mkt.index.get_level_values("trade_date") else None
                today_prices = mkt.xs(dt, level="trade_date") if dt in mkt.index.get_level_values("trade_date") else None
            except KeyError:
                continue

            if future_prices is None or today_prices is None:
                continue

            fwd_return = (future_prices["close"] / today_prices["close"] - 1)

            # 对齐
            common = today_fac.index.intersection(fwd_return.index)
            if len(common) < 5:
                continue

            fac_vals = today_fac.loc[common, factor_key]
            ret_vals = fwd_return.loc[common]

            # Spearman Rank IC
            from scipy.stats import spearmanr
            r, _ = spearmanr(fac_vals, ret_vals)
            if not np.isnan(r):
                ic_values.append(r)
        except Exception:
            continue

    report = FactorICReport(factor_key=factor_key)
    if ic_values:
        ic_arr = np.array(ic_values)
        report.rank_ic_mean = float(np.mean(ic_arr))
        report.rank_ic_std = float(np.std(ic_arr))
        report.rank_ic_ir = report.rank_ic_mean / report.rank_ic_std if report.rank_ic_std > 0 else 0
        report.rank_ic_positive_pct = float(np.sum(ic_arr > 0) / len(ic_arr))

    return report


def vectorbt_quick_scan(
    company_ids: list[int],
    factor_keys: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, dict]:
    """使用 VectorBT 快速扫描因子表现（Top/Bottom 分位数收益差）"""
    logger.info(f"VectorBT 快速扫描: {len(factor_keys)} 个因子, {len(company_ids)} 只股票")

    mkt = load_market_data(company_ids, start_date, end_date)
    fac = load_factor_signals(company_ids, factor_keys, start_date, end_date,
                              use_percentile=True)

    if mkt.empty or fac.empty:
        return {}

    results = {}
    for fk in factor_keys:
        try:
            # 每日截面：按因子百分位分层
            dates = sorted(fac.index.get_level_values("trade_date").unique())
            top_returns = []
            bot_returns = []

            for dt in dates:
                try:
                    day_fac = fac.xs(dt, level="trade_date")
                    if fk not in day_fac.columns:
                        continue
                    day_fac = day_fac.dropna(subset=[fk])

                    if len(day_fac) < 4:
                        continue

                    # Top 20% vs Bottom 20%
                    threshold_top = day_fac[fk].quantile(0.8)
                    threshold_bot = day_fac[fk].quantile(0.2)

                    top_ids = day_fac[day_fac[fk] >= threshold_top].index
                    bot_ids = day_fac[day_fac[fk] <= threshold_bot].index

                    # 次日收益
                    next_dt = dt + pd.Timedelta(days=1)
                    if next_dt not in mkt.index.get_level_values("trade_date"):
                        # 找下一个交易日
                        all_dates = sorted(mkt.index.get_level_values("trade_date").unique())
                        idx = all_dates.index(dt) if dt in all_dates else -1
                        if idx < 0 or idx + 1 >= len(all_dates):
                            continue
                        next_dt = all_dates[idx + 1]

                    try:
                        today_close = mkt.xs(dt, level="trade_date")["close"]
                        next_close = mkt.xs(next_dt, level="trade_date")["close"]
                    except KeyError:
                        continue

                    ret = (next_close / today_close - 1)

                    top_ret = ret.reindex(top_ids).mean()
                    bot_ret = ret.reindex(bot_ids).mean()

                    if not np.isnan(top_ret) and not np.isnan(bot_ret):
                        top_returns.append(top_ret)
                        bot_returns.append(bot_ret)
                except Exception:
                    continue

            if top_returns and bot_returns:
                top_arr = np.array(top_returns)
                bot_arr = np.array(bot_returns)
                spread = np.mean(top_arr - bot_arr)
                results[fk] = {
                    "top_mean_return": float(np.mean(top_arr)),
                    "bot_mean_return": float(np.mean(bot_arr)),
                    "spread_return": float(spread),
                    "top_win_rate": float(np.mean(top_arr > 0)),
                    "num_observations": len(top_returns),
                }
        except Exception as e:
            logger.warning(f"因子 {fk} 扫描失败: {e}")

    return results


def compare_strategies(results: list[BacktestResult]) -> pd.DataFrame:
    """多策略对比 DataFrame"""
    rows = []
    for r in results:
        d = r.to_dict()
        d.pop("run_time_sec", None)
        rows.append(d)
    return pd.DataFrame(rows).set_index("strategy")
