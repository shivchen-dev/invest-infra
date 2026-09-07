# 目标 Dataset DS-0M v1.1 差异验收记录

> 日期：2026-09-07（Asia/Shanghai）
>
> 基线：`5afd9e409ddc31a9ba50a4da12057feaa1cb8fab`
>
> 结论：`DS-0M_PARTIAL`；`Gate DS-FM = BLOCKED`
>
> 边界：只读复核既有证据、代码和测试；未执行真实来源探针，未修改业务代码、运行配置或历史数据，未批准来源、发布 Definition、激活策略或生成正式 Candidate。

## 1. 复核目的

在保留 2026-09-06 WorkBuddy 固定配方决定和 `b0c5493` DS-C0 实现的前提下，区分：

1. 仍可复用的历史事实；
2. v1.1 新增或收紧的验收差异；
3. 尚未定位或需要重新核证的证据；
4. 解除 Gate DS-FM 前必须取得的决定。

本记录不改写历史报告中的 `READY_FOR_DS-C0`。该结论在当时口径下证明了候选 shadow 配方可实施；现行 v1.1 Gate 增加了单位、分类身份、真实时点、完整度、使用条件和目标策略交接要求，因此历史结论不能直接外推为当前 Gate 已通过。

## 2. 历史事实复用

| 项目 | 可复用事实 | 证据 | 当前适用边界 |
|---|---|---|---|
| 执行路径 | WorkBuddy DataRequest/DataBundle 1.0 是已选 shadow 候选路径；不并行实现 Provider | `docs/research/sector-dataset-multisource-contribution-matrix-20260906.md` 第 4～6 节；`docs/research/sector-dataset-primary-source-evidence-20260906.md` 第 12 节 | 只证明候选配方与协议语义；不等于生产准入或当前 DS-FM 已通过 |
| 采集映射 | `sector-ranking` ← WeStock；`sector-constituent-memberships` ← WeStock；`sector-constituent-symbol-map` ← TDX | 同上 | 三个采集 Dataset 分别保留真实 producer/connector；系统内部再形成两个业务输入 |
| 协议能力 | DataBundle 1.0 支持多 Dataset、每 Dataset 恰好一个成功来源、请求/交付身份和分页声明 | `packages/domain/src/invest_domain/strategy/data_acquisition.py` | 结构自洽校验不能证明真实单位、上游完整度或使用许可 |
| DS-C0 实现 | `b0c5493` 已加入三 Dataset 窄 join，保留旧二 Dataset 入口，并对缺失、重复、歧义和额外映射 fail closed | `apps/pipeline/src/invest_pipeline/integrations/sector_evaluator.py`；`apps/pipeline/tests/unit/test_sector_evaluator.py` | 可复用实现与测试，不重复开发；仍需按 v1.1 差异补验收 |
| 历史验证 | 2026-09-07 复跑 sector evaluator/CLI、strategy governance/version CLI 共 66 项通过；API candidate-lineage service 43 项通过 | 本记录第 5 节 | 证明现有行为未回归；不证明目标 v2.1.0、真实来源或正式主链完成 |

## 3. v1.1 差异与缺口

| v1.1 要求 | 当前代码/证据事实 | 结论 | 责任与解除条件 |
|---|---|---|---|
| 分类与稳定身份 | 历史配方按 WeStock 板块身份、名称规范化和 TDX symbol repair 工作；当前 join key 仅含 `group/bd_code/name`，未携带或校验 taxonomy namespace，证券代码仅要求非空 | `OPEN` | 来源主线核证相同分类、同时点、一一映射；DS-C0/DS-1 仅在确认缺口后补稳定板块/交易所身份校验 |
| 单位与转换 | 历史证据记录 WeStock `turnover × 10,000 = CNY`；DataBundle 保存 `units`，但 evaluator 不校验单位，现有测试使用空 `units` | `OPEN` | 来源主线提供上游单位与转换证据；实现切片 fail closed 校验并测试，不以字段重命名代替换算 |
| 真实 `as_of` | WeStock ranking 的 `date` 参数曾静默失效；当前通用校验只比较请求与交付声明，不能证明声明来自上游 | `OPEN` | 固定 latest-only 交易日锚定规则及证据；来源不明或混合日期时拒绝 |
| 完整度 | 既有 11 组/371 条快照和 join 集合相等可复算；尚无目标范围的排行全集、逐入选板块成分计数及两次 shadow 完整度证明 | `OPEN` | DS-0M/DS-2 提供分页终态、上游总数或冻结清单对账；样本数量自洽不能替代完整度 |
| 频控、许可与留存 | 两份 2026-09-06 报告仍将 WeStock/TDX 的 QPS、配额、自动化留存条件列为 unknown | `OPEN` | 定位适用的一手条款或 owner 决定，冻结限制和停止规则 |
| 目标策略身份 | 当前 evaluator、Definition 和请求均绑定 v2.0.0；scoped profile 仍挂旧身份 | `OPEN` | 候选策略 Slice 1C-A 交付 CIA/RAA 审核并获准影子的 v2.1.0 artifact、决定引用和匹配 evaluator |
| artifact 可信加载 | evaluator 接受调用方 Mapping，信任自报 hash，缺失时补默认 hash；CLI 可读取任意本地 JSON | `OPEN` | Slice 1C-A/DS-C0 复用策略治理权威，按实际 artifact 内容计算 hash 并绑定审核对象；缺失或不一致 fail closed |
| 三 Dataset Definition | 当前静态 `sector-strength-ranking/1.0.0.json` 仍是 v2.0.0、旧二 Dataset 且要求 `zgb` | `OPEN` | 仅在目标要求和 DS-FM 决定明确后，由 DS-1 形成未激活候选 Definition；不得原地改写历史 artifact |

## 4. Gate 与后续顺序

### 4.1 当前可以确认

- 历史 WorkBuddy 配方仍是应优先复核的唯一候选，不重新铺开四源实现。
- DataRequest/DataBundle 1.0 无需因“三采集 Dataset、两业务输入”升级为 2.0。
- `b0c5493` 的 join 与现有测试继续作为 DS-C0 基线，不重做已满足部分。
- Slice 1C-A 必须在 DS-2 前提供可信、未激活的 v2.1.0 artifact、matching evaluator 和测试；这项工作不依赖 B2A 先通过。

### 4.2 当前不能确认

- 不能把历史 `READY_FOR_DS-C0` 直接登记为现行 DS-FM 通过。
- 不能开始 DS-C0 代码变更或 DS-1 接入。
- 不能发布/激活 Definition 或 StrategyVersion，不能执行正式 Candidate 链路。
- B2A 只覆盖板块 Dataset；不能替代个股输入核验或 Stage 4D Gate 3。

### 4.3 DS-FM 解除条件

1. CIA 固定 v2.1.0 目标数据要求的身份/hash、字段、单位、分类、时点、范围和停止条件；
2. 来源证据关闭本记录第 3 节的分类身份、单位、真实时点、完整度、频控/许可/留存缺口；
3. owner 确认历史 WorkBuddy 配方在上述范围继续适用，并记录批准人、日期、边界和停止规则；
4. 形成“历史 DS-C0 已覆盖 / 目标版本有意变化 / 必须局部修复”的逐项对照；
5. 仅在 Gate 记录完成后，按独立代码授权进入 DS-C0 差异验收。

## 5. 本轮验证

```text
git diff --check 8610418..5afd9e4                                  PASS
六份变更文档的仓库内 Markdown 相对链接                         PASS（0 missing）
apps/pipeline: sector evaluator/CLI + strategy governance/CLI     66 passed
apps/api: external workflow candidate-lineage service             43 passed, 1 deprecation warning
```

业务测试、真实来源探针、容器、生产数据库、发布和激活均未执行。

## 6. 生产者与持久化核对

- 当前代码已有 WorkBuddy DataBundle 归档、外部 WorkBuddy Candidate Intake、ExternalWorkflow metadata lineage 和只读投影。
- 当前尚未发现由投研系统正式生产并持久化 `SectorStageResult → StockStageResult → CandidateProposal(producer=invest-infra)` 的完整主链。
- Slice 2 必须冻结唯一持久化权威，分别保存上游 producer/provider、输入 artifact/batch、两个 StageResult、系统 Candidate 及 Admission/Research 关联；不得用临时 JSON 字段或外部 Candidate Bridge 代替。
- 新主链的实现与读回属于候选策略/Stage 4D 后续切片，不属于 DS-0M，也不因本记录获得授权。
