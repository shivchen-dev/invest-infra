"""P0 错误隔离 — pipeline 各步骤独立捕获，异常不向上传播"""

import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


class StepError(Exception):
    """记录单步失败，不阻断后续步骤"""
    def __init__(self, step_name: str, func_name: str, reason: str):
        self.step_name = step_name
        self.func_name = func_name
        self.reason = reason
        super().__init__(f"[{step_name}] {func_name} 失败: {reason}")


def safe_step(step_name: str):
    """
    装饰器：为 pipeline 步骤添加错误隔离。
    异常被捕获并记录，不阻断下游步骤。
    返回 {"status": "ok", ...} 或 {"status": "failed", "error": ...}
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> dict:
            try:
                result = func(*args, **kwargs)
                # 如果返回 dict 且包含 error 键，也视为失败
                if isinstance(result, dict) and result.get("error"):
                    logger.warning(f"[{step_name}] {func.__name__} 返回错误: {result.get('error')}")
                    return {"status": "failed", "step": step_name, "error": result.get("error")}
                return {"status": "ok", **result} if isinstance(result, dict) else {"status": "ok", "result": result}
            except Exception as e:
                logger.error(f"[{step_name}] {func.__name__} 异常: {e}", exc_info=True)
                return {"status": "failed", "step": step_name, "error": str(e)[:200]}
        return wrapper
    return decorator