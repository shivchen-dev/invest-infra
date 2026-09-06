# invest-infra 目标 Dataset 多源供给准入实施计划 v1.0

> 治理状态：`BLOCKED`（Gate DS-FM）
> 制定日期：2026-09-05
> 当前修订：2026-09-06；冻结个人非商业投研用途，改为“Gate 选定单一路径、按需收敛 evaluator、验证后再发布”
> 当前定位：Stage 4D Gate B2A 的唯一数据源准入实施计划
> 授权记录：用户于 2026-09-06 明确用途为个人投资研究参考，并明确授权“修正”本计划；代码实现仍须独立授权、派工和验收

## 1. 业务目标

免费或低权限数据源通常各自只覆盖部分板块分类、字段、时点或证券身份。当前目标不是等待一个万能高积分来源，也不是预建多源平台，而是由一个或多个已获准来源满足：

- `sector-ranking`：Industry、Concept 的排行输入；
- `sector-constituents`：板块成分、稳定证券身份和明确 `as_of`；
- 每份输入的真实来源、访问路径、时间、口径、artifact 和 hash lineage；
- 必要覆盖缺失或冲突未解决时 fail closed，阻止不可信输入进入 evaluator。

多源管理的业务价值是统一 Dataset 业务合同、准入结论、来源角色和停止条件；Provider 与 WorkBuddy Connector 继续分别执行。MVP 先选择一条能闭合业务合同的采集路径，不为尚未入选的第二条路径预建 Adapter。

本计划冻结的使用边界是：仅供 owner 个人、非商业投资研究参考；不向团队提供数据服务，不对外分发原始数据，不形成商业数据产品。代理或自动化代表 owner 执行采集、校验和研究处理仍属于内部流程，但不得绕过来源条款、访问权限、配额或第三方权利边界。

## 2. 核心原则

1. **统一业务输入，不统一采集生命周期。** Provider 和 Connector 保留各自合同；只有入选路径需要在 evaluator 内部形成相同板块输入不变量。
2. **多源覆盖优先，合同升级从证据。** 先判断现有 1.0 的“多语义 Dataset + Dataset 内 fallback”能否表达需求，再决定是否需要 2.0。
3. **先证明组合可行，再编码。** 来源集合不能满足业务合同时停止，不用控制面建设掩盖来源缺口。
4. **配置不越界。** `DataAcquisitionDefinition` 继续只描述 WorkBuddy DataRequest/DataBundle 路径；内部 Provider 不写入该合同，也不新增统一 Source Policy。
5. **兼容性收敛优先。** 保留现有 `evaluate_sector_bundle()`；只有入选 Provider 路径无法复用现有 evaluator 时，才抽取私有板块输入核心。
6. **来源级 lineage 不丢失。** 每个输入及输出记录可追溯真实上游、访问路径、`as_of`、artifact/batch 和 hash。
7. **旁证按需而非必建。** 首轮 shadow 可记录简单诊断；存在同分类、同时点且独立的第二来源时，也只有重复复算或审计需求已出现，才可另行批准正式 `CrossCheckReport`。
8. **准入与许可由人工决定。** ARC 提供技术证据；用户或指定治理负责人批准生产使用。

## 3. 最小多源语义

### 3.1 默认路径：复用 1.0

现有 `workbuddy-data-request/1.0` 已支持一个请求包含多个语义独立 Dataset；每个 Dataset 内部按 `allowed_connectors` 顺序执行同口径 fallback，并只接受一个最终成功来源。

DS-0M 已判定：**DataRequest/DataBundle 1.0 对 WorkBuddy Connector 路径语义充分，不启动 2.0。** 这不代表 MVP 必须同时实现 WorkBuddy 和内部 Provider。Gate DS-FM 必须先选定一条最小路径；内部 Provider 不伪装成 Connector，也不写入 `allowed_connectors`。

默认继续使用现有两个业务 Dataset：`sector-ranking` 和 `sector-constituents`。只有入选来源确实需要 Industry/Concept 分别供给且不能在来源 Adapter 内安全归一化时，才拆成以下候选 key：

```text
sector-ranking-industry
sector-ranking-concept
sector-constituents-industry
sector-constituents-concept
```

以上名称不预先冻结。不同分类体系不得仅按名称合并；可选旁证不要求单独 Dataset，除非真实 shadow 证明需要稳定复算和归档。

### 3.2 三种行为及边界

| 行为 | MVP 处理方式 | 约束 |
|---|---|---|
| `fallback` | 仅复用 WorkBuddy DataRequest/DataBundle 1.0 | 只在同 Dataset 的获准 Connector 之间切换；内部 Provider 首版不做自动跨源 fallback |
| `union` | evaluator 内部的板块专用归一化/组装 | 仅在入选路径需要多个语义独立 Dataset 时启用，不预建公开组装框架 |
| `corroboration` | shadow 诊断；满足复用或审计触发条件后才考虑 `CrossCheckReport` | 不平均、不覆盖；仅同分类、同时点、独立来源的预声明关键冲突可阻断 |

执行路径：

```text
Gate DS-FM 选定一条路径
  ├─ WorkBuddy → DataRequest/DataBundle 1.0 → 复用现有 codec 与 evaluate_sector_bundle()
  └─ Provider  → ProviderRequest/Attempt/Batch → 入选来源 Adapter
                                                    ↓
                              evaluator 私有 SectorDatasetSnapshot 不变量
                                                    ↓
                              校验/组装 Industry/Concept → sector evaluator
```

`ProviderRequest` 绑定单一 `provider_key`，`ProviderAttempt` 只表达该请求内的尝试，不等于跨 Provider fallback。首版 Provider 路径失败后 fail closed；切换来源须人工批准并创建新的请求/运行，不建设自动选源编排。

### 3.3 条件升级：何时才允许 2.0

只有 DS-0M 同时证明以下事实，才允许另立 DataRequest/DataBundle 2.0 设计任务：

- 同一逻辑记录必须同时使用两个以上来源才能满足必需字段；
- 不能合理拆成多个语义独立 Dataset；
- evaluator 确实需要字段级来源 lineage，而非 Dataset 级 lineage；
- 使用 1.0 会导致错误语义或不可审计，而不仅是不够“统一”。

2.0 不属于当前默认排期。触发后须单独评审影响面、兼容策略和迁移预算，Gate DS-FM 不自动授权其实现。

## 4. 最小设计

### 4.1 WorkBuddy Definition 的候选与正式发布

只有 Gate DS-FM 选中 WorkBuddy 路径时，才生成与入选 Connector 一致的候选 `DataAcquisitionDefinition`：

- 继续使用 `data-acquisition-definition/1.0` 和 WorkBuddy DataRequest/DataBundle 1.0；
- 只承载 Dataset key、必需字段、`as_of`/freshness、获准 Connector 顺序和 output contract；
- shadow run 通过显式候选 artifact 路径和 hash 运行，不加入 active catalog、不通过 active API 暴露；
- Gate B2A 通过且获得独立激活授权后，才更新 catalog/hash，使其成为 active Definition。

若 Gate 选中内部 Provider 路径，本切片不修改 WorkBuddy Definition。Provider 选择由该次获准运行的显式配置和 Gate 证据固定；不向现有 Definition 塞入 Provider、许可或组装配置。

### 4.2 evaluator 内部收敛

现有 `evaluate_sector_bundle()` 是兼容接口，必须保留。当前 WorkBuddy 路径已由 codec 和 evaluator 完成合同校验、组装和确定性计算，不额外增加透传型 WorkBuddy Adapter。

只有 Gate 选中 Provider 路径，且直接接入会复制板块校验/计算时，才在现有 evaluator 内部抽取私有 `SectorDatasetSnapshot` 不变量，并增加一个入选 Provider Adapter。该内部 seam 负责：

- 分类命名空间、字段、单位、`as_of`、稳定身份和完整度；
- 确定性 Industry/Concept 组装与 fail-closed；
- 保留 producer、真实 upstream、访问路径、artifact/batch 和 hash lineage。

不预先发布 `ValidatedSectorDataset[]`、`assemble_sector_snapshot()` 通用接口或第二个未使用 Adapter。若未来两个真实入口同时稳定使用相同不变量，再把私有 seam 提升为正式接口。

### 4.3 按需旁证

首轮 shadow 允许把限定样本对比写入运行诊断，不强制建设 `CrossCheckReport` 模型、Schema 或持久化：

- 旁证缺失不影响正式覆盖判定；
- 只有同分类、同时点且真实 owner 独立的来源才可作为有效旁证；
- 只有 Definition/Gate 预先声明的关键字段冲突才阻断，其他差异进入人工复核；
- 若真实运行证明需要重复查询、审计或第二个消费者，再单独批准正式 `CrossCheckReport`。

## 5. 范围

### 5.1 纳入

- 两个目标 Dataset 的多源贡献矩阵；
- 现有 1.0 合同适配性判断；
- 入选路径所需的候选 WorkBuddy Definition 或单个 Provider Adapter；
- 必要时对现有 evaluator 做兼容性内部收敛；
- 两次真实 shadow run 和 Gate B2A 验收；
- 现有 archive、Request/Attempt/Batch、DataBundle 和 hash lineage 复用。

### 5.2 明确不做

- 不默认建设 DataRequest/DataBundle 2.0；
- 不新增独立 DatasetSupplyPolicy 或通用 DatasetSupplyEngine；
- 不迁移全部 Provider、Connector、Tool 或 Dataset；
- 不建设动态权重、自动质量评分、成本优化、任意路由或管理 UI；
- 不把不同分类体系按名称自动映射；
- 不自动修复冲突、不平均数值、不由 AI 决定字段权威；
- 不把内部 Provider batch 强接入 WorkBuddy 链，也不把 Provider 名称写入 `allowed_connectors`；
- 不同时实现 WorkBuddy/Provider 两套 Adapter，不建设跨 Provider 自动 fallback；
- 不预建公开 `ValidatedSectorDataset`、通用组装接口或正式 CrossCheckReport 持久化；
- 不在 Gate B2A 前把候选 Definition 加入 active catalog；
- 不因本计划完成自动启用 Provider、激活策略或生成 Candidate。

## 6. 实施切片

### Slice DS-0M：多源贡献矩阵与合同判定（核证已完成，Gate 未通过）

**目标：** 判断来源集合能否覆盖业务合同，以及现有 1.0 是否足够。

**工作内容：**

- 复用 TDX、WeStock、MX、Tushare 等既有证据，只补能关闭未知项的探针；
- 按分类命名空间、字段、`as_of`、证券身份、分页、许可和限流建立贡献矩阵；
- 区分 contributor、corroborator 和同 Dataset fallback；
- 判断各贡献能否拆成语义独立 Dataset；
- 冻结 merge key、完整度、硬冲突和停止条件；
- 冻结实际使用场景为 owner 个人、非商业投资研究参考；不对团队提供数据服务、不对外分发原始数据、不形成商业数据产品，并按该场景收集许可证据。

**验收标准：**

- [x] 两个目标业务输入的必需覆盖均映射到具体来源，不以“多源”代替字段证据；
- [x] 同源不同访问路径不被误算为独立旁证；
- [x] 明确记录 WorkBuddy 路径 `1.0 sufficient`，并提供逐项理由；内部 Provider 不进入该合同，是否需要 Adapter 由 Gate 选路后决定；
- [ ] 分类、时点、身份和许可不存在需要运行时猜测的硬缺口；
- [x] 来源集合不能满足合同时继续 `BLOCKED`，不启动后续代码。

**核证结果（2026-09-06）：** 已按 A/B/C/U 证据等级完成 TDX Connector、WeStock MCP、MX-DS MCP、Tushare 四源核证，并复算既有响应证据 hash。官方复核进一步确认：Tushare DC 成员页只证明 Concept，不能证明 Industry；因此只有 Tushare TDX 组在文档层接近覆盖四个目标 Dataset。当前没有可准入的单一路径；分类修订、全量/重复 hash、目标接口频控和个人自动化留存许可仍未闭合。宿主机凭证可解析，但当前 Dagster 容器未挂载集中凭证，且宿主机/容器对 Tushare 均在 TLS 握手阶段失败；工作树只完成了 Compose 只读挂载配置，尚未部署。DS-0M 继续保持“证据完成、Gate 阻塞”，DS-C0/DS-1 不得启动。

**验证：** 贡献矩阵、真实探针/hash、许可证据、冲突样本复算和敏感信息扫描。

**依赖：** 2026-09-05/06 单源证据；v2.1.0 策略治理可并行。

**预计规模：** S，只读取证，不修改业务代码。

### Gate DS-FM：来源集合与合同路径可实施

- [ ] `sector-ranking`、`sector-constituents` 的业务覆盖均有具备准入可能的来源集合；
- [ ] 字段、时点、身份、分页、限流和许可符合已冻结使用场景；
- [x] 若选择 WorkBuddy，固定使用 DataRequest/DataBundle 1.0，不启动 2.0；
- [ ] 在 WorkBuddy Connector 或单一内部 Provider 中选定一条最小运行路径，不同时实现两条；
- [ ] 用户确认继续实施所选最小路径。

未通过 Gate DS-FM 时只更新证据。当前只冻结 WorkBuddy 1.0 的合同判断，尚未冻结 Provider Adapter。只有未来新证据推翻 DS-0M 判定时，才独立评审 2.0。

### Slice DS-C0：选定路径的最小代码收敛

**目标：** 先用 characterization tests 冻结现有行为，只在入选路径需要时解除 evaluator 对采集信封的耦合。

**验收标准：**

- [ ] 现有 `evaluate_sector_bundle()` 正常、负面和确定性行为由测试固定且保持兼容；
- [ ] WorkBuddy 入选时复用现有 codec/evaluator，本切片允许以“无需代码修改”关闭；
- [ ] Provider 入选时只抽取私有板块输入核心，不新增通用注册表、公开组装框架或第二个 Adapter。

**验证：** sector evaluator/CLI characterization tests、受影响 Pipeline 回归、Ruff、架构检查和 diff 审查。

**依赖：** Gate DS-FM 已选定一条运行路径。

**预计规模：** XS～M；WorkBuddy 路径可为零代码，Provider 路径最多 3～5 个文件。

### Slice DS-1：入选来源垂直接入

**目标：** 只实现 Gate 选定的来源路径，形成可执行但尚未 active 发布的候选输入链。

**验收标准：**

- [ ] WorkBuddy 路径使用候选 Definition + DataRequest/DataBundle 1.0；Provider 路径使用单一获准 ProviderRequest/Attempt/Batch；
- [ ] 每个实际 Dataset 有唯一 key、必需字段、时点、分类、完整度和停止条件；仅在真实分源需要时拆 Industry/Concept；
- [ ] 缺 Dataset、字段、时点、稳定身份或完整度不足时 fail closed；
- [ ] 输出保留 producer、真实来源、访问路径、artifact/batch 和 hash lineage；
- [ ] 未入选路径没有新增运行代码、配置或测试替身。

**验证：** 入选来源真实小样本、缺失/冲突/乱序负面测试、sector evaluator focused tests 和 Pipeline 回归。

**依赖：** DS-C0。

**预计规模：** M，单一垂直切片不超过 5 个文件；若超出则暂停并重新拆分。

### Slice DS-2：双次 shadow run 与 Gate 验收

**目标：** 用入选来源执行两次不生成正式 Candidate 的板块影子运行，验证确定性、业务覆盖和运行成本。

**验收标准：**

- [ ] 实际 Connector 或 Provider、参数、分页、样本量和失败证据可追溯；
- [ ] 相同规范化输入重复执行得到相同快照 hash 和 evaluator 输出；
- [ ] 记录调用次数、耗时、失败率、覆盖率和人工复核工作量；
- [ ] 资源成本与首批 Candidate 业务价值匹配，且未生成正式 Candidate。

**验证：** archive/lineage 读回、重复 hash、运行指标、focused/full regression 和人工验收记录；旁证仅作为可选诊断。

**依赖：** DS-1；真实凭证、限流和许可边界已确认。

**预计规模：** S，以运行验收为主；不新增平台能力。

### Gate B2A：目标 Dataset 可生产使用

- [ ] 两个目标业务输入均由未过期、证据完整且人工批准的来源集合覆盖；
- [ ] 每个 Dataset 的适用 fallback、组装键、完整度和停止条件可追溯；Provider 路径无 fallback 时须明确记录；
- [ ] 两次真实 shadow run 形成确定性输入与结果，硬冲突和覆盖不足均被拒绝；
- [ ] 可选旁证不被当作 evaluator 正式输入或运行必需依赖；
- [ ] producer、真实上游、请求、尝试、artifact、hash 和准入决定可追溯；
- [ ] 运行成本和人工复核负担已被业务接受。

Gate B2A 通过后，本计划只交付“可正式发布”的入选路径证据。随后须单独授权：激活获批 v2.1.0；若选中 WorkBuddy，则把候选 Definition 加入 active catalog；若选中 Provider，则启用获准 Provider 运行配置。此前不产生正式 Candidate。

## 7. 依赖顺序

```text
既有单源证据
  ↓
DS-0M 多源贡献矩阵 + 个人非商业场景 + WorkBuddy 1.0 判定
  ↓
Gate DS-FM：选定 WorkBuddy 或单一 Provider 路径
  ↓
DS-C0：characterization + 必要时私有 evaluator 收敛
  ↓
DS-1：只接入选定来源
  ↓
DS-2：两次 shadow run
  ↓
Gate B2A
  ↓（独立授权）
发布/启用入选路径 + 激活 v2.1.0

未来若新证据证明必须字段级多源且语义不可拆，另立 2.0 评审；不得自动编码。
```

v2.1.0 提案及 CIA/RAA 审核可与 DS-0M～DS-2 并行，但在 Gate B2A 通过前保持 inactive。

## 8. 抽象升级触发条件

满足以下条件并经独立评审后，才考虑把私有 seam 提升为正式接口或抽取通用供给模块：

- 至少两个真实采集入口已稳定运行并需要复用相同板块输入不变量；
- 第二个真实业务消费者或至少三个 Dataset 已出现重复逻辑；
- DS-0M 证明存在无法由语义独立 Dataset 表达的字段级多源组合；
- 删除候选模块会使已存在的复杂性重新散落，而不是只删除一层转发。

## 9. 全局验证与实施规则

- DS-0M 是硬性可行性 Gate，不能以模拟数据或治理代码替代；
- 当前只冻结 WorkBuddy DataRequest/DataBundle 1.0 的充分性，不预先冻结 Provider Adapter；
- DS-C0、DS-1、DS-2 是顺序执行的原子交付点；每次只允许一个写入型执行器；
- 每个切片执行前做删除测试；未入选 Adapter、跨 Provider fallback、正式 CrossCheckReport 和通用配置均延期；
- 代码实现必须通过仓库 `task-routing` 入口，由 ARC 独立检查 diff、测试、范围和工作树；
- 每个代码切片均需 focused tests、受影响包回归、Ruff、格式、架构和 `git diff --check`；
- 凭证不得进入命令、日志、报告或 artifact；
- 不得自动 commit、push、部署、重启、启用 Provider、激活策略或生成正式 Candidate。
