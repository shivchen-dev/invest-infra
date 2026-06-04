"""舆情数据采集器 — 通过 akshare 东方财富接口获取个股新闻"""

import logging
from datetime import datetime, date
from dateutil import parser as date_parser
from typing import Optional

import akshare as ak

from src.collector.retry import with_retry

logger = logging.getLogger(__name__)


@with_retry()
def fetch_stock_news(stock_code: str) -> list[dict]:
    """获取个股新闻（东方财富源）"""
    raw_code = stock_code.split(".")[0]
    logger.info(f"正在获取 {raw_code} 新闻 ...")

    try:
        df = ak.stock_news_em(symbol=raw_code)
    except Exception as e:
        logger.error(f"{raw_code} 新闻获取失败: {e}", exc_info=True)
        return []

    if df is None or df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        records.append({
            "stock_code": stock_code,
            "title": str(row.get("新闻标题", "")),
            "content_summary": (lambda c: str(c)[:500] if c else "")(row.get("新闻内容")),
            "source_name": str(row.get("文章来源", "东方财富")),
            "source_url": str(row.get("新闻链接", "")),
            "published_at": _parse_time(row.get("发布时间")),
        })
    return records


def _parse_time(t) -> Optional[datetime]:
    if t is None:
        return None
    if isinstance(t, datetime):
        return t
    if isinstance(t, date):
        return datetime.combine(t, datetime.min.time())
    try:
        return date_parser.parse(str(t))
    except (ValueError, TypeError):
        logger.debug(f"无法解析时间: {t!r}")
        return None
