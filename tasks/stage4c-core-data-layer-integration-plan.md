# Stage 4C Core Data Layer Integration — 收敛实施计划

## Overview

Stage 4C 收敛为日频市场状态 MVP：以 Tushare/TDX 日线事实和版本化价格限制规则为
输入，发布 Market Breadth v2 与 Limit Sentiment。分钟线、板块、GUI 和 Research
扩展不再阻塞本阶段。

> 当前代码状态：Task 1–3 已由现有 Domain / Storage / Pipeline 实现和 focused
> tests 覆盖；Task 4 的 seeded replay、迁移链和降级测试已通过，Tushare/TDX
> 真实环境一致性与 Checkpoint B 签核仍待完成。

## Dependency Graph

```text
日线 Provider evidence
        ↓
stock_daily_bars + stock_price_limits
        ├── Market Breadth v2
        └── Limit Sentiment
                 ↓
       complete/partial observation
```

## Task 1：合同与规则冻结

**Acceptance criteria:**

- [x] `stock_price_limits` 的 Raw/Core 字段、规则版本、来源和状态明确；
- [x] 缺失前收、未知规则、停牌、过期和低覆盖率的 fail-closed 语义明确；
- [x] 不改变既有 Provider routing。

**Verification:** 规则 fixture、catalog/routing focused tests。
**Dependencies:** None。**Scope:** S。

## Task 2：价格限制事实持久化

**Acceptance criteria:**

- [x] migration、repository、Unit of Work 和发布服务完成；
- [x] 生成并保存 `stock_price_limits`，保留 batch、hash、parser/rule version；
- [x] 幂等、revision、重复证券和部分数据行为可重放。

**Verification:** persistence tests、migration round-trip、replay test。
**Dependencies:** Task 1。**Scope:** M。

## Task 3：日频 Analytics 收口

**Acceptance criteria:**

- [x] Market Breadth v2 和 Limit Sentiment 使用统一日频事实边界；
- [x] 只发布收盘可证明的涨跌停指标，盘中指标返回 unknown 或延期；
- [x] complete/partial/stale、hash 和 observation identity 稳定。

**Verification:** domain/pipeline tests、PostgreSQL round-trip、failure tests。
**Dependencies:** Task 2。**Scope:** M。

## Task 4：一致性与 Checkpoint B

**Acceptance criteria:**

- [~] Tushare/TDX 的 close、prev_close、覆盖率比较可审计；
- [x] 主源失败 fallback 不产生伪前收或静默补值；
- [x] migration rollback/upgrade、seeded replay 和故障降级通过。

**Verification:** 全量测试、Ruff、架构检查、`git diff --check`、工作树审计。
**Dependencies:** Task 3。**Scope:** M。

## Definition of Done

- [~] Task 1–4 全部完成；
- [x] 日频宽度和涨跌停情绪可独立重算；
- [x] 不完整或不可证明的数据不会发布为 complete；
- [ ] 用户审核通过后，4C-MVP 关闭。

## Deferred

板块轮动、分钟线、盘中事件、TDX GUI、gpcw 财务、Research Bundle 扩展，以及
资金流/Level-2/盘口、评分、回测、交易和 UI，另立项目处理。
