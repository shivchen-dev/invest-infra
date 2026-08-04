# Implementation Plan: 东方财富 / 新浪 / 同花顺数据源接入（planned-only）

## Status

**De-scoped.** The three-provider plan originally proposed东方财富 / 新浪 /
同花顺 as independent V2 read-only providers. This slice removes the
unimplemented standalone provider skeleton packages
(`apps/pipeline/src/invest_pipeline/adapters/eastmoney`,
`adapters/sina`, `adapters/tonghuashun`) and the corresponding catalog
declarations (`EASTMONEY` / `SINA` / `TONGHUASHUN`) and provider-quality
ETF registry entries. The three sources are **not** selectable runtime
providers in V2 and the runtime factory surface remains the three-key
`fixture_dev` / `cifangquant` / `akshare` set.

The plan is kept here as **planned-only** documentation. A future ADR
may resurrect the plan; until that ADR lands the catalog carries no
declaration for the three sources.

## Overview (historical)

将东方财富、新浪、同花顺作为 V2 独立只读 Provider 接入现有数据源契约、Catalog、Routing 与 Coverage 体系，用于历史行情、交叉校验及 ETF 基础信息辅助；默认关闭，真实网络请求必须显式启用。

> 本计划在当前 slice 中**未实现**，仅作为 planned-only 记录。三源的
> 公开历史行情接口在 V2 中继续作为 AkShare 聚合库的内部上游：
> `ak.fund_etf_hist_sina`（新浪）与 `ak.fund_etf_hist_em`（东方财富）
> 由 `invest_pipeline.adapters.akshare.client` 直接调用，对应的
> `BarSource.source_key` 在 evidence 元数据中保留 `"sina"` 与
> `"eastmoney"` 字面值；同花顺没有对应的公开历史行情接口在当前 slice
> 中使用。

## Architecture Decisions

- （历史）每个来源使用独立 provider key：`eastmoney`、`sina`、
  `tonghuashun`。
- （历史）复用现有 Adapter 边界：client / config / mapper / adapter，
  不直接写数据库，不参与候选池筛选。
- （历史）Provider 声明必须区分 dataset 与 capability，禁止把研究快
  照能力伪装成历史 OHLCV 覆盖。
- （历史）无凭证或未显式启用时保持无网络行为；错误统一映射为 typed
  provider errors。
- （历史）先实现可测试的只读请求与字段映射，再接入 Coverage 探针；
  真实全量覆盖率不作为本次默认验收条件。
- **当前**：以上决策均处于 planned-only 状态，三源未注册为 runtime
  Provider；其公开历史行情接口仅作为 AkShare 聚合库的内部上游。

## Task List

### Phase 1: Contract and routing

- [ ] ~~增加三个 Provider 声明、能力矩阵和工厂选择约束。~~（已 de-scoped）
- [ ] ~~为三源增加配置骨架、禁用默认值和路由单元测试。~~（已 de-scoped；
      对应 `adapters/eastmoney` / `adapters/sina` / `adapters/tonghuashun`
      包已删除，单元测试已删除）

### Checkpoint: Contract

- [ ] ~~Catalog、Factory、Routing 离线测试通过。~~（planned-only；当前
      slice 不存在对应三源 catalog / routing 注册项）
- [ ] ~~未启用时不发生网络请求。~~（planned-only）

### Phase 2: Provider adapters

- [ ] ~~实现东方财富只读 client / mapper / adapter 及离线 fixtures/tests。~~
      （planned-only）
- [ ] ~~实现新浪只读 client / mapper / adapter 及离线 fixtures/tests。~~
      （planned-only）
- [ ] ~~实现同花顺只读 client / mapper / adapter 及离线 fixtures/tests。~~
      （planned-only）

### Checkpoint: Adapters

- [ ] ~~三源字段映射、日期/复权口径、错误分类和脱敏测试通过。~~（planned-only）
- [ ] ~~适配器不写数据库、不修改候选池规则。~~（planned-only）

### Phase 3: Coverage integration

- [ ] ~~将三源接入 Coverage 输入构造和交叉校验所需的 dataset 声明。~~
      （planned-only）
- [ ] ~~增加代表性只读探测命令/报告格式，明确空覆盖与部分覆盖。~~
      （planned-only）

### Checkpoint: Complete

- [ ] 相关 lint、单元测试和架构检查通过。
- [x] 工作树只包含本任务范围内的变更（移除 standalone skeletons +
      catalog / quality 注册项 + 更新测试 / 文档）。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 非官方接口字段或限流策略变化 | High | 隔离 client/mapper；默认关闭；保留 typed failure |
| 三源复权口径不一致 | High | 将 adjustment 作为显式请求参数和证据元数据，禁止静默转换 |
| 某来源只能提供快照而非历史日线 | Medium | 按 capability 注册，路由拒绝能力不匹配 |
| 凭证或真实网络误触发 | High | enabled gate、无触网构造测试、日志脱敏 |
| 未来误把三源当作 runtime Provider 注册 | Medium | 当前 slice 在 catalog 与 provider_quality 中均不注册三源；`test_provider_catalog.EastmoneySinaTonghuashunNotRuntimeTest` 钉死 `lookup_provider("eastmoney" / "sina" / "tonghuashun")` 抛 `KeyError`；`test_provider_quality.test_registry_excludes_three_provider_plan_keys` 钉死 ETF 注册表不包含三源 |

## Open Questions

- 三源的真实 API 凭证和允许的网络验收范围需在真实探测前单独确认；
  本实现阶段使用离线 fixtures 验证契约。
- 是否在后续 ADR 中将三源升级为独立的 runtime Provider：待未来
  ADR 决策；当前 slice 的 contract 是三源不进入 runtime catalog，
  其公开历史行情接口仅作为 AkShare 聚合库的内部上游。

## Sina / Eastmoney 作为 AkShare 内部上游

- V2 的 ETF 历史日线（`ak.fund_etf_hist_sina`）由 AkShare adapter
  作为首选路径调用；失败 / 空结果时回退到东方财富路径
  （`ak.fund_etf_hist_em`）。两条路径均通过
  `invest_pipeline.adapters.akshare.client.AkshareClient` 暴露，
  `BarSource.provider_key` 在 evidence 元数据中保留 `"sina"` /
  `"eastmoney"` 字面值，便于审计和回放。
- 同花顺（同花顺 iFinD / 10jqka）目前没有对应的开源历史行情
  endpoint 在 V2 中作为 AkShare 内部上游使用；其作为独立
  runtime Provider 的可能性留待未来 ADR 评估。