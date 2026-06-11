# 投研系统综合修复计划

**生成日期**: 2026-06-05  
**审计团队**: signals-auditor, factors-auditor, data-pipeline-auditor  
**审计范围**: `data-pipeline/src/` 全模块（signals / factors / collector）  
**问题总数**: 21 项（P0×6 + P1×8 + P2×6 + P3×1）  
**预计总工时**: ~61 小时  
**建议实施周期**: 5 周

---

## 一、问题汇总与优先级排序

### P0 级 — 紧急修复（本周内完成）

| # | 模块 | 问题 ID | 描述 | 影响 | 预计工时 |
|---|------|---------|------|------|----------|
| 1 | 数据采集层 | P0-2 | Pipeline 无错误隔离 | 单步失败阻断全流程 | 3-4h |
| 2 | 数据采集层 | P0-5 | 无告警通知机制 | 故障发现延迟 | 6-8h |
| 3 | Factors | F-BASE-01 | DataLoader 连接无超时设置 | 数据库连接挂起风险 | 0.5h |
| 4 | Factors | F-ENG-03 | 每次计算触发 sync_definitions_to_db() | 性能浪费，DB 压力 | 0.5h |
| 5 | 数据采集层 | P0-1 | 采集器无重试机制（tenacity 未充分利用） | 临时故障无法恢复 | 4-6h |
| 6 | 数据采集层 | P0-4 | scheduler_jobs 审计日志未实现 | 无法追溯执行历史 | 4-6h |

### P1 级 — 高优先级（第 2 周完成）

| # | 模块 | 问题 ID | 描述 | 影响 | 预计工时 |
|---|------|---------|------|------|----------|
| 7 | Signals | S-MD03 | etf/liquidity 维度完全相关（多重共线性） | 评分有效性受损 | 2h |
| 8 | Factors | F-REG-01 | 注册表非线程安全 | 多线程竞态风险 | 0.5h |
| 9 | Factors | F-ENG-05 | _compute_percentile 单元素边界缺日志 | 调试困难 | 0.5h |
| 10 | Factors | F-BASE-02 | load_latest_financial 未校验财报时效性 | 过期数据参与计算 | 1h |
| 11 | Factors | F-TECH-02/03 | NaN 处理不一致 | 评分污染风险 | 1h |
| 12 | 数据采集层 | P1-4 | 日志格式不统一 | 可观测性差 | 2-3h |
| 13 | Factors | F-ENG-04 | 部分因子计算器独立建连 | DB 连接泄漏风险 | 2h |
| 14 | 数据采集层 | P1-2 | 采集器全串行执行 | 性能瓶颈 | 8-12h |

### P2 级 — 中优先级（第 3-4 周完成）

| # | 模块 | 问题 ID | 描述 | 影响 | 预计工时 |
|---|------|---------|------|------|----------|
| 15 | Signals | S-MD01 | coverage 衰减导致评分分布不均匀 | 评分公平性受损 | 4h |
| 16 | Signals | S-MD02 | premium_rate NaN 值可能污染评分 | 计算异常风险 | 2h |
| 17 | Factors | F-ALT-01/02/03 | 另类因子连接复用与一致性问题 | DB 负载增加 | 1.5h |
| 18 | Factors | F-FUND-03 | iterrows() 循环性能差 | 大规模计算慢 | 2h |
| 19 | Factors | F-FUND-02 | ROE/ROA 使用最新一期而非 TTM | 指标不准确 | 2-3h |
| 20 | 数据采集层 | P1-3 | 跨源一致性校验缺失 | 数据质量风险 | 6-8h |

### P3 级 — 低优先级（第 5 周或后续迭代）

| # | 模块 | 问题 ID | 描述 | 影响 | 预计工时 |
|---|------|---------|------|------|----------|
| 21 | Signals | S-MD04 | DEFAULT_FILTERS 注释与实际不匹配 | 文档误导 | 1h |

---

## 二、修复实施计划（5 周）

### 第 1 周 — P0 基础修复

**目标**: 建立错误隔离框架，消除紧急风险

| 任务 | 负责人 | 依赖 | 工时 |
|------|--------|------|------|
| P0-2: Pipeline 错误隔离 | data-pipeline-auditor | 无 | 3-4h |
| F-BASE-01: DataLoader 超时补全 | factors-auditor | 无 | 0.5h |
| F-ENG-03: sync_definitions_to_db() 缓存 | factors-auditor | 无 | 0.5h |

**交付物**:
- `pipeline_main.py` 中所有步骤添加 `@safe_step` 装饰器
- `base.py` 连接参数扩展（keepalives + statement_timeout）
- `engine.py` 添加 `_SYNC_DEFS_DONE` 缓存标记

### 第 2 周 — P0 增强 + P1 基础

**目标**: 告警通知上线，修复高优先级问题

| 任务 | 负责人 | 依赖 | 工时 |
|------|--------|------|------|
| P0-5: 告警通知机制 | data-pipeline-auditor | P0-2 | 6-8h |
| S-MD03: etf/liquidity 多重共线性 | signals-auditor | 无 | 2h |
| F-REG-01: 注册表线程安全 | factors-auditor | 无 | 0.5h |
| F-ENG-05: _compute_percentile 边界日志 | factors-auditor | 无 | 0.5h |
| F-BASE-02: 财报时效性校验 | factors-auditor | 无 | 1h |
| F-TECH-02/03: NaN 处理统一 | factors-auditor | 无 | 1h |

**交付物**:
- `src/collector/alert.py` 告警模块（邮件/钉钉/企微）
- `scoring.py` 删除重复的 `scores["liquidity"]` 赋值
- `registry.py` 添加 `_REGISTRY_LOCK`
- `engine.py` 边界场景日志增强

### 第 3 周 — P0 收尾 + P1 优化

**目标**: 完成 P0 剩余任务，修复连接复用问题

| 任务 | 负责人 | 依赖 | 工时 |
|------|--------|------|------|
| P0-1: 重试机制重构（tenacity） | data-pipeline-auditor | 无 | 4-6h |
| P0-4: scheduler_jobs 审计日志 | data-pipeline-auditor | 无 | 4-6h |
| F-ENG-04: 因子计算器连接复用 | factors-auditor | 无 | 2h |

**交付物**:
- `retry.py` 重构为真正的 tenacity 装饰器
- `scheduler_jobs` 表 + pipeline 执行记录写入
- `technical.py` / `alternative.py` 计算器接受 `conn` 参数

### 第 4 周 — P2 修复

**目标**: 解决评分公平性、性能瓶颈问题

| 任务 | 负责人 | 依赖 | 工时 |
|------|--------|------|------|
| S-MD01: coverage 衰减改进 | signals-auditor | 无 | 4h |
| S-MD02: NaN 防护统一 | signals-auditor | 无 | 2h |
| F-ALT-01/02/03: 另类因子连接复用 | factors-auditor | P0-1 | 1.5h |
| F-FUND-03: iterrows → 向量化 | factors-auditor | 无 | 2h |

**交付物**:
- `alpha.py` coverage < 0.7 标记低置信度
- `scoring.py` 添加 `np.isnan()` 防护
- `fundamental.py` / `alternative.py` 向量化改造

### 第 5 周 — P2 收尾 + P3

**目标**: 完成剩余中优先级问题，修复文档

| 任务 | 负责人 | 依赖 | 工时 |
|------|--------|------|------|
| F-FUND-02: ROE/ROA TTM 计算 | factors-auditor | 无 | 2-3h |
| P1-4: 日志格式统一 | data-pipeline-auditor | 无 | 2-3h |
| P1-2: 采集器并发改造 | data-pipeline-auditor | P0-2, P0-5 | 8-12h |
| P1-3: 跨源一致性校验 | data-pipeline-auditor | P0-4 | 6-8h |
| S-MD04: DEFAULT_FILTERS 注释修复 | signals-auditor | 无 | 1h |

**交付物**:
- `fundamental.py` TTM 滚动计算实现
- 所有采集器日志统一 f-string + 前缀规范
- `pipeline_main.py` ThreadPoolExecutor 并发改造
- `consistency.py` 跨源校验模块
- `scoring.py` docstring 更新

---

## 三、跨模块共性问题识别

### 3.1 数据库连接管理不统一

**涉及问题**: F-BASE-01, F-ENG-04, F-ALT-01/02/03  
**根因**: 部分计算器独立 `psycopg2.connect()`，未复用 engine.py 传入的连接  
**建议方案**:
```python
# 统一接口：所有计算器接受 conn 参数
class FactorCalculator(ABC):
    def compute(self, company_ids, calc_date, conn=None, **kwargs):
        if conn is None:
            conn = psycopg2.connect(pg_cfg.uri)
            should_close = True
        else:
            should_close = False
        try:
            return self._compute(company_ids, calc_date, conn, **kwargs)
        finally:
            if should_close and conn:
                conn.close()
```

### 3.2 NaN/空值处理不一致

**涉及问题**: S-MD02, F-TECH-02/03  
**根因**: 各模块使用不同的空值检查方式（`is not None` vs `np.isnan()` vs `pd.notna()`）  
**建议方案**:
```python
# 统一工具函数
def safe_float(val):
    """安全转换为 float，NaN/None 返回 None"""
    if val is None:
        return None
    f = float(val)
    return None if np.isnan(f) else f
```

### 3.3 错误处理与可观测性不足

**涉及问题**: P0-2, P0-5, F-ENG-05, P1-4  
**根因**: 缺乏统一的错误隔离、告警通知和日志规范  
**建议方案**:
- 统一使用 `@safe_step` 装饰器
- 实现 `alert.py` 告警模块
- 统一日志格式（f-string + 模块前缀）

### 3.4 性能优化空间

**涉及问题**: F-FUND-03, P1-2, F-ENG-03  
**根因**: iterrows() 循环、串行采集、重复 sync_definitions_to_db()  
**建议方案**:
- pandas 向量化替代 iterrows()
- ThreadPoolExecutor 并发采集
- 缓存标记避免重复同步

---

## 四、风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| P1-2 并发改造引入新 bug | 数据采集错误 | 灰度发布，先对非核心数据源启用 |
| F-FUND-02 TTM 计算改变历史数据 | 回测结果变化 | 保留旧因子名 `roe`，新增 `roe_ttm` |
| P0-5 告警通知误报 | 告警疲劳 | 添加抑制机制（同一错误 1h 内只报一次） |
| S-MD03 删除 liquidity 维度 | 评分分布变化 | 回归测试验证评分相关性 |

---

## 五、验收标准

### P0 级验收
- [ ] Pipeline 单步失败不阻断后续步骤
- [ ] 关键错误触发外部告警（钉钉/企微）
- [ ] DataLoader 连接超时设置完整（connect + socket + statement）
- [ ] sync_definitions_to_db() 仅首次执行
- [ ] 采集器使用 tenacity 重试，支持 HTTP 4xx/5xx 区分
- [ ] scheduler_jobs 表记录每次 pipeline 执行

### P1 级验收
- [ ] etf/liquidity 维度不再完全相关（相关系数 < 0.9）
- [ ] registry.py 线程安全测试通过
- [ ] _compute_percentile 单元素场景有警告日志
- [ ] load_latest_financial 默认过滤 180 天以上财报
- [ ] technical.py NaN 处理统一返回 None
- [ ] 所有采集器日志格式统一

### P2 级验收
- [ ] coverage < 0.7 的股票标记低置信度
- [ ] score_etf() 中 NaN 值不污染评分
- [ ] 因子计算器连接复用率 > 90%
- [ ] iterrows() 全部替换为向量化操作
- [ ] ROE/ROA 使用 TTM 计算

### P3 级验收
- [ ] DEFAULT_FILTERS docstring 与实际值一致

---

## 六、工时汇总

| 模块 | P0 | P1 | P2 | P3 | 小计 |
|------|----|----|----|----|------|
| Signals | - | 2h | 6h | 1h | **9h** |
| Factors | 1.5h | 4h | 7.5h | - | **13h** |
| 数据采集层 | 17-20h | 12-15h | 6-8h | - | **35-43h** |
| **合计** | **18.5-21.5h** | **18-21h** | **19.5-21.5h** | **1h** | **~61h** |

---

*报告生成: 2026-06-05 22:40 CST*  
*审计团队: signals-auditor, factors-auditor, data-pipeline-auditor*
