"""采集器重试装饰器 — 指数退避"""
import logging
from functools import wraps

from urllib.error import HTTPError, URLError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# 可重试：网络超时、HTTP 5xx、连接错误
RETRYABLE_EXCEPTIONS = (
    HTTPError,
    URLError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 25.0,
):
    """
    统一重试装饰器，适用于所有采集器 fetch_* 函数。

    Args:
        max_attempts: 最大尝试次数（含首次），默认3次
        min_wait: 首次重试等待秒数，默认1s
        max_wait: 最大等待秒数，默认25s（指数退避上限）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while attempt < max_attempts:
                try:
                    result = func(*args, **kwargs)
                    if result is not None and result != []:
                        if attempt > 0:
                            logger.info(f"{func.__name__} 重试成功 (attempt {attempt + 1})")
                        return result
                    # 首次返回空直接返回（停牌/数据不存在，不重试）
                    if attempt == 0:
                        return result
                    # 重试后仍为空，继续重试
                    if attempt < max_attempts - 1:
                        logger.warning(f"{func.__name__} 返回空，第{attempt + 1}次重试...")
                    return result
                except RETRYABLE_EXCEPTIONS as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(f"{func.__name__} 重试{max_attempts}次均失败: {e}")
                        return []
                    wait_s = min_wait * (2 ** (attempt - 1))
                    logger.warning(f"{func.__name__} 第{attempt}次失败 ({e})，{wait_s:.0f}s后重试...")
                    import time; time.sleep(wait_s)
            return []
        return wrapper
    return decorator