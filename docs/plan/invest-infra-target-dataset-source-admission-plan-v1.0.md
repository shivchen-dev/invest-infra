# invest-infra 目标 Dataset 多源供给准入实施计划 v1.0

> 治理状态：`ACTIVE`
> 当前检查点：`READY_FOR_DS-C0`（Gate DS-FM 已冻结 WorkBuddy 固定多源配方；生产准入仍待 Gate B2A）
> 制定日期：2026-09-05
> 当前修订：2026-09-06；冻结个人非商业投研用途，改为“Dataset 主轴管理、固定多源配方、按需收敛、验证后再发布”
> 当前定位：Stage 4D Gate B2A 的唯一数据源准入实施计划
> 授权记录：用户于 2026-09-06 明确用途为个人投资研究参考，并明确授权“修正”本计划；代码实现仍须独立授权、派工和验收

## 1. 业务目标

免费或低权限数据源通常各自只覆盖部分板块分类、字段、时点或证券身份。当前目标不是等待一个万能高积分来源，也不是预建多源平台，而是由一个或多个已获准来源满足：

- `sector-ranking`：Industry、Concept 的排行输入；
- `sector-constituents`：板块成分、稳定证券身份和明确 `as_of`；
- 每份输入的真实来源、访问路径、时间、口径、artifact 和 hash lineage；
- 必要覆盖缺失或冲突未解决时 fail closed，阻止不可信输入进入 evaluator。

多源管理的业务价值是统一 Dataset 业务合同、准入结论、来源角色和停止条件；Provider 与 WorkBuddy Connector 继续分别执行。MVP 以 Dataset 为调度主轴，为每个 Dataset 冻结一条确定性来源配方；同一配方可以使用多个已验证 Connector，但不得动态猜测、任意字段拼接或自动跨 Provider 选源。

本计划冻结的使用边界是：仅供 owner 个人、非商业投资研究参考；不向团队提供数据服务，不对外分发原始数据，不形成商业数据产品。代理或自动化代表 owner 执行采集、校验和研究处理仍属于内部流程，但不得绕过来源条款、访问权限、配额或第三方权利边界。

## 2. 核心原则

1. **Dataset 是业务主轴，Source 是运行视图。** 业务按 Dataset 定义字段、时点、完整度和停止条件；凭证、限流、健康状态按 Source 管理。Provider 和 Connector 保留各自生命周期。
2. **多源覆盖优先，合同升级从证据。** 先判断现有 1.0 的“多语义 Dataset + Dataset 内 fallback”能否表达需求，再决定是否需要 2.0。
3. **先证明组合可行，再编码。** 来源集合不能满足业务合同时停止，不用控制面建设掩盖来源缺口。
4. **统一绑定，不统一执行。** 用最小 `DatasetSourceBinding` 记录 Dataset 与 Source 的角色、顺序、工具和准入状态；`DataAcquisitionDefinition` 仍只描述 WorkBuddy 路径，内部 Provider 不写入该合同。
5. **兼容性收敛优先。** 保留现有 `evaluate_sector_bundle()`；只有入选 Provider 路径无法复用现有 evaluator 时，才抽取私有板块输入核心。
6. **来源级 lineage 不丢失。** 每个输入及输出记录可追溯真实上游、访问路径、`as_of`、artifact/batch 和 hash。
7. **旁证按需而非必建。** 首轮 shadow 可记录简单诊断；存在同分类、同时点且独立的第二来源时，也只有重复复算或审计需求已出现，才可另行批准正式 `CrossCheckReport`。
8. **准入与许可由人工决定。** ARC 提供技术证据；用户或指定治理负责人批准生产使用。

## 3. 最小多源语义

### 3.1 默认路径：复用 1.0

现有 `workbuddy-data-request/1.0` 已支持一个请求包含多个语义独立 Dataset；每个 Dataset 内部按 `allowed_connectors` 顺序执行同口径 fallback，并只接受一个最终成功来源。

DS-0M 已判定：**DataRequest/DataBundle 1.0 对 WorkBuddy Connector 路径语义充分，不启动 2.0。** 当前冻结 WorkBuddy 固定多源配方作为首个 shadow 路径；内部 Provider 是按 Dataset 独立登记的候选来源，不伪装成 Connector，也不写入 `allowed_connectors`。

业务输出仍是 `sector-ranking` 和 canonical `sector-constituents`。为满足 DataBundle 1.0“每个 Dataset 恰好一个成功 Connector”约束，冻结三个采集 Dataset：

```text
sector-ranking                  ← WeStock latest ranking
sector-constituent-memberships  ← WeStock 板块身份、名称、显式日期
sector-constituent-symbol-map   ← TDX 请求绑定板块内的 symbol/name 映射
```

evaluator 只在请求已冻结的 `(taxonomy_namespace, group, bd_code)` 范围内，以 NFKC + 去空白后的名称做确定性 join，生成原有 canonical `sector-constituents`。不得把两个成功 Connector 塞进同一 Dataset attempt，也不得跨分类体系仅按名称合并。Industry/Concept 暂不再预拆；真实 shadow 证明合同需要时再拆。

### 3.2 三种行为及边界

| 行为 | MVP 处理方式 | 约束 |
|---|---|---|
| `fallback` | 仅复用 WorkBuddy DataRequest/DataBundle 1.0 | 只在同 Dataset 的获准 Connector 之间切换；内部 Provider 首版不做自动跨源 fallback |
| `union` | evaluator 内部 join 三个已冻结采集 Dataset | 每个采集 Dataset 只有一个成功 Connector；保留各自 lineage，不预建公开组装框架 |
| `corroboration` | shadow 诊断；满足复用或审计触发条件后才考虑 `CrossCheckReport` | 不平均、不覆盖；仅同分类、同时点、独立来源的预声明关键冲突可阻断 |

执行路径：

```text
业务消费者 → DatasetSpec → DatasetSourceBinding
                           ├─ WorkBuddy Connector 固定配方 → DataRequest/DataBundle 1.0
                           └─ 内部 Provider 候选绑定 → ProviderRequest/Attempt/Batch
                                                        ↓
                         归一化、校验 Industry/Concept → sector evaluator
```

`ProviderRequest` 绑定单一 `provider_key`，`ProviderAttempt` 只表达该请求内的尝试，不等于跨 Provider fallback。Dataset 的固定 WorkBuddy 配方可以调用多个已声明 Connector，但必须冻结工具、参数、join key 和 lineage；内部 Provider 失败后仍 fail closed，不建设自动跨 Provider 选源编排。

### 3.3 条件升级：何时才允许 2.0

只有 DS-0M 同时证明以下事实，才允许另立 DataRequest/DataBundle 2.0 设计任务：

- 同一逻辑记录必须同时使用两个以上来源才能满足必需字段；
- 不能合理拆成多个语义独立 Dataset；
- evaluator 确实需要字段级来源 lineage，而非 Dataset 级 lineage；
- 使用 1.0 会导致错误语义或不可审计，而不仅是不够“统一”。

2.0 不属于当前默认排期。触发后须单独评审影响面、兼容策略和迁移预算，Gate DS-FM 不自动授权其实现。

## 4. 最小设计

### 4.0 统一登记模型

统一管理只增加三类静态事实，不新增运行时 Registry、动态评分或通用路由平台：

| 对象 | 主责 | 最小内容 |
|---|---|---|
| `DatasetSpec` | 业务合同 | `dataset_key`、必需字段/单位、`as_of`、完整度、身份和停止条件 |
| `SourceSpec` | 来源运行信息 | `source_key`、`provider/connector` 类型、凭证引用、限流、健康与许可边界 |
| `DatasetSourceBinding` | Dataset 与 Source 的确定性绑定 | 来源角色、固定工具/Adapter、顺序、覆盖范围和 `declared/probed/admitted/active` 状态 |

MVP 可由现有 Definition、Provider Catalog 和证据文档承载这些事实；只有发现同一事实重复维护并发生漂移时，才实现新的持久化模型。

### 4.1 WorkBuddy Definition 的候选与正式发布

Gate DS-FM 已选中 WorkBuddy 固定配方；DS-1 只生成与该配方一致的候选 `DataAcquisitionDefinition`：

- 继续使用 `data-acquisition-definition/1.0` 和 WorkBuddy DataRequest/DataBundle 1.0；
- 只承载 Dataset key、必需字段、`as_of`/freshness、获准 Connector 顺序和 output contract；
- shadow run 通过显式候选 artifact 路径和 hash 运行，不加入 active catalog、不通过 active API 暴露；
- Gate B2A 通过且获得独立激活授权后，才更新 catalog/hash，使其成为 active Definition。

内部 Provider 当前只保留候选绑定，不进入本切片。未来若独立准入 Provider，仍通过显式配置和 Gate 证据固定；不向现有 Definition 塞入 Provider、许可或组装配置。

### 4.2 evaluator 内部收敛

现有 `evaluate_sector_bundle()` 是兼容入口，StageResult 输出合同必须保留。当前 evaluator 只接受 `sector-ranking + sector-constituents`；DS-C0 需改为接受三个单来源采集 Dataset，并在内部完成窄 join：

- 复用现有 DataRequest/DataBundle codec 和通用合同校验，不增加透传型 WorkBuddy Adapter；
- 分别校验 ranking、membership、symbol-map 的字段、单位、`as_of`、完整度和唯一性；
- 仅在请求绑定的分类/板块范围内按规范化名称 join membership 与 symbol-map；
- 输出继续生成 canonical `sector-constituents` 与现有 StageResult，并保留三个 Dataset 各自的 connector、artifact 和 hash lineage；
- 缺失、重复、歧义、多余映射或日期不一致时 fail closed。

不发布 `ValidatedSectorDataset[]`、`assemble_sector_snapshot()` 通用接口，不增加 Provider Adapter。若未来第二个真实入口稳定使用相同不变量，再评审是否提升为正式接口。

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
- 冻结配方所需的候选 WorkBuddy Definition；
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
- [x] 明确记录 WorkBuddy 路径 `1.0 sufficient`，并提供“三个单来源采集 Dataset + evaluator 窄 join”的逐项理由；内部 Provider 不进入该合同；
- [x] 已知硬缺口已转为显式 latest-only、固定 repair 和 fail-closed 边界，不允许运行时猜测；
- [x] 单个候选来源不可用时只阻断该绑定，不再否定已验证的固定 Dataset 配方。

**核证结果（2026-09-06）：** 已按 A/B/C/U 证据等级完成 TDX Connector、WeStock MCP、MX-DS MCP、Tushare 四源核证，并复算既有响应证据 hash。既有覆盖报告同时证明：WeStock Industry Top20 为 20/20、Concept 为 802/802；11 个 Industry/Concept 样本组共 371 条成分可通过 WeStock 显式日期/名称与 TDX 证券代码补全形成可复算快照；TDX 个股筛选必需字段有效覆盖 6/6。由此冻结首个 shadow 配方：排行使用 WeStock 最新快照，成分使用 WeStock 日期/名称 + TDX symbol repair，并保留各来源 lineage。Tushare TDX 最新探针的 `40203` 只阻断该 Provider 候选绑定，不否定 WorkBuddy 配方。DS-0M 证据完成，Gate DS-FM 允许进入 DS-C0；历史时点、全量分页、分类修订、频控和许可仍是 Gate B2A 前必须关闭的生产准入项。

**验证：** 贡献矩阵、真实探针/hash、许可证据、冲突样本复算和敏感信息扫描。

**依赖：** 2026-09-05/06 单源证据；v2.1.0 策略治理可并行。

**预计规模：** S，只读取证，不修改业务代码。

### Gate DS-FM：Dataset 固定配方可实施

- [x] `sector-ranking`、`sector-constituents` 均已有可执行、可追溯的 WorkBuddy 固定多源配方；
- [x] 每个配方已冻结来源角色、字段映射、时间边界、join key 和 fail-closed 条件；
- [x] 固定使用 WorkBuddy DataRequest/DataBundle 1.0，不启动 2.0；
- [x] 首个 shadow 路径固定为 WorkBuddy；Tushare 等内部 Provider 只保留按 Dataset 登记的候选绑定，不同时实现；
- [x] 用户已授权继续修正并按该方向推进。

Gate DS-FM 只确认“能否执行 shadow”，不等于生产准入。历史时点、全集/分页、来源许可、频控和两次运行确定性在 Gate B2A 前必须关闭；任一运行无法满足请求时继续 fail closed。当前不实现 Provider Adapter；只有未来新证据推翻 1.0 判断时，才独立评审 2.0。

### Slice DS-C0：固定配方的最小代码收敛

**目标：** 先用 characterization tests 冻结现有行为，再让 evaluator 接受三个单来源采集 Dataset，并在内部生成兼容的 canonical `sector-constituents`。

**验收标准：**

- [ ] 现有 `evaluate_sector_bundle()` 正常、负面和确定性行为由测试固定且保持兼容；
- [ ] 保留 `evaluate_sector_bundle()` 入口与 StageResult 输出合同；
- [ ] 每个采集 Dataset 恰好一个成功 Connector，分别保留 attempt/artifact/hash lineage；
- [ ] membership 与 symbol-map 只按请求绑定分类和规范化名称确定性 join；缺失、重复、歧义或多余映射全部 fail closed；
- [ ] 不新增通用注册表、公开组装框架或 Provider Adapter。

**验证：** sector evaluator/CLI characterization tests、受影响 Pipeline 回归、Ruff、架构检查和 diff 审查。

**依赖：** Gate DS-FM 已冻结 WorkBuddy 固定多源配方。

**预计规模：** S；优先只修改候选 Definition、sector evaluator 和 focused tests，超出 4 个文件须暂停复核。

### Slice DS-1：入选 Dataset 配方垂直接入

**目标：** 只实现 Gate 冻结的 WorkBuddy Dataset 配方，形成可执行但尚未 active 发布的候选输入链。

**验收标准：**

- [ ] 使用候选 Definition + DataRequest/DataBundle 1.0 表达固定 Connector 配方；不新增 Provider 路径；
- [ ] 三个采集 Dataset 有唯一 key、必需字段、时点、分类、完整度和停止条件；Industry/Concept 暂不额外预拆；
- [ ] 缺 Dataset、字段、时点、稳定身份或完整度不足时 fail closed；
- [ ] 输出保留 producer、真实来源、访问路径、artifact/batch 和 hash lineage；
- [ ] 未入选路径没有新增运行代码、配置或测试替身。

**验证：** 入选来源真实小样本、缺失/冲突/乱序负面测试、sector evaluator focused tests 和 Pipeline 回归。

**依赖：** DS-C0。

**预计规模：** M，单一垂直切片不超过 5 个文件；若超出则暂停并重新拆分。

### Slice DS-2：双次 shadow run 与 Gate 验收

**目标：** 用冻结的 Dataset 配方执行两次不生成正式 Candidate 的板块影子运行，验证确定性、业务覆盖和运行成本。

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
- [ ] 每个 Dataset 的来源角色、固定工具、组装键、完整度和停止条件可追溯；
- [ ] 两次真实 shadow run 形成确定性输入与结果，硬冲突和覆盖不足均被拒绝；
- [ ] 可选旁证不被当作 evaluator 正式输入或运行必需依赖；
- [ ] producer、真实上游、请求、尝试、artifact、hash 和准入决定可追溯；
- [ ] 运行成本和人工复核负担已被业务接受。

Gate B2A 通过后，本计划只交付“可正式发布”的 Dataset 配方证据。随后须单独授权：把候选 WorkBuddy Definition 加入 active catalog，并激活获批 v2.1.0。此前不产生正式 Candidate。

## 7. 依赖顺序

```text
既有单源证据
  ↓
DS-0M 多源贡献矩阵 + 个人非商业场景 + WorkBuddy 1.0 判定
  ↓
Gate DS-FM：冻结 WorkBuddy Dataset 固定多源配方
  ↓
DS-C0：characterization + 必要时私有 evaluator 收敛
  ↓
DS-1：只接入冻结的 Dataset 配方
  ↓
DS-2：两次 shadow run
  ↓
Gate B2A
  ↓（独立授权）
发布 Dataset 配方 + 激活 v2.1.0

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
- 当前冻结 WorkBuddy DataRequest/DataBundle 1.0 和首个 Dataset 固定配方，不实现 Provider Adapter；
- DS-C0、DS-1、DS-2 是顺序执行的原子交付点；每次只允许一个写入型执行器；
- 每个切片执行前做删除测试；未入选 Adapter、跨 Provider fallback、正式 CrossCheckReport 和通用配置均延期；
- 代码实现必须通过仓库 `task-routing` 入口，由 ARC 独立检查 diff、测试、范围和工作树；
- 每个代码切片均需 focused tests、受影响包回归、Ruff、格式、架构和 `git diff --check`；
- 凭证不得进入命令、日志、报告或 artifact；
- 不得自动 commit、push、部署、重启、启用 Provider、激活策略或生成正式 Candidate。
