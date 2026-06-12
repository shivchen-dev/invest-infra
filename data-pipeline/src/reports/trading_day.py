"""
交易日判断模块
判断当前日期是否为 A 股交易日
"""
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import json

logger = logging.getLogger(__name__)

_CALENDAR_PATH = Path("/home/claw/invest-infra/data-pipeline/data/trading_calendar.json")

# 缓存池（模块级，惰性初始化）
_CACHED_TRADING_DATES: Optional[set[date]] = None
_cache_loaded = False


def _load_trading_dates() -> set[date]:
    """从本地 JSON 文件加载 A 股完整交易日历（优先）。

    文件由 scripts/save_trading_calendar.py 生成，包含 1990 年至今所有交易日。
    读取失败时回退到 HOLIDAYS_JSON 环境变量 → 硬编码节假日。
    """
    global _CACHED_TRADING_DATES

    if _CACHED_TRADING_DATES is not None:
        return _CACHED_TRADING_DATES

    if _CALENDAR_PATH.exists():
        try:
            with open(_CALENDAR_PATH) as f:
                data = json.load(f)
            dates = {date.fromisoformat(d) for d in data.get("trading_dates", [])}
            logger.info(f"从 {_CALENDAR_PATH} 加载 {len(dates)} 个交易日")
            _CACHED_TRADING_DATES = dates
            return dates
        except Exception as e:
            logger.warning(f"交易日历文件读取失败: {e}，回退到 HOLIDAYS_JSON")

    # 回退到 HOLIDAYS_JSON 环境变量
    try:
        raw = json.loads(os.environ.get("HOLIDAYS_JSON", ""))
        if isinstance(raw, list) and all(isinstance(d, str) for d in raw):
            dates = {date.fromisoformat(d) for d in raw}
            logger.info(f"从 HOLIDAYS_JSON 加载 {len(dates)} 个节假日")
            return dates
    except Exception as e:
        logger.warning(f"HOLIDAYS_JSON 解析失败: {e}，使用硬编码节假日")

    # 最终回退：硬编码节假日
    return {
        date(2026, 1, 1), date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17),
        date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 21),
        date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
        date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3), date(2026, 5, 4), date(2026, 5, 5),
        date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
        date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27),
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4),
        date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
        date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3),
        date(2027, 2, 14), date(2027, 2, 15), date(2027, 2, 16),
        date(2027, 2, 17), date(2027, 2, 18), date(2027, 2, 19), date(2027, 2, 20),
        date(2027, 4, 3), date(2027, 4, 4), date(2027, 4, 5),
        date(2027, 5, 1), date(2027, 5, 2), date(2027, 5, 3),
        date(2027, 6, 8), date(2027, 6, 9), date(2027, 6, 10),
        date(2027, 9, 15), date(2027, 9, 16), date(2027, 9, 17),
        date(2027, 10, 1), date(2027, 10, 2), date(2027, 10, 3),
        date(2027, 10, 4), date(2027, 10, 5), date(2027, 10, 6), date(2027, 10, 7),
    }


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    判断是否为 A 股交易日

    Args:
        check_date: 要检查的日期，默认为今天

    Returns:
        True 是交易日，False 不是
    """
    global _cache_loaded

    if not _cache_loaded:
        _load_trading_dates()
        _cache_loaded = True

    if check_date is None:
        check_date = date.today()

    # 有本地文件时：直接查交易日集合
    if _CACHED_TRADING_DATES is not None:
        return check_date in _CACHED_TRADING_DATES

    # 无本地文件时：周六周日直接 False
    if check_date.weekday() >= 5:
        return False

    holidays = _load_trading_dates()
    return check_date not in holidays


def get_last_trading_day(ref_date: Optional[date] = None) -> date:
    """获取指定日期最近的上一交易日"""
    if ref_date is None:
        ref_date = date.today()

    check_date = ref_date
    for _ in range(15):
        check_date = date.fromordinal(check_date.toordinal() - 1)
        if is_trading_day(check_date):
            return check_date

    return ref_date


def get_next_trading_day(ref_date: Optional[date] = None) -> date:
    """获取指定日期最近的下一交易日

    collector 15:05 采集的是"今天的市场数据"，但这份数据要让次交易日的 pre_market
    能读到。因此 collector 写入 snapshot 时用『下一交易日』作为 trade_date。
    """
    if ref_date is None:
        ref_date = date.today()

    check_date = date.fromordinal(ref_date.toordinal() + 1)
    for _ in range(15):
        if is_trading_day(check_date):
            return check_date
        check_date = date.fromordinal(check_date.toordinal() + 1)

    return ref_date  # 没找到就退回原地（不应发生）


def is_trading_time() -> bool:
    """判断当前是否在交易时间内"""
    now = datetime.now()
    if not is_trading_day(now.date()):
        return False
    hour = now.hour
    return 9 <= hour < 15


def get_trading_phase(now: Optional[datetime] = None) -> str:
    """获取当前交易阶段"""
    if now is None:
        now = datetime.now()

    hour = now.hour
    minute = now.minute
    time_val = hour * 60 + minute

    if not is_trading_day(now.date()):
        if time_val < 9 * 60:
            return "pre_market_before_open"
        return "closed"

    if time_val < 9 * 60:
        return "closed"
    if 9 * 60 <= time_val < 9 * 60 + 30:
        return "pre_market"
    if 9 * 60 + 30 <= time_val < 11 * 60 + 30:
        return "morning"
    if 11 * 60 + 30 <= time_val < 13 * 60:
        return "midday_break"
    if 13 * 60 <= time_val < 15 * 60:
        return "afternoon"
    return "after_hours"


if __name__ == "__main__":
    print(f"今日是交易日: {is_trading_day()}")
    print(f"当前交易阶段: {get_trading_phase()}")
    print(f"上一交易日: {get_last_trading_day()}")
