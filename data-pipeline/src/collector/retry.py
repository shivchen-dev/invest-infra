"""采集器重试装饰器 — 基于 tenacity 的指数退避重试。

用于所有采集器 fetch_* 函数，行为：
- 非空结果 → 立即返回（成功 / 停牌 / 数据不存在）
- HTTP 4xx → 不重试，返回 []（客户端错误不应重试）
- HTTP 5xx / URLError / ConnectionError / TimeoutError / OSError → 指数退避重试
- 首次调用返回空（None / []）→ 直接返回（停牌、数据不存在）
- 后续重试返回空 → 继续重试（瞬态空结果）

异常处理流程：
  func() 抛 HTTPError(4xx) → wrapper 捕获并返回 []，tenacity 看不到
  func() 抛 RETRYABLE_EXCEPTIONS → tenacity 拦截并重试
    → 成功 → retry_if_result 非空 → 正常返回
    → 结果空 → retry_if_result 触发重试直到耗尽 → RetryError → _catch_all → []
"""

import logging
from functools import wraps

from urllib.error import HTTPError, URLError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 25.0,
):
    """统一重试装饰器，适用于所有采集器 fetch_* 函数。

    Args:
        max_attempts: 最大尝试次数（含首次），默认 3 次
        min_wait:     首次重试等待秒数，默认 1 s
        max_wait:     最大等待秒数（指数退避上限），默认 25 s
    """

    def decorator(func):
        # ── _fetch_wrapper：捕获 HTTP 4xx 并返回 []，其余正常透过 ────────
        @wraps(func)
        def _fetch_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPError as e:
                # 4xx 客户端错误：不重试，返回空列表（tenacity 看不到异常）
                if 400 <= e.code < 500:
                    logger.warning("%s HTTP %d 不重试", func.__name__, e.code)
                    return []
                # 5xx 服务端错误：重新抛出，OSError 子类由 tenacity 捕获并重试
                raise

        # ── tenacity：异常驱动 + 结果驱动重试 ───────────────────────────
        _tenacity_wrapped = retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(min=min_wait, max=max_wait),
            retry=(
                retry_if_exception_type((OSError, ConnectionError, TimeoutError))
                | retry_if_result(lambda r: not r)
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )(_fetch_wrapper)

        # ── _catch_all：捕获所有异常（RetryError + 非 RETRYABLE），返回 []
        @wraps(func)
        def _catch_all(*args, **kwargs):
            try:
                return _tenacity_wrapped(*args, **kwargs)
            except Exception as e:
                logger.error("%s 执行异常: %s", func.__name__, e)
                return []

        return _catch_all

    return decorator
