"""
log_redactor.py — 日志敏感信息脱敏 Filter (v1.0)

设计:
- SecretRedactorFilter(logging.Filter): 不丢日志,改 record.msg
- 预编译正则 _REDACT_PATTERNS: 4 个常见模式 (F-5 修复)
- install_redactor(logger_name): 一行装到指定 logger (N-2.2 实现)

覆盖模式:
1. key=value (例: password=abc123)
2. key: value (例: api_key: xyz)
3. key="value" (引号包裹)
4. Bearer xxx (HTTP Authorization header)

审计员: Arc
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

# F-5 修复: 模块级预编译正则,避免运行时反复编译
# 模式: key + 任意空白 + 分隔符 + 任意空白 + value → 保留 key + 任意空白 + 分隔符 + 任意空白,value 替 ***
# 关键: \s* 包含分隔符周围的空白(在 group 2 中),replacement 用 \1\2 完整保留
_REDACT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)(\b(?:password|passwd|pwd)(\s*[:=]\s*))["\']?[^\s"\'`,]+'), r'\1***'),
    (re.compile(r'(?i)(\b(?:token|api_key|apikey|secret|access_key)(\s*[:=]\s*))["\']?[^\s"\'`,]+'), r'\1***'),
    (re.compile(r'(?i)(\bauthorization(\s*[:=]\s*))["\']?bearer\s+[^\s"\'`,]+'), r'\1Bearer ***'),
    (re.compile(r'(?i)\bbearer\s+[a-zA-Z0-9._\-]{20,}'), r'Bearer ***'),
]


class SecretRedactorFilter(logging.Filter):
    """日志脱敏 Filter — 修改 record.msg 中敏感字段为 ***.

    用法:
        import logging
        logger = logging.getLogger("invest-infra")
        logger.addFilter(SecretRedactorFilter())

    后续 install_redactor() 函数(N-2.2)提供一行封装。
    """

    def __init__(self, extra_patterns: List[Tuple[re.Pattern, str]] = None) -> None:
        """初始化.

        Args:
            extra_patterns: 可选,项目特定的额外 (pattern, replacement) 元组列表
        """
        super().__init__()
        self._patterns = list(_REDACT_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """脱敏 record.msg 和 record.args.

        始终返回 True(不丢日志),只改 record 内容。
        关键:若 record.args 非空(说明 record.msg 是 %s 模板),不直接 redact msg,
        因为 %s 是占位符不是 secret。redact args 后,msg % redacted_args 产生最终脱敏输出。
        """
        # 1. redact record.args(逐个元素)
        if record.args:
            new_args = []
            for a in record.args:
                if isinstance(a, str):
                    new_args.append(_redact_string(a, self._patterns))
                else:
                    new_args.append(a)
            record.args = tuple(new_args)

        # 2. redact record.msg(仅当 args 为空时;否则 msg 是 %s 模板,不应动)
        if isinstance(record.msg, str) and not record.args:
            record.msg = _redact_string(record.msg, self._patterns)

        return True


def _redact_string(text: str, patterns: List[Tuple[re.Pattern, str]]) -> str:
    """对单字符串依次应用所有 pattern."""
    for pat, repl in patterns:
        text = pat.sub(repl, text)
    return text


def install_redactor(
    logger_name: str = "invest-infra",
    extra_patterns: Optional[List[Tuple[re.Pattern, str]]] = None,
) -> SecretRedactorFilter:
    """一行装脱敏 filter 到指定 logger.

    Args:
        logger_name: logger 名(默认 'invest-infra')
        extra_patterns: 可选,项目特定的额外 (pattern, replacement) 元组

    Returns:
        装上的 filter 实例(用于 uninstall 时 .removeFilter(filter))

    用法:
        from security.log_redactor import install_redactor
        install_redactor()  # 默认装到 'invest-infra' logger
    """
    logger = logging.getLogger(logger_name)
    f = SecretRedactorFilter(extra_patterns=extra_patterns)
    logger.addFilter(f)
    return f
