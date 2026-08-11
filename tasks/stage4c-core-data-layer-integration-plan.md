# Stage 4C Core Data Layer Integration — Implementation Plan

## Overview

在 `4268f96` 基线上扩展分钟线、板块、涨跌停和 TDX GUI 分析结果。按垂直切片
推进，每个切片均完成 Raw evidence、Core facts、Analytics observation 和验收，
不进行 UI 开发。

## Architecture Decisions

- 保留现有 `tdx_offline`；`mootdx` 只做有边界复用。
- 新 dataset 使用独立 capability 和稳定持久化键。
- 当前板块只表达 snapshot，不伪造历史 effective period。
- 涨跌停由规范日线与版本化规则计算；盘中事件必须有分钟证据。
- GUI 是独立 `tdx_gui_analysis` Provider，不能旁路 Raw provenance。
- 每个阶段先冻结合同，再迁移、实现、编排和发布。

## Dependency Graph

```text
Dataset/Capability contracts
        ↓
Raw evidence + canonical facts
        ├── Daily limits ──→ Limit Sentiment
        ├── Block snapshot ─→ Block Rotation
        ├── Minute bars ────→ Intraday evidence
        └── GUI export ─────→ TDX analysis facts
                                  ↓
                       Market Observation snapshots
                                  ↓
                       ResearchEvidenceBundle
```

## Phase 0：Contract and feasibility baseline

### Task 0.1：冻结 dataset 与 capability

**Acceptance criteria:**

- 每个持久化键、Provider key、capability 和 owner 唯一；
- raw/core/analytics 字段边界明确；
- 旧 Provider 路由行为不变。

**Verification:** catalog/routing focused tests、architecture check。
**Dependencies:** None。
**Estimated scope:** M。

### Task 0.2：真实样本格式 Spike

**Acceptance criteria:**

- `.lc1/.lc5`、block、gpcw 各有样本清单与 hash；
- 输出字段、历史深度、更新时间和损坏行为有证据；
- 形成 `mootdx` wrapper/移植/自研选择 ADR。

**Verification:** golden fixtures、cross-reader comparison、license notice check。
**Dependencies:** Task 0.1。
**Estimated scope:** M。

### Task 0.3：覆盖率与容量基线

**Acceptance criteria:**

- 统计证券数、日期范围、缺口率和文件增长；
- 冻结 complete/partial/stale 阈值；
- 分钟线容量与运行时间有基准。

**Verification:** coverage report 可重复生成并绑定输入 hash。
**Dependencies:** Task 0.2。
**Estimated scope:** S。

### Checkpoint A

- [ ] 合同、ADR、样本与覆盖基线经人工审核；
- [ ] 不存在未明确许可证的代码复制；
- [ ] 生产依赖和 migration 尚未引入。

## Phase 1：Daily market-state slice

### Task 1.1：补齐 TDX 前收语义

**Acceptance criteria:**

- 由同一证券前一有效交易日 close 确定 `prev_close`；
- 首条、停牌、缺口和跨年行为显式；
- TDX fallback 可参与涨跌宽度计算。

**Verification:** reader/provider tests 与 Tushare 样本交叉检查。
**Dependencies:** Checkpoint A。
**Estimated scope:** M。

### Task 1.2：价格限制事实合同

**Acceptance criteria:**

- 覆盖主板、创业板、科创板、北交所和 ST 规则；
- 价格精度、舍入和生效日期版本化；
- 未知证券类别 fail-closed。

**Verification:** 规则边界 fixture、历史制度切换测试。
**Dependencies:** Task 1.1。
**Estimated scope:** M。

### Task 1.3：Market Breadth v2 与 Limit Sentiment

**Acceptance criteria:**

- 增加 MA60、新高/新低和涨跌停日频指标；
- 相同输入产生确定性 hash；
- partial/stale 不发布 complete snapshot。

**Verification:** domain、pipeline、PostgreSQL round-trip。
**Dependencies:** Tasks 1.1–1.2。
**Estimated scope:** M。

### Checkpoint B

- [ ] 日频宽度和涨跌停情绪可独立重算；
- [ ] Tushare 失败时 TDX fallback 不产生伪前收；
- [ ] migration upgrade/downgrade/upgrade 通过。

## Phase 2：Block rotation slice

### Task 2.1：板块字典与成员快照 Provider

**Acceptance criteria:**

- industry/concept/custom 分类明确；
- snapshot date、原文件 hash 和 parser version 可追溯；
- 删除或改名不会覆盖旧快照。

**Verification:** golden parser、幂等写入、snapshot diff tests。
**Dependencies:** Checkpoint A。
**Estimated scope:** M。

### Task 2.2：板块日频聚合与轮动观察

**Acceptance criteria:**

- 生成涨跌、成交额、上涨家数和扩散指标；
- 分母、停牌和未知成员处理固定；
- 当前 snapshot 不用于其日期之前。

**Verification:** fixture aggregation、look-ahead guard tests。
**Dependencies:** Task 2.1、Phase 1 daily facts。
**Estimated scope:** M。

### Checkpoint C

- [ ] 轮动快照可回溯至成员和日线批次；
- [ ] 无历史穿越；
- [ ] 缺失成员和低覆盖率正确降级。

## Phase 3：Minute-data slice

### Task 3.1：`.lc1/.lc5` 窄 reader

**Acceptance criteria:**

- 周期、时间和 Decimal 合同冻结；
- 文件损坏、乱序、重复和未来时间 fail-closed；
- 与参考 reader 的 golden 输出一致。

**Verification:** byte fixtures、property/boundary tests。
**Dependencies:** Checkpoint A。
**Estimated scope:** M。

### Task 3.2：分钟 Provider、增量和持久化

**Acceptance criteria:**

- 支持按证券、日期、周期增量高水位；
- revision 不覆盖历史 batch；
- 容量和运行时间符合 Phase 0 预算。

**Verification:** incremental replay、PostgreSQL round-trip、benchmark。
**Dependencies:** Task 3.1。
**Estimated scope:** M。

### Task 3.3：盘中事件证据

**Acceptance criteria:**

- 开板、封板和分钟动能只由分钟证据判定；
- 证据不足返回 unknown，而非 false；
- observation 绑定分钟 batch 和规则版本。

**Verification:** known/unknown event fixtures。
**Dependencies:** Task 3.2、Task 1.2。
**Estimated scope:** M。

### Checkpoint D

- [ ] 1/5 分钟数据可增量回放；
- [ ] 性能与存储预算通过；
- [ ] 日频与盘中证据边界清晰。

## Phase 4：TDX GUI analysis slice

### Task 4.1：状态机和运行合同

**Acceptance criteria:**

- 启动、登录、刷新、执行、导出、解析均为显式状态；
- 只允许运行白名单公式与证券范围；
- 超时、窗口漂移和登录失败 fail-closed。

**Verification:** state-transition tests 与独立容器演练。
**Dependencies:** Checkpoint A。
**Estimated scope:** M。

### Task 4.2：导出解析与 Raw evidence

**Acceptance criteria:**

- ASCII 文件名、GB18030、Tab/schema contract 固定；
- reported count、row count、schema、hash 一致；
- 原始导出和运行证据可追溯。

**Verification:** 已验证 489 行样本 golden test、损坏/错列测试。
**Dependencies:** Task 4.1。
**Estimated scope:** M。

### Task 4.3：单公式端到端发布

**Acceptance criteria:**

- 一个白名单公式无人值守完成分析和发布；
- 重跑幂等，输入或客户端版本变化生成新 batch；
- GUI 不直接写 Analytics 表。

**Verification:** seeded container E2E 与故障注入。
**Dependencies:** Task 4.2。
**Estimated scope:** M。

### Checkpoint E

- [ ] GUI 结果可审计、可重放，失败不污染 Core；
- [ ] 不依赖中文文件名或固定 sleep；
- [ ] 现有 TDX 实例不受影响。

## Phase 5：Research integration and acceptance

### Task 5.1：Observation 与 Bundle 注册

**Acceptance criteria:**

- 只绑定 complete snapshot；
- Bundle hash 包含新 snapshot identity；
- 旧 EvidencePack 与 ResearchRun 兼容。

**Verification:** bundle/context projection/fake runner tests。
**Dependencies:** Checkpoints B–E。
**Estimated scope:** M。

### Task 5.2：Stage 4C 验收

**Acceptance criteria:**

- seeded Case 可追溯到日线、分钟、板块、规则和 GUI batch；
- 主源失败、文件损坏、GUI 漂移按合同降级；
- 生成覆盖率、容量、许可证和最终验收报告。

**Verification:** focused suites、migration chain、architecture check、`git diff --check`。
**Dependencies:** Task 5.1。
**Estimated scope:** M。

## Parallelization

- Phase 1、Phase 2、Phase 3 reader 和 Phase 4 状态机可在 Phase 0 后并行；
- Dataset/Capability contract 和 migration 必须先串行冻结；
- Research Bundle 等待所有待注册 snapshot 合同稳定；
- 共享 Provider Catalog 或 migration 的任务不得并发修改。

## Deferred

- Dashboard/UI；
- 北向/主力资金流、Tick/Level-2/盘口；
- 私有在线协议生产化；
- 历史板块成员回填；
- 多公式批量自动化、投资评分、回测和交易。
