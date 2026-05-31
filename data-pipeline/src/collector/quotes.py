"""日行情数据采集器 — 通过 akshare 获取 A 股日线行情 (Sina API)"""

import logging
from datetime import date, timedelta
from typing import Optional

import akshare as ak

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
    return "SH"


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
        logger.warning(f"{symbol} 行情获取失败: {e}")
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
    }

    records = []
    for _, row in df.iterrows():
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
        # 计算涨跌幅（如果没有）
        if r.get("close_price") and r.get("open_price"):
            r["change_pct"] = round((r["close_price"] - r["open_price"]) / r["open_price"] * 100, 4)
        records.append(r)

    logger.info(f"{symbol} 获取到 {len(records)} 条日线")
    return records
