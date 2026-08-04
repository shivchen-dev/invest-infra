# Implementation Plan: 东方财富 / 新浪 / 同花顺数据源接入

## Overview

将东方财富、新浪、同花顺作为 V2 独立只读 Provider 接入现有数据源契约、Catalog、Routing 与 Coverage 体系，用于历史行情、交叉校验及 ETF 基础信息辅助；默认关闭，真实网络请求必须显式启用。

## Architecture Decisions

- 每个来源使用独立 provider key：`eastmoney`、`sina`、`tonghuashun`。
- 复用现有 Adapter 边界：client / config / mapper / adapter，不直接写数据库，不参与候选池筛选。
- Provider 声明必须区分 dataset 与 capability，禁止把研究快照能力伪装成历史 OHLCV 覆盖。
- 无凭证或未显式启用时保持无网络行为；错误统一映射为 typed provider errors。
- 先实现可测试的只读请求与字段映射，再接入 Coverage 探针；真实全量覆盖率不作为本次默认验收条件。

## Task List

### Phase 1: Contract and routing

- [ ] 增加三个 Provider 声明、能力矩阵和工厂选择约束。
- [ ] 为三源增加配置骨架、禁用默认值和路由单元测试。

### Checkpoint: Contract

- [ ] Catalog、Factory、Routing 离线测试通过。
- [ ] 未启用时不发生网络请求。

### Phase 2: Provider adapters

- [ ] 实现东方财富只读 client / mapper / adapter 及离线 fixtures/tests。
- [ ] 实现新浪只读 client / mapper / adapter 及离线 fixtures/tests。
- [ ] 实现同花顺只读 client / mapper / adapter 及离线 fixtures/tests。

### Checkpoint: Adapters

- [ ] 三源字段映射、日期/复权口径、错误分类和脱敏测试通过。
- [ ] 适配器不写数据库、不修改候选池规则。

### Phase 3: Coverage integration

- [ ] 将三源接入 Coverage 输入构造和交叉校验所需的 dataset 声明。
- [ ] 增加代表性只读探测命令/报告格式，明确空覆盖与部分覆盖。

### Checkpoint: Complete

- [ ] 相关 lint、单元测试和架构检查通过。
- [ ] 工作树只包含本任务范围内的变更。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 非官方接口字段或限流策略变化 | High | 隔离 client/mapper；默认关闭；保留 typed failure |
| 三源复权口径不一致 | High | 将 adjustment 作为显式请求参数和证据元数据，禁止静默转换 |
| 某来源只能提供快照而非历史日线 | Medium | 按 capability 注册，路由拒绝能力不匹配 |
| 凭证或真实网络误触发 | High | enabled gate、无触网构造测试、日志脱敏 |

## Open Questions

- 三源的真实 API 凭证和允许的网络验收范围需在真实探测前单独确认；本实现阶段使用离线 fixtures 验证契约。
