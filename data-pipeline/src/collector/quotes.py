"""日行情数据采集器 — 通过 akshare 获取 A 股日线行情 (Sina API)"""

import logging
from datetime import date, timedelta
from typing import Optional

import akshare as ak

from src.collector.retry import with_retry
from src.config import collector

logger = logging.getLogger(__name__)


def _sina_symbol(raw_code: str, market: str = "SH") -> str:
    """转为新浪格式: sh600519 / sz000001"""
    return f"{market.lower()}{raw_code}"


def _market_for_code(raw_code: str) -> str:
    if raw_code.startswith("6"):
        return "SH"
    elif raw_code.startswith("0") or raw_code.startswith("3"):
        return "SZ"
    elif raw_code.startswith("8") or raw_code.startswith("4") or raw_code.startswith("92"):
        return "BJ"
    raise ValueError(f"未知市场代码: {raw_code}")


@with_retry()
def fetch_quotes(
    stock_code: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    adjust: str = "qfq",
) -> list[dict]:
    """获取单只股票的日行情数据（通过新浪财经接口）"""
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=collector.quotes_history_days)

    raw_code = stock_code.split(".")[0]
    market = stock_code.split(".")[1] if "." in stock_code else _market_for_code(raw_code)
    symbol = _sina_symbol(raw_code, market)

    logger.info(f"正在获取 {symbol} 行情 [{start_date} ~ {end_date}]")
    try:
        df = ak.stock_zh_a_daily(
            symbol=symbol,
            adjust=adjust,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
    except Exception as e:
        logger.error(f"{symbol} 行情获取失败: {e}", exc_info=True)
        return []

    if df is None or df.empty:
        return []

    # 字段映射
    field_map = {
        "date": "trade_date",
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
        "volume": "volume",
        "amount": "amount",
        "turnover": "turnover_rate",
    }

    # 计算 pre_close 用于标准涨跌幅（替代昨收）
    df["pre_close"] = df["close"].shift(1)
    df["change_pct"] = ((df["close"] - df["pre_close"]) / df["pre_close"] * 100).round(4)

    records = []
    for row in df.to_dict('records'):
        r = {"stock_code": stock_code, "source": "akshare-sina"}
        for src, dst in field_map.items():
            v = row.get(src)
            if v is not None:
                try:
                    r[dst] = float(v) if dst != "trade_date" else row["date"]
                except (ValueError, TypeError):
                    pass
            else:
                r[dst] = None
        # 涨跌幅使用 pre_close 计算的标准值
        cp = row.get("change_pct")
        if cp is not None and not (isinstance(cp, float) and (cp != cp)):  # not NaN
            r["change_pct"] = cp
        records.append(r)

    logger.info(f"{symbol} 获取到 {len(records)} 条日线")
    return records
