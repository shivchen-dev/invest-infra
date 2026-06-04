"""PG → ETF Backtrader DataFeed 适配器

从 PostgreSQL etf_quotes / etfs 表加载ETF行情数据和因子信号，
转为 Backtrader 可消费的 pandas DataFrame。
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2

from src.config import pg as pg_cfg

logger = logging.getLogger(__name__)


def load_etf_quotes(
    etf_codes: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """从 etf_quotes 加载ETF日K线数据

    Returns:
        DataFrame indexed by (code, trade_date), columns=[open,high,low,close,volume,amount]
    """
    sql = """
        SELECT e.code, eq.trade_date,
               eq.open_price, eq.high_price, eq.low_price, eq.close_price,
               eq.volume, eq.amount,
               eq.premium_rate, eq.iopv, eq.turnover_rate, eq.change_pct, eq.amplitude
        FROM etf_quotes eq
        JOIN etfs e ON eq.etf_id = e.id
        WHERE e.code = ANY(%s)
          AND eq.trade_date BETWEEN %s AND %s
        ORDER BY e.code, eq.trade_date
    """
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        df = pd.read_sql(sql, conn, params=(etf_codes, start_date, end_date),
                         parse_dates=["trade_date"])
        df.set_index(["code", "trade_date"], inplace=True)
        # 列名标准化
        df.columns = [c.replace("_price", "") for c in df.columns]
        return df
    finally:
        conn.close()


def get_etf_id_map(etf_codes: list[str]) -> dict[str, int]:
    """{code: etf_id} 映射"""
    conn = psycopg2.connect(pg_cfg.uri)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, id FROM etfs WHERE code = ANY(%s)", (etf_codes,))
            return dict(cur.fetchall())
    finally:
        conn.close()


def build_etf_backtest_data(
    etf_codes: list[str],
    start_date: date,
    end_date: date,
    lookback_days: int = 60,
) -> dict[str, pd.DataFrame]:
    """组装每只ETF的回测数据集（OHLCV + 复权价格计算）

    复权处理：检测分红送股跳空，用累计收益率还原复权价格

    Args:
        etf_codes: ETF代码列表
        start_date: 回测开始日期
        end_date: 回测结束日期
        lookback_days: 向前多取N天用于因子计算（前复权需要更长历史）

    Returns:
        {code: DataFrame(index=trade_date, columns=[open,high,low,close,volume,amount,close_adjusted]))}
    """
    # 多取一些历史用于复权计算
    adj_start = start_date - timedelta(days=lookback_days * 2)
    df = load_etf_quotes(etf_codes, adj_start, end_date)

    if df.empty:
        logger.warning("无ETF数据返回")
        return {}

    result = {}
    for code in df.index.get_level_values("code").unique():
        try:
            daily = df.xs(code, level="code").copy()
        except KeyError:
            continue

        if daily.empty or len(daily) < 30:
            continue

        # ── 复权计算 ──────────────────────────────────────────
        # 检测除权跳空：当日收盘价 vs 前日收盘价发生大幅不成比例下跌
        close_raw = daily["close"].copy()
        close_raw = pd.to_numeric(close_raw, errors="coerce").dropna()
        if len(close_raw) < 20:
            continue

        # 计算每日收益率
        returns = close_raw.pct_change()

        # 检测跳空（单日跌幅>5%且次日未反弹）：认为是除权分红
        adjustment_factors = [1.0]
        for i in range(1, len(close_raw)):
            prev = float(close_raw.iloc[i - 1])
            curr = float(close_raw.iloc[i])
            if prev <= 0:
                adjustment_factors.append(1.0)
                continue

            raw_ret = curr / prev - 1

            # 跳空检测：当日下跌>5% 且次日未收复
            if raw_ret < -0.05 and i < len(close_raw) - 1:
                next_ret = float(close_raw.iloc[i + 1]) / curr - 1 if curr > 0 else 0
                if next_ret < abs(raw_ret) * 0.5:
                    # 是除权，跳空当日需要向后累积修复
                    factor = prev / curr  # 修复因子
                    adjustment_factors.append(factor)
                    logger.debug(f"检测到除权: {code} 日期={close_raw.index[i]} 跌幅={raw_ret:.2%} 因子={factor:.4f}")
                else:
                    adjustment_factors.append(1.0)
            else:
                adjustment_factors.append(1.0)

        # 简化方案：只对 detected 除权日做累计复权
        # 重新计算：用收益率序列还原"前复权"价格
        cumulative_factor = pd.Series(adjustment_factors[:len(close_raw)], index=close_raw.index).cumprod()
        close_adjusted = close_raw * cumulative_factor / cumulative_factor.iloc[-1]  # 归一化到最新价

        daily["close_adjusted"] = close_adjusted
        daily["return_raw"] = returns

        # 排序
        daily.sort_index(inplace=True)
        result[code] = daily

    logger.info(f"ETF数据加载完成: {len(result)}/{len(etf_codes)} 只有效")
    return result


def compute_momentum_factor(df: pd.DataFrame, window: int = 20) -> float:
    """
    动量因子 = 年化收益率 × R²
    年化收益率 = (C_t / C_{t-n})^(252/n) - 1
    R² = 线性回归拟合优度（时间 vs 收益率）

    Args:
        df: 单只ETF日线DataFrame，需含 close_adjusted 列
        window: 计算窗口，默认20日

    Returns:
        动量因子得分（float，None表示数据不足）
    """
    close = df["close_adjusted"].dropna()
    if len(close) < window + 1:
        return None

    prices = close.iloc[-window:].values
    # 年化收益率
    r_start = prices[0]
    r_end = prices[-1]
    if r_start <= 0 or r_end <= 0:
        return None

    # 年化收益率（线性年化，不用复合公式，避免短窗口极端值）
    daily_returns = np.diff(prices) / prices[:-1]  # 日收益率序列
    mean_daily = np.mean(daily_returns)
    annual_return = mean_daily * 252

    # R²：收益率对时间的线性回归
    x = np.arange(len(prices))
    y = np.diff(prices) / prices[:-1]  # 日收益率序列
    if len(y) < 5:
        return None

    # 简单线性回归：y = alpha + beta * x + epsilon
    x_fit = x[1:]  # 对齐收益率长度
    n = len(x_fit)
    x_mean = np.mean(x_fit)
    y_mean = np.mean(y)
    ss_xy = np.sum((x_fit - x_mean) * (y - y_mean))
    ss_xx = np.sum((x_fit - x_mean) ** 2)
    if ss_xx == 0:
        return None
    beta = ss_xy / ss_xx
    alpha = y_mean - beta * x_mean

    # R² 计算
    y_pred = alpha + beta * x_fit
    ss_total = np.sum((y - y_mean) ** 2)
    ss_res = np.sum((y - y_pred) ** 2)
    r_squared = 1 - ss_res / ss_total if ss_total != 0 else 0

    momentum = annual_return * r_squared
    return float(momentum)


def compute_risk_factor(df: pd.DataFrame, window: int = 20) -> dict:
    """
    风控因子：
    1. 波动率 = std(20日收益率)
    2. 成交额变异系数 = std(20日成交额) / mean(20日成交额)

    Returns:
        dict: {volatility, cv_amount, risk_score}
        risk_score = percentile_rank(volatility) * 0.6 + percentile_rank(cv_amount) * 0.4
    """
    returns = df["return_raw"].dropna().iloc[-window:]
    amount = pd.to_numeric(df["amount"], errors="coerce").dropna().iloc[-window:]

    if len(returns) < 10 or len(amount) < 10:
        return {"volatility": None, "cv_amount": None, "risk_score": None}

    vol = float(returns.std())
    cv = float(amount.std() / amount.mean()) if amount.mean() != 0 else None

    return {"volatility": vol, "cv_amount": cv, "risk_score": None}


def compute_all_factors(
    etf_data: dict[str, pd.DataFrame],
    window: int = 20,
) -> pd.DataFrame:
    """
    对所有ETF计算动量+风控因子，返回因子矩阵

    Returns:
        DataFrame: index=code, columns=[momentum, volatility, cv_amount, risk_score, composite_score]
    """
    rows = []
    for code, df in etf_data.items():
        mom = compute_momentum_factor(df, window)
        risk = compute_risk_factor(df, window)

        row = {
            "code": code,
            "momentum": mom,
            "volatility": risk["volatility"],
            "cv_amount": risk["cv_amount"],
        }
        rows.append(row)

    factor_df = pd.DataFrame(rows).set_index("code")

    # 百分位排名（风险：波动率越高分数越高 = 越危险）
    for col in ["momentum", "volatility", "cv_amount"]:
        factor_df[f"{col}_pct"] = factor_df[col].rank(pct=True, ascending=True, method="average")

    # 风险分数：波动率60% + 成交额CV40%
    factor_df["risk_score"] = factor_df["volatility_pct"] * 0.6 + factor_df["cv_amount_pct"] * 0.4

    # 综合得分 = 动量排名 - 风险排名（动量高+风险低 → 得分高）
    factor_df["composite_score"] = factor_df["momentum_pct"] - factor_df["risk_score"]

    return factor_df