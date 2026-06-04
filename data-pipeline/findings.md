# Findings: pg.py 基础函数修复

## Batch 1 任务
修复 pg.py 中两个 P0 缺陷：
1. `_nan_to_none`: 不处理字符串 "NaN"/"inf"/pandas NA
2. `_normalize_date`: 仅处理 ISO T 格式，无日期验证

## 修复方案

### NV1: _nan_to_none
```python
def _nan_to_none(v):
    if v is None:
        return None
    # 处理 pandas NA/NaT
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (ImportError, TypeError):
        pass
    # 处理字符串形式的 NaN/Inf
    if isinstance(v, str) and v.lower() in ("nan", "inf", "-inf", "none", "null"):
        return None
    # 处理数值类型的 NaN/Inf
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except (TypeError, ValueError):
        pass
    return v
```

### DV1: _normalize_date
```python
from datetime import date as date_type
from dateutil import parser as date_parser

def _normalize_date(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (date_type, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        if "T" in v:
            return v.split("T")[0]
        v = v.replace("/", "-")
        try:
            parsed = date_parser.parse(v[:10])
            return parsed.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(f"无法解析日期: {v!r}")
            return None
    return str(v)
```

## 依赖
- `dateutil` 库（Python 内置，无需 pip install）