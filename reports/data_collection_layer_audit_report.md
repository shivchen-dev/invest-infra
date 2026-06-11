# 数据采集层代码质量审计报告

**审计人**: data-pipeline-auditor  
**审计日期**: 2026-06-05  
**审计范围**: `data-pipeline/src/collector/*.py` 和 `data-pipeline/src/pipeline_main.py`  
**源码路径**: `/home/claw/invest-infra/data-pipeline/src/`

---

## 执行摘要

本次审计对数据采集层的 7 个未修复问题进行了源码级验证。验证结论如下：

| 问题 ID | 优先级 | 问题描述 | 验证结论 |
|---------|--------|----------|----------|
| P0-1 | P0 | 采集器无重试机制（tenacity 已引入但分散） | **部分修复** — with_retry 已实现但未使用 tenacity |
| P0-2 | P0 | Pipeline 无错误隔离 | **未修复** — safe_step 已定义但未使用 |
| P0-4 | P0 | scheduler_jobs 审计日志未实现 | **未修复** — 代码中不存在 |
| P0-5 | P0 | 无告警通知机制（部分修复） | **未修复** — 仅 logger 记录，无外部通知 |
| P1-2 | P1 | 采集器全串行执行 | **未修复** — 所有采集均为串行循环 |
| P1-3 | P1 | 跨源一致性校验缺失 | **未修复** — 无交叉验证逻辑 |
| P1-4 | P1 | 日志格式不统一 | **未修复** — % 格式化与 f-string 混用 |

---

## P0 级问题详情

### P0-1: 采集器无重试机制（tenacity 已引入但分散）

**当前状态**: ⚠️ 部分修复 — `with_retry` 装饰器已实现，但未使用 tenacity 库的成熟特性

**源码证据**:

文件: `src/collector/retry.py` (第 1-67 行)
```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

def with_retry(max_attempts=3, min_wait=1.0, max_wait=25.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while attempt < max_attempts:  # ← 手动 while 循环，未使用 tenacity
                try:
                    result = func(*args, **kwargs)
                    if result is not None and result != []:
                        return result
                    if attempt == 0:
                        return result
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
```

**问题分析**:
1. tenacity 库已导入（`stop_after_attempt`, `wait_exponential`, `retry_if_exception_type`, `before_sleep_log`），但实际实现完全使用手动 while 循环，未利用 tenacity 的装饰器能力
2. 重试逻辑存在缺陷：首次返回空结果直接返回（第 51-52 行），这意味着如果 API 因临时故障返回空数据，不会重试
3. `RETRYABLE_EXCEPTIONS` 包含 `HTTPError`, `URLError`, `ConnectionError`, `TimeoutError`, `OSError`，但未区分可重试和不可重试的 HTTP 状态码（如 4xx 不应重试）

**影响范围**: 所有采集器（cifang.py, financial.py, etf.py, rsscast.py, companies.py, quotes.py, news.py）均使用此装饰器

**修复建议**:
1. 重构 `with_retry` 为真正的 tenacity 装饰器，利用其成熟的重试策略
2. 添加 `retry_if_exception_type` 和 `retry_if_result` 条件判断
3. 区分 HTTP 4xx（不可重试）和 5xx（可重试）错误
4. 添加重试上限的可配置性

**预计工时**: 4-6 小时

---

### P0-2: Pipeline 无错误隔离

**当前状态**: ❌ 未修复 — `safe_step` 装饰器已定义但从未使用

**源码证据**:

文件: `src/pipeline/error_isolation.py` (第 1-37 行)
```python
class StepError(Exception):
    """记录单步失败，不阻断后续步骤"""
    def __init__(self, step_name: str, func_name: str, reason: str):
        self.step_name = step_name
        self.func_name = func_name
        self.reason = reason
        super().__init__(f"[{step_name}] {func_name} 失败: {reason}")

def safe_step(step_name: str):
    """装饰器：为 pipeline 步骤添加错误隔离"""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> dict:
            try:
                result = func(*args, **kwargs)
                if isinstance(result, dict) and result.get("error"):
                    logger.warning(f"[{step_name}] {func.__name__} 返回错误: {result.get('error')}")
                    return {"status": "failed", "step": step_name, "error": result.get("error")}
                return {"status": "ok", **result} if isinstance(result, dict) else {"status": "ok", "result": result}
            except Exception as e:
                logger.error(f"[{step_name}] {func.__name__} 异常: {e}", exc_info=True)
                return {"status": "failed", "step": step_name, "error": str(e)[:200]}
        return wrapper
    return decorator
```

文件: `src/pipeline/pipeline_main.py` (第 19 行)
```python
from src.pipeline.error_isolation import safe_step  # ← 已导入但未使用
```

**问题分析**:
1. `safe_step` 装饰器已完整实现，但 `pipeline_main.py` 中从未使用 `@safe_step("step_name")` 装饰任何函数
2. 当前 `run_all()` 和 `run_etf_pipeline()` 中的错误处理是手动的 try-except 块，虽然能捕获异常，但缺乏统一的错误隔离机制
3. 手动 try-except 导致代码重复，且错误信息格式不统一

**影响范围**: `run_all()`, `run_all_via_rsscast()`, `run_etf_pipeline()`, `run_cifang_etf_spot()`, `run_etf_spot_only()`

**修复建议**:
1. 为 `run_all()` 中的每个步骤（companies, quotes, financial, financial_indicator, news）添加 `@safe_step` 装饰器
2. 统一错误返回格式，便于后续分析和告警
3. 考虑将 `StepError` 异常用于跨步骤的错误传递

**预计工时**: 3-4 小时

---

### P0-4: scheduler_jobs 审计日志未实现

**当前状态**: ❌ 未修复 — 源码中不存在 scheduler_jobs 相关代码

**问题分析**:
1. 在 `pipeline_main.py` 和所有 collector 文件中，未发现任何与 `scheduler_jobs` 相关的表操作或审计日志记录
2. Pipeline 的执行结果（`result` dict）仅返回给调用方，未持久化到数据库
3. 无法追溯历史执行记录、失败原因、耗时统计等关键信息

**影响范围**: 所有 pipeline 执行过程均无持久化审计日志

**修复建议**:
1. 创建 `scheduler_jobs` 表（或复用现有调度表），记录每次 pipeline 执行的元数据
2. 在 `run_all()` 和 `run_etf_pipeline()` 结束时，将 `result` dict 写入数据库
3. 记录字段：job_id, started_at, finished_at, status, steps_json, error_message, source

**预计工时**: 4-6 小时

---

### P0-5: 无告警通知机制（部分修复）

**当前状态**: ❌ 未修复 — 仅使用 logger.warning/error 记录日志，无外部通知

**源码证据**:

文件: `src/pipeline/pipeline_main.py` (第 97, 119, 136 行等)
```python
logger.error(f"[run_all] companies 步骤异常: {e}")
logger.warning(f"[run_all] quotes.fetch_quotes({code}) 失败: {e}")
```

文件: `src/collector/cifang.py` (第 41, 44 行)
```python
logger.warning("次方量化请求超时: %s", path)
logger.warning("次方量化请求失败: %s -> %s", path, e)
```

**问题分析**:
1. 所有错误仅通过 `logger.warning` 和 `logger.error` 记录到日志系统
2. 无外部告警通知机制（邮件、钉钉、企业微信、Slack 等）
3. 无法在采集失败时及时通知运维人员，可能导致数据缺失问题延迟发现

**影响范围**: 所有采集器和 pipeline 步骤

**修复建议**:
1. 实现统一的告警通知模块 `src/collector/alert.py`
2. 支持多种通知渠道（邮件、钉钉 Webhook、企业微信 Webhook）
3. 在关键错误（如连续失败、数据为空）时触发告警
4. 添加告警抑制机制，避免频繁告警

**预计工时**: 6-8 小时

---

## P1 级问题详情

### P1-2: 采集器全串行执行

**当前状态**: ❌ 未修复 — 所有采集均为串行循环

**源码证据**:

文件: `src/pipeline/pipeline_main.py` (第 106-121 行)
```python
# Step 2: 股票行情 — 串行循环
for code in batch_codes:
    try:
        batch = quotes.fetch_quotes(code, start_date=start_date, end_date=today)
        if batch:
            q_total += len(batch)
            minio_loader.store_json(batch, mc.bucket_bronze_quotes, "quotes/daily", today)
            pg_loader.batch_upsert_quotes(batch)
    except Exception as e:
        q_errors += 1
        logger.warning(f"[run_all] quotes.fetch_quotes({code}) 失败: {e}")
    time.sleep(cc.request_interval)  # ← 串行 + 限流
```

文件: `src/pipeline/pipeline_main.py` (第 305-339 行)
```python
# ETF 历史K线 — 串行循环
for etf in target_etfs:
    try:
        code = etf["code"]
        hist = etf_collector.fetch_etf_hist(code, start_date=start_date, end_date=today)
        # ...
    except Exception as e:
        k_errors += 1
        logger.warning(f"[run_etf_pipeline] fetch_etf_hist({etf.get('code')}) 失败: {e}")
    time.sleep(cc.request_interval)  # ← 串行 + 限流
```

**问题分析**:
1. `run_all()` 中 quotes、financial、financial_indicator、news 四个步骤完全串行执行
2. 每个步骤内部对每只股票/ETF 也是串行调用，无法利用并发加速
3. 对于 50 只股票，quotes 步骤需要 50 * 平均请求时间 + 49 * request_interval 的时间

**影响范围**: `run_all()`, `run_all_via_rsscast()`, `run_etf_pipeline()`

**修复建议**:
1. 使用 `concurrent.futures.ThreadPoolExecutor` 实现并发采集
2. 保持 `time.sleep(cc.request_interval)` 作为限流机制，避免对数据源造成压力
3. 考虑使用异步 IO（asyncio + aiohttp）替代线程池

**预计工时**: 8-12 小时

---

### P1-3: 跨源一致性校验缺失

**当前状态**: ❌ 未修复 — 无交叉验证逻辑

**问题分析**:
1. 系统使用多个数据源（akshare、次方量化 cifang、RssCast），但各源之间无一致性校验
2. `batch_fetch_etf_hist()` 中有 fallback 机制（新浪→东财），但这是同源的 fallback，不是跨源校验
3. 无法检测某个数据源返回的数据是否存在系统性偏差或错误

**影响范围**: 所有多源采集场景

**修复建议**:
1. 实现跨源一致性校验模块 `src/collector/consistency.py`
2. 对关键数据（如 ETF 实时价格）进行多源交叉验证
3. 当不同源返回的数据差异超过阈值时，记录警告或触发告警

**预计工时**: 6-8 小时

---

### P1-4: 日志格式不统一

**当前状态**: ❌ 未修复 — % 格式化与 f-string 混用

**源码证据**:

文件: `src/collector/cifang.py` (第 37, 41, 44, 59, 85, 125, 155, 294, 363, 426 行)
```python
logger.warning("次方量化 API 异常: code=%s message=%s path=%s", d.get("code"), d.get("message"), path)  # ← % 格式化
logger.info("次方量化基金列表: %d 只", len(data))  # ← % 格式化
```

文件: `src/collector/financial.py` (第 52, 57, 68, 71, 109, 144, 150, 157, 223, 230, 235 行)
```python
logger.info(f"正在获取 {raw_code} 财报 ...")  # ← f-string
logger.error(f"{raw_code} 财报获取失败: {e}", exc_info=True)  # ← f-string
```

文件: `src/collector/etf.py` (第 24, 30, 134, 167, 172, 208, 283, 290 行)
```python
logger.info("正在获取 ETF 实时行情 (fund_etf_spot_em) ...")  # ← 无变量，纯字符串
logger.info(f"获取到 {len(df)} 只ETF")  # ← f-string
```

文件: `src/collector/companies.py` (第 28, 34, 97 行)
```python
logger.info("正在从 akshare 获取 A 股公司列表 ...")  # ← 无变量，纯字符串
logger.info(f"获取到 {len(df)} 条公司记录")  # ← f-string
```

**问题分析**:
1. `cifang.py` 使用 `%` 格式化（如 `"次方量化 API 异常: code=%s message=%s path=%s"`）
2. 其他文件（financial.py, etf.py, companies.py, quotes.py, news.py）使用 f-string（如 `f"正在获取 {raw_code} 财报 ..."`）
3. 日志前缀不统一：cifang.py 使用 `"次方量化..."`，其他文件使用模块名或无前缀

**影响范围**: 所有采集器文件的日志输出

**修复建议**:
1. 统一使用 f-string 格式化（Python 3.6+ 性能已优化）
2. 定义统一的日志前缀规范，如 `[cifang]`, `[akshare]`, `[rsscast]`
3. 创建统一的日志配置模块 `src/collector/logging_config.py`

**预计工时**: 2-3 小时

---

## 修复优先级排序

| 优先级 | 问题 ID | 问题描述 | 预计工时 | 依赖关系 |
|--------|---------|----------|----------|----------|
| P0 | P0-1 | 采集器无重试机制（tenacity 已引入但分散） | 4-6h | 无 |
| P0 | P0-2 | Pipeline 无错误隔离 | 3-4h | 无 |
| P0 | P0-4 | scheduler_jobs 审计日志未实现 | 4-6h | 无 |
| P0 | P0-5 | 无告警通知机制 | 6-8h | P0-2 |
| P1 | P1-4 | 日志格式不统一 | 2-3h | 无 |
| P1 | P1-2 | 采集器全串行执行 | 8-12h | P0-2, P0-5 |
| P1 | P1-3 | 跨源一致性校验缺失 | 6-8h | P0-4 |

**总预计工时**: 33-47 小时

---

## 修复建议实施顺序

1. **第一阶段（P0 基础）**: P0-2 → P0-1 → P0-4
   - 先实现错误隔离，为后续修复提供统一框架
   - 重构重试机制，利用 tenacity 的成熟特性
   - 实现审计日志，建立执行追溯能力

2. **第二阶段（P0 增强）**: P0-5 → P1-4
   - 基于错误隔离实现告警通知
   - 统一日志格式，提升可观测性

3. **第三阶段（P1 优化）**: P1-2 → P1-3
   - 实现并发采集，提升性能
   - 添加跨源一致性校验，提升数据质量

---

## 附录：源码文件清单

| 文件 | 行数 | 主要功能 |
|------|------|----------|
| `src/collector/retry.py` | 67 | 重试装饰器（手动实现） |
| `src/collector/cifang.py` | 431 | 次方量化 ETF 数据采集 |
| `src/collector/financial.py` | 259 | 财报数据采集 |
| `src/collector/etf.py` | 295 | ETF 数据采集（akshare） |
| `src/collector/rsscast.py` | 326 | RssCast MCP 数据采集 |
| `src/collector/companies.py` | 98 | 公司列表采集 |
| `src/collector/quotes.py` | 97 | 日行情数据采集 |
| `src/collector/news.py` | 54 | 新闻数据采集 |
| `src/pipeline/error_isolation.py` | 37 | 错误隔离装饰器（未使用） |
| `src/pipeline/pipeline_main.py` | 363 | Pipeline 主编排器 |
