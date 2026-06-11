"""
交易日判断模块
判断当前日期是否为 A 股交易日
"""
import logging
from datetime import datetime, date
from typing import Optional
import json

logger = logging.getLogger(__name__)


def _load_holidays() -> set[date]:
    """惰性加载 A 股节假日集合。

    优先从环境变量 HOLIDAYS_JSON 读取（JSON 数组，格式 ["YYYY-MM-DD", ...]），
    未设置或解析失败时回退到硬编码的 2026-2027 年度节假日。
    """
    try:
        raw = json.loads(__import__("os").environ.get("HOLIDAYS_JSON", ""))
        if isinstance(raw, list) and all(isinstance(d, str) for d in raw):
            return {date.fromisoformat(d) for d in raw}
    except Exception as e:
        logger.warning("HOLIDAYS_JSON 解析失败，使用硬编码节假日: %s", e)

    # 2026-2027 A 股节假日（以国务院实际通知为准）
    return {
        # --- 2026 ---
        date(2026, 1, 1),   # 元旦
        date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17),
        date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
        date(2026, 2, 21), # 春节
        date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),   # 清明
        date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
        date(2026, 5, 4), date(2026, 5, 5),   # 劳动节
        date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21), # 端午
        date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27), # 中秋
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
        date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
        date(2026, 10, 7),   # 国庆
        # --- 2027 ---
        date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3),   # 元旦
        date(2027, 2, 14), date(2027, 2, 15), date(2027, 2, 16),
        date(2027, 2, 17), date(2027, 2, 18), date(2027, 2, 19),
        date(2027, 2, 20),   # 春节
        date(2027, 4, 3), date(2027, 4, 4), date(2027, 4, 5),   # 清明
        date(2027, 5, 1), date(2027, 5, 2), date(2027, 5, 3),   # 劳动节
        date(2027, 6, 8), date(2027, 6, 9), date(2027, 6, 10),  # 端午
        date(2027, 9, 15), date(2027, 9, 16), date(2027, 9, 17), # 中秋
        date(2027, 10, 1), date(2027, 10, 2), date(2027, 10, 3),
        date(2027, 10, 4), date(2027, 10, 5), date(2027, 10, 6),
        date(2027, 10, 7),   # 国庆
    }


# 缓存池（模块级，惰性初始化）
_CACHED_HOLIDAYS: Optional[set[date]] = None
_cache_loaded = False


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    判断是否为 A 股交易日

    Args:
        check_date: 要检查的日期，默认为今天

    Returns:
        True 是交易日，False 不是
    """
    global _CACHED_HOLIDAYS, _cache_loaded

    if not _cache_loaded:
        _CACHED_HOLIDAYS = _load_holidays()
        _cache_loaded = True

    if check_date is None:
        check_date = date.today()

    # 周六周日直接返回 False
    if check_date.weekday() >= 5:
        return False

    # A 股节假日
    if _CACHED_HOLIDAYS and check_date in _CACHED_HOLIDAYS:
        return False

    return True


def get_last_trading_day(ref_date: Optional[date] = None) -> date:
    """
    获取指定日期最近的上一交易日
    
    Args:
        ref_date: 参考日期，默认为今天
        
    Returns:
        最近的上一个交易日
    """
    if ref_date is None:
        ref_date = date.today()
    
    check_date = ref_date
    
    # 最多回溯 15 天（覆盖春节/国庆 8 天长假）
    for _ in range(15):
        check_date = date.fromordinal(check_date.toordinal() - 1)
        if is_trading_day(check_date):
            return check_date
    
    return ref_date  # 找不到则返回原日期


def is_trading_time() -> bool:
    """
    判断当前是否在交易时间内
    
    Returns:
        True 在交易时间内，False 不在
    """
    now = datetime.now()
    
    # 只在交易日的交易时间判断
    if not is_trading_day(now.date()):
        return False
    
    hour = now.hour
    
    # 盘前: 09:00-09:30
    # 盘中: 09:30-11:30, 13:00-15:00
    # 盘后: 15:00-15:30
    
    if hour >= 9 and hour < 15:
        return True
    
    return False


def get_trading_phase(now: Optional[datetime] = None) -> str:
    """
    获取当前交易阶段

    Args:
        now: 时间，默认为现在

    Returns:
        pre_market_before_open: 非交易日凌晨准备期 (00:00-08:59, 非交易日)
        pre_market: 盘前 (09:00-09:30)
        morning: 早盘 (09:30-11:30)
        midday_break: 午间休市 (11:30-13:00)
        afternoon: 下午盘 (13:00-15:00)
        after_hours: 盘后 (15:00+)
        closed: 休市
    """
    if now is None:
        now = datetime.now()

    hour = now.hour
    minute = now.minute
    time_val = hour * 60 + minute

    # 凌晨准备期：非交易日 00:00-08:59，区分于真正休市
    if not is_trading_day(now.date()) and time_val < 9 * 60:
        return "pre_market_before_open"

    if not is_trading_day(now.date()):
        return "closed"

    # 交易日 00:00-08:59：交易所未开，视为休市
    if time_val < 9 * 60:
        return "closed"
    
    hour = now.hour
    minute = now.minute
    time_val = hour * 60 + minute
    
    # 盘前 09:00-09:30
    if 9 * 60 <= time_val < 9 * 60 + 30:
        return "pre_market"
    
    # 早盘 09:30-11:30
    if 9 * 60 + 30 <= time_val < 11 * 60 + 30:
        return "morning"
    
    # 午间休市 11:30-13:00
    if 11 * 60 + 30 <= time_val < 13 * 60:
        return "midday_break"
    
    # 下午盘 13:00-15:00
    if 13 * 60 <= time_val < 15 * 60:
        return "afternoon"
    
    # 盘后 15:00+
    if time_val >= 15 * 60:
        return "after_hours"
    
    return "closed"


if __name__ == "__main__":
    print(f"今日是交易日: {is_trading_day()}")
    print(f"当前交易阶段: {get_trading_phase()}")
    print(f"上一交易日: {get_last_trading_day()}")